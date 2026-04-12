"""
按需调用的 LLM pipeline 步骤，每个接口独立调用，避免上传时一次性超时。
- POST /api/pipeline/<session_id>/cleansing    AI 清洗判断
- POST /api/pipeline/<session_id>/grade-match   职级匹配
- POST /api/pipeline/<session_id>/func-match    职能匹配
"""
from flask import Blueprint, jsonify

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

    try:
        import os
        if not os.getenv('OPENROUTER_API_KEY', '').strip():
            raise RuntimeError('No API key')

        from app.agents.cleansing_agent import CleansingAgent
        from app.services.pipeline import _merge_ai_corrections
        agent = CleansingAgent()
        ai_results = agent.run(code_results)
        if ai_results and not ai_results.get('error'):
            merged = _merge_ai_corrections(base_corrections, ai_results, code_results)
        else:
            merged = base_corrections
    except Exception as e:
        print(f'[Pipeline] AI cleansing failed: {e}')
        merged = base_corrections

    session['_merged_corrections'] = merged
    session['_ai_cleansing_done'] = True

    # 同步更新 parse_result
    if session.get('parse_result'):
        session['parse_result']['cleansing_corrections'] = merged

    return jsonify({'cleansing_corrections': merged})


@pipeline_bp.route('/<session_id>/grade-match', methods=['POST'])
def run_grade_match(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # 缓存
    if session.get('_grade_match_done'):
        return jsonify({'grade_matching': session.get('grade_matching', [])})

    from app.services.pipeline import _run_grade_matching
    grades_list = session.get('_grades_list', [])
    employees = session.get('_employees', [])
    field_map = session.get('_field_map', {})
    code_results = session.get('_code_results')

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

    from app.services.pipeline import _run_function_matching
    employees = session.get('_employees', [])

    function_matching = _run_function_matching(employees)

    session['function_matching'] = function_matching
    session['_func_match_done'] = True
    if session.get('parse_result'):
        session['parse_result']['function_matching'] = function_matching

    return jsonify({'function_matching': function_matching})
