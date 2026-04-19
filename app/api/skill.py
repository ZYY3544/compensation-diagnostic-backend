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

    # 构建前置条件 context
    # ⚠️ 修正：原来 has_data_snapshot 还判 session.get('snapshot_id')，但 snapshot_id
    # 在 session 创建时就有，导致只要会话存在就被认为有数据 → preconditions 形同虚设。
    # 现在严格只看是否真的解析到员工数据。
    context = {
        'has_data_snapshot': bool(employees),
        'has_market_data': True,  # 默认有（static/市场薪酬数据.xlsx 已加载）
        'has_performance_data': bool([e for e in employees if e.get('performance')]),
        'has_business_data': bool(session and session.get('parse_result', {}).get('sheet2_summary', {}).get('metrics')),
    }
    unmet = registry.check_preconditions(skill_key, context)
    print(f'[Skill] {skill_key} preconditions check: context={context}, unmet={unmet}')
    if unmet:
        readable = _precondition_readable(unmet)
        # 走 Sparky 友好提示，不出右侧面板，不调 engine，不调叙事
        return jsonify({
            'error': f'前置条件未满足: {readable}',
            'unmet': unmet,
            'sparky_message': _sparky_precondition_message(unmet),
            'skill': {
                'key': skill['key'],
                'display_name': skill['display_name'],
                'render_components': [],   # 显式空数组，前端不应渲染面板
            },
        }), 400

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
        # cost_trend / labor_cost engine 需要这个，否则 KPI 全 None
        'sheet2_summary': session.get('parse_result', {}).get('sheet2_summary'),
    }


def _precondition_readable(unmet: list) -> str:
    mp = {
        'has_data_snapshot': '需要先上传薪酬数据',
        'has_market_data': '市场薪酬数据未加载',
        'has_performance_data': '需要数据中包含绩效字段',
        'has_business_data': '需要上传公司经营数据（Sheet 2）',
    }
    return '；'.join(mp.get(u, u) for u in unmet)


def _sparky_precondition_message(unmet: list) -> str:
    """preconditions 不满足时给用户的 Sparky 口吻提示，由前端直接 streamMsg 展示"""
    if 'has_data_snapshot' in unmet:
        return '这个分析需要先上传薪酬数据。把 Excel 发给我，我帮你跑一遍。'
    if 'has_business_data' in unmet:
        return '这个需要公司经营数据（Sheet 2 里的营收、人数、人工成本）。补完上传后我再帮你看趋势。'
    if 'has_performance_data' in unmet:
        return '你上传的数据里没有绩效字段。补一列绩效等级（如 A/B/C 或 优秀/良好）再上传我就能算了。'
    return '前置条件还没满足：' + _precondition_readable(unmet)


# 引擎结果里"关键字段都没数据"——叙事引擎不许调 AI（防止凭空编造）
_RESULT_KEY_FIELDS = {
    'external_benchmark': ['overall_cr', 'total_employees_with_cr', 'benchmark_results'],
    'external_competitiveness': ['overall_cr', 'total_employees_with_cr', 'benchmark_results'],
    'internal_equity': ['high_dispersion_count', 'dispersion'],
    'pay_mix_check': ['overall_fix_pct', 'pay_mix_by_grade'],
    'fix_variable_ratio': ['overall_fix_pct', 'pay_mix_by_grade'],
    'performance_link': ['perf_stats', 'a_vs_b_gap_pct'],
    'pay_performance': ['perf_stats', 'a_vs_b_gap_pct'],
    'cost_trend': ['kpi', 'trend'],
    'labor_cost': ['kpi', 'trend'],
    'salary_simulation': ['plan_a', 'plan_b', 'headcount_affected'],
    'offer_check': ['market', 'recommendation'],
    'grade_lookup': ['lookup'],
}


def _result_is_empty(skill_key: str, result: dict) -> bool:
    """关键字段全为 None / 空 list / 空 dict / 0 时视为空结果"""
    if not isinstance(result, dict):
        return True
    keys = _RESULT_KEY_FIELDS.get(skill_key, [])
    if not keys:
        return False
    for k in keys:
        v = result.get(k)
        if v is None:
            continue
        if isinstance(v, (list, dict)) and len(v) == 0:
            continue
        if isinstance(v, (int, float)) and v == 0:
            continue
        return False  # 至少一个字段有值
    return True


def _generate_narrative(skill: dict, result: dict, session: dict | None) -> str:
    """让 AI 根据 skill 结果生成解读文案"""
    # ⚠️ 安全闸：engine 返回空数据时绝不调 AI，避免凭空编造分析结论
    if _result_is_empty(skill['key'], result):
        print(f'[Skill] {skill["key"]} engine 返回空数据，跳过 AI 叙事')
        return '数据不足，无法分析。请先上传包含员工明细的薪酬数据 Excel。'
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

        # 跟 module-insight 走同一套约定：访谈为空时传明确字符串 '无访谈'，
        # 避免传 None / '{}' 让 LLM 误以为有访谈数据进而编造（之前的幻觉 bug）
        interview = session.get('interview_notes') if session else None
        interview_payload = str(interview)[:800] if interview else '无访谈'
        user_content = json.dumps({
            'skill': skill['key'],
            'result': result,
            'interview': interview_payload,
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
