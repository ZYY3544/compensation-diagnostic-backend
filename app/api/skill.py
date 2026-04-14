"""
统一能力入口：
POST /api/skill/classify-intent  — 识别意图
POST /api/skill/invoke            — 调用能力
GET  /api/skill/registry          — 获取能力列表（前端欢迎页 chip 用）
"""
import os
import json
import traceback
import importlib
from flask import Blueprint, jsonify, request
from app.skills import get_registry
from app.services.intent_router import classify_intent
from app.models import new_id, now_iso

skill_bp = Blueprint('skill', __name__)


@skill_bp.route('/registry', methods=['GET'])
def get_registry_endpoint():
    """返回所有有 chip_label 的能力，供前端欢迎页展示"""
    registry = get_registry()
    only_chips = request.args.get('only_chips', 'true').lower() == 'true'
    skills = registry.list_chips() if only_chips else registry.list_all()
    return jsonify({
        'skills': [
            {
                'key': s['key'],
                'display_name': s['display_name'],
                'mode': s['mode'],
                'chip_label': s.get('chip_label'),
                'preconditions': s.get('preconditions', []),
            }
            for s in skills
        ]
    })


@skill_bp.route('/classify-intent', methods=['POST'])
def classify():
    """意图识别：用户消息 → skill_key"""
    data = request.json or {}
    message = data.get('message', '')
    context = data.get('context', {})
    result = classify_intent(message, context)
    return jsonify(result)


@skill_bp.route('/invoke', methods=['POST'])
def invoke():
    """
    调用一个 skill。
    请求：{ 'skill_key': '...', 'session_id': '...', 'params': {...} }
    返回：{ 'result': {...}, 'narrative': '...', 'skill': {...} }
    """
    data = request.json or {}
    skill_key = data.get('skill_key', '')
    session_id = data.get('session_id', '')
    params = data.get('params', {}) or {}

    registry = get_registry()
    skill = registry.get(skill_key)
    if not skill:
        return jsonify({'error': f'Unknown skill: {skill_key}'}), 404

    # 取 session 数据
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id) if session_id else None
    employees = (session.get('cleaned_employees') or session.get('_employees', [])) if session else []

    # 检查前置条件
    context = {
        'has_data_snapshot': bool(employees) or bool(session and session.get('snapshot_id')),
        'has_market_data': True,  # 默认有（static/市场薪酬数据.xlsx 已加载）
        'has_performance_data': bool([e for e in employees if e.get('performance')]),
        'has_business_data': bool(session and session.get('parse_result', {}).get('sheet2_summary', {}).get('metrics')),
    }
    unmet = registry.check_preconditions(skill_key, context)
    if unmet:
        readable = _precondition_readable(unmet)
        return jsonify({'error': f'前置条件未满足: {readable}', 'unmet': unmet}), 400

    # 检查必填参数
    missing = registry.get_missing_params(skill_key, params)
    if missing:
        return jsonify({'error': 'missing_params', 'missing': missing}), 400
    # 补 default 值
    params = registry.apply_defaults(skill_key, params)

    # 执行 engine
    engine_path = skill.get('engine', '')
    if engine_path == 'none':
        # 不需要引擎（如 general_question）
        result = {'question': params.get('question', '')}
    else:
        engine_fn = _resolve_engine(engine_path)
        if not engine_fn:
            return jsonify({'error': f'Engine not implemented: {engine_path}', 'skill': skill_key}), 501
        try:
            # 构造 data_snapshot（符合 engine 统一签名）
            data_snapshot = _build_data_snapshot(session)
            result = engine_fn(data_snapshot, params)
        except Exception as e:
            print(f'[Skill] {skill_key} engine failed: {e}')
            traceback.print_exc()
            return jsonify({'error': f'Engine execution failed: {str(e)}'}), 500

    # 生成 narrative（AI 解读）
    narrative = _generate_narrative(skill, result, session)

    # 记录调用
    if session is not None:
        invocations = session.setdefault('_skill_invocations', [])
        invocations.append({
            'invocation_id': new_id('inv_'),
            'skill_key': skill_key,
            'invoked_at': now_iso(),
            'params': params,
            'result': result,
            'narrative': narrative,
        })

    return jsonify({
        'skill': {
            'key': skill['key'],
            'display_name': skill['display_name'],
            'render_components': skill.get('render_components', []),
        },
        'result': result,
        'narrative': narrative,
    })


def _resolve_engine(engine_path: str):
    """按路径动态加载 engine 函数"""
    if not engine_path or engine_path == 'none':
        return None
    try:
        module_path, fn_name = engine_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        return getattr(module, fn_name, None)
    except Exception as e:
        print(f'[Skill] Failed to resolve engine {engine_path}: {e}')
        return None


def _build_data_snapshot(session: dict | None) -> dict:
    """构造统一的 data_snapshot 传给 engine 函数"""
    if not session:
        return {'employees': [], 'interview_notes': None, 'full_analysis': None}
    # 预热全量分析缓存
    try:
        from app.services.full_analysis import get_or_compute
        full = get_or_compute(session)
    except Exception as e:
        print(f'[Skill] full_analysis failed: {e}')
        full = None
    return {
        'employees': session.get('cleaned_employees') or session.get('_employees', []),
        'interview_notes': session.get('interview_notes'),
        'full_analysis': full,
        'grade_mapping': session.get('_grade_match_result', {}).get('grade_mapping'),
        'func_mapping': session.get('_func_match_result', {}).get('family_table'),
    }


def _precondition_readable(unmet: list) -> str:
    mp = {
        'has_data_snapshot': '需要先上传薪酬数据',
        'has_market_data': '市场薪酬数据未加载',
        'has_performance_data': '需要数据中包含绩效字段',
        'has_business_data': '需要上传公司经营数据（Sheet 2）',
    }
    return '；'.join(mp.get(u, u) for u in unmet)


def _generate_narrative(skill: dict, result: dict, session: dict | None) -> str:
    """让 AI 根据 skill 结果生成解读文案"""
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        return _fallback_narrative(skill, result)

    prompt_file = skill.get('narrative_prompt', '').strip()
    if prompt_file.startswith('prompts/'):
        prompt_file = prompt_file[len('prompts/'):]

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.5)
        try:
            system_prompt = agent.load_prompt(prompt_file)
        except Exception:
            system_prompt = (
                "你是 Sparky，铭曦产品的 AI 薪酬顾问。"
                f"用户刚使用了「{skill['display_name']}」能力，系统算出了结果。"
                "请用 2-4 句自然口语解读这个结果，给用户判断，不要只是复述数字。"
                "如果访谈背景里有相关信息，关联起来。只输出文本，不要 markdown。"
            )

        interview = session.get('interview_notes', {}) if session else {}
        user_content = json.dumps({
            'skill': skill['key'],
            'result': result,
            'interview': str(interview)[:800] if interview else None,
        }, ensure_ascii=False)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        return agent.call_llm(messages).strip()
    except Exception as e:
        print(f'[Skill] narrative generation failed: {e}')
        return _fallback_narrative(skill, result)


def _fallback_narrative(skill: dict, result: dict) -> str:
    if result.get('error'):
        return f"执行「{skill['display_name']}」时遇到问题：{result['error']}"
    return f"「{skill['display_name']}」已完成，请查看右边的结果详情。"
