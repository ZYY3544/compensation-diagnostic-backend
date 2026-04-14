"""
统一能力入口：
POST /api/skill/classify-intent  — 识别意图
POST /api/skill/invoke            — 调用能力
GET  /api/skill/registry          — 获取能力列表（前端欢迎页 chip 用）
"""
import os
import json
import traceback
from flask import Blueprint, jsonify, request
from app.services.skill_registry import SKILLS, get_skill, get_engine_fn, check_preconditions, list_skills
from app.services.intent_router import classify_intent
from app.models import new_id, now_iso

skill_bp = Blueprint('skill', __name__)


@skill_bp.route('/registry', methods=['GET'])
def get_registry():
    """返回所有能力列表，供前端欢迎页展示 chip"""
    mode = request.args.get('mode')
    skills = list_skills(mode)
    # 只返回前端需要的字段
    return jsonify({
        'skills': [
            {
                'key': s['key'],
                'display_name': s['display_name'],
                'mode': s['mode'],
                'chip_label': s.get('chip_label'),
                'chip_icon': s.get('chip_icon'),
                'estimated_duration': s.get('estimated_duration'),
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
    请求：{ 'skill_key': 'external_benchmark', 'session_id': '...', 'params': {...} }
    返回：{ 'result': {...}, 'narrative': '...', 'skill': {...} }
    """
    data = request.json or {}
    skill_key = data.get('skill_key', '')
    session_id = data.get('session_id', '')
    params = data.get('params', {}) or {}

    skill = get_skill(skill_key)
    if not skill:
        return jsonify({'error': f'Unknown skill: {skill_key}'}), 404

    # 获取员工数据（从 session）
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id) if session_id else None
    employees = session.get('cleaned_employees') or session.get('_employees', []) if session else []

    # 检查前置条件
    context = {
        'snapshot_id': session.get('snapshot_id') if session else None,
        'has_data': bool(employees),
    }
    ok, reason = check_preconditions(skill_key, context)
    if not ok:
        return jsonify({'error': reason, 'needs_action': 'upload_data'}), 400

    # 触发全量分析（带缓存，首次算完存起来）
    if session and employees:
        try:
            from app.services.full_analysis import get_or_compute
            get_or_compute(session)  # 预热缓存，skill 函数内部如果需要可以读 session['_full_analysis']
        except Exception as e:
            print(f'[Skill] full_analysis precompute failed: {e}')

    # 调用 engine
    engine_fn = get_engine_fn(skill_key)
    if not engine_fn:
        return jsonify({'error': f'Engine not implemented: {skill_key}'}), 501

    try:
        result = engine_fn(employees, params)
    except Exception as e:
        print(f'[Skill] {skill_key} failed: {e}')
        traceback.print_exc()
        return jsonify({'error': f'Skill execution failed: {str(e)}'}), 500

    # 生成 narrative（AI 解读）
    narrative = _generate_narrative(skill, result, session)

    # 记录调用（简化：写到 session）
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


def _generate_narrative(skill: dict, result: dict, session: dict) -> str:
    """让 AI 根据 skill 结果生成解读文案"""
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        return _fallback_narrative(skill, result)

    prompt_file = skill.get('narrative_prompt')
    if not prompt_file:
        return _fallback_narrative(skill, result)

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.5)
        # 尝试加载 prompt，不存在用通用 prompt
        try:
            system_prompt = agent.load_prompt(prompt_file)
        except:
            system_prompt = (
                "你是 Sparky，铭曦产品的 AI 薪酬顾问。"
                f"用户刚使用了「{skill['display_name']}」能力，系统算出了结果。"
                "请用 2-4 句自然口语解读这个结果，给用户判断，不要只是复述数字。"
                "如果结果里有异常或问题，要明确指出。如果用户访谈背景里有相关信息，要关联起来。"
                "只输出文本，不要 markdown。"
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
    """AI 不可用时的兜底文案"""
    if result.get('error'):
        return f"执行「{skill['display_name']}」时遇到问题：{result['error']}"

    name = skill['display_name']
    if skill['key'] == 'external_benchmark':
        rows = result.get('rows', [])
        if rows:
            worst = rows[0]
            return f"{name}完成。{len(rows)} 个分组中，{worst['name']} 处于市场 P{worst.get('avg_percentile', '—')}，差距最大。详情看右边。"
    elif skill['key'] == 'salary_simulation':
        return f"调薪模拟完成。影响 {result.get('headcount', 0)} 人，年度预算约 ¥{result.get('total_annual_delta', 0) // 10000} 万。分层方案相比全员调 P50 可节省 {result.get('savings_pct', 0)}%。"
    elif skill['key'] == 'offer_check':
        return f"候选人定薪建议完成。建议范围见右边。"
    elif skill['key'] == 'grade_lookup':
        return f"市场薪酬查询完成。详情看右边。"
    return f"{name}完成。"
