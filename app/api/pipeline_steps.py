"""
按需调用的 LLM pipeline 步骤，每个接口独立调用，避免上传时一次性超时。
- POST /api/pipeline/<session_id>/cleansing      AI 清洗判断
- POST /api/pipeline/<session_id>/grade-match     职级匹配
- POST /api/pipeline/<session_id>/func-match      职能匹配
- POST /api/pipeline/<session_id>/parse-summary   解析总结（AI 生成一句话）
"""
from flask import Blueprint, jsonify, request

pipeline_bp = Blueprint('pipeline', __name__)


@pipeline_bp.route('/<session_id>/cleansing', methods=['POST'])
def run_cleansing(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # 如果已经跑过，直接返回缓存
    if session.get('_ai_cleansing_done'):
        return jsonify({
            'cleansing_corrections': session.get('_merged_corrections', session.get('_base_corrections', [])),
        })

    code_results = session.get('_code_results')
    base_corrections = list(session.get('_base_corrections', []))

    if not code_results:
        return jsonify({'cleansing_corrections': base_corrections})

    import os
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        session['_ai_cleansing_done'] = True
        session['_merged_corrections'] = base_corrections
        return jsonify({'cleansing_corrections': base_corrections})

    try:
        # Step 1: CleansingAgent 做专业判断（年化/异常值/绩效映射等）
        from app.agents.cleansing_agent import CleansingAgent
        agent = CleansingAgent()
        ai_judgments = agent.run(code_results)

        # Step 2: 让 AI 直接输出用户看到的修正项文案
        from app.agents.base_agent import BaseAgent
        writer = BaseAgent(temperature=0.3)
        import json
        prompt_data = {
            'code_detections': {
                k: v for k, v in code_results.items()
                if k not in ('sample_rows',) and v  # 过滤空值和大数据
            },
            'ai_judgments': ai_judgments if not ai_judgments.get('error') else None,
        }
        messages = [
            {"role": "system", "content": (
                "你是薪酬诊断系统的数据清洗模块。根据下面的代码检测结果和 AI 判断结果，"
                "生成面向用户的修正项列表。每一项用一句简洁的中文描述发生了什么以及做了什么处理。\n\n"
                "输出 JSON 数组，每项格式：\n"
                '[{"id": 1, "description": "一句话描述", "type": "类型标签"}]\n\n'
                "规则：\n"
                "- description 必须具体：提到涉及的行号、数值、字段名\n"
                "- 合并同类项：同一类问题合成一条，不要逐行列出\n"
                "- 如果 AI 判断推翻了代码检测（如判断不是异常值），则不要输出该项\n"
                "- 如果没有任何需要修正的问题，返回空数组 []\n"
                "- type 可选：annualize_bonus, extreme_value, 13th_month_reclassify, "
                "salary_inversion, performance_mapping, department_merge, lti_suspect, "
                "allowance_high, date_anomaly\n"
                "- 只输出 JSON，不要其他文字"
            )},
            {"role": "user", "content": json.dumps(prompt_data, ensure_ascii=False, indent=2)},
        ]
        response = writer.call_llm(messages)

        # 解析 JSON
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        corrections = json.loads(response.strip())
        if not isinstance(corrections, list):
            corrections = base_corrections
    except Exception as e:
        print(f'[Pipeline] AI cleansing failed: {e}')
        import traceback
        traceback.print_exc()
        corrections = base_corrections

    session['_merged_corrections'] = corrections
    session['_ai_cleansing_done'] = True
    if session.get('parse_result'):
        session['parse_result']['cleansing_corrections'] = corrections

    return jsonify({'cleansing_corrections': corrections})


@pipeline_bp.route('/<session_id>/grade-match', methods=['POST'])
def run_grade_match(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # 缓存
    if session.get('_grade_match_done'):
        return jsonify({'grade_matching': session.get('grade_matching', [])})

    from app.services.pipeline import _run_grade_matching, _fallback_grade_matching
    grades_list = session.get('_grades_list', [])
    employees = session.get('_employees', [])
    field_map = session.get('_field_map', {})
    code_results = session.get('_code_results')

    import os
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        grade_matching = _fallback_grade_matching(grades_list)
    else:
        grade_matching = _run_grade_matching(grades_list, employees, [], field_map, code_results)

    session['grade_matching'] = grade_matching
    session['_grade_match_done'] = True
    if session.get('parse_result'):
        session['parse_result']['grade_matching'] = grade_matching

    return jsonify({'grade_matching': grade_matching})


@pipeline_bp.route('/<session_id>/func-match', methods=['POST'])
def run_func_match(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # 缓存
    if session.get('_func_match_done'):
        return jsonify({'function_matching': session.get('function_matching', [])})

    from app.services.pipeline import _run_function_matching, _fallback_function_matching_from_employees
    employees = session.get('_employees', [])

    import os
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        function_matching = _fallback_function_matching_from_employees(employees)
    else:
        function_matching = _run_function_matching(employees)

    session['function_matching'] = function_matching
    session['_func_match_done'] = True
    if session.get('parse_result'):
        session['parse_result']['function_matching'] = function_matching

    return jsonify({'function_matching': function_matching})


@pipeline_bp.route('/<session_id>/completeness-summary', methods=['POST'])
def completeness_summary(session_id):
    """让 Sparky 基于完整度检查结果生成一句话总结"""
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    data = request.json or {}
    summary_data = data.get('summary', '')

    import os
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        return jsonify({'message': ''})

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.5)
        messages = [
            {"role": "system", "content": (
                "你是 Sparky，铭曦产品的 AI 薪酬诊断助手。"
                "系统刚完成了数据完整度检查。请根据下面的检查结果，"
                "用 2-3 句自然口语告诉用户情况，提醒他看看右边的详情，"
                "让他决定是补完数据重新上传还是先跳过继续。"
                "如果没有任何缺失问题，就夸一下数据质量好，让他直接往下走。"
                "语气轻松专业，不要用 markdown 格式。"
            )},
            {"role": "user", "content": summary_data},
        ]
        reply = agent.call_llm(messages)
        return jsonify({'message': reply.strip()})
    except Exception as e:
        print(f'[Pipeline] completeness-summary failed: {e}')
        return jsonify({'message': ''})


@pipeline_bp.route('/<session_id>/parse-summary', methods=['POST'])
def parse_summary(session_id):
    """让 Sparky 基于解析结果生成一句话总结"""
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    data = request.json or {}
    # 前端传入解析摘要
    summary_data = data.get('summary', '')

    import os
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        return jsonify({'message': ''})

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.5)
        messages = [
            {"role": "system", "content": (
                "你是 Sparky，铭曦产品的 AI 薪酬诊断助手。"
                "用户刚上传了薪酬数据 Excel，系统已完成解析。"
                "请根据下面的解析摘要，用一句自然的口语（2-3 句话）告诉用户数据读取情况，"
                "提醒他看看右边的字段和数量对不对，没问题就往下走。"
                "语气轻松专业，不要用 markdown 格式。"
            )},
            {"role": "user", "content": summary_data},
        ]
        reply = agent.call_llm(messages)
        return jsonify({'message': reply.strip()})
    except Exception as e:
        print(f'[Pipeline] parse-summary failed: {e}')
        return jsonify({'message': ''})
