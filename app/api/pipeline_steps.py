"""
按需调用的 LLM pipeline 步骤，每个接口独立调用，避免上传时一次性超时。
"""
import os
import json
import traceback
from flask import Blueprint, jsonify, request, send_file

pipeline_bp = Blueprint('pipeline', __name__)


def _has_api_key() -> bool:
    return bool(os.getenv('OPENROUTER_API_KEY', '').strip())


# ======================================================================
# Snapshot
# ======================================================================

@pipeline_bp.route('/<session_id>/snapshot', methods=['POST'])
def create_snapshot(session_id):
    """复制一份原始数据，后续清洗都在副本上操作"""
    from app.api.sessions import sessions_store
    import copy
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    if session.get('_snapshot_done'):
        return jsonify({'status': 'ok'})
    session['_employees_original'] = copy.deepcopy(session.get('_employees', []))
    session['_snapshot_done'] = True
    return jsonify({'status': 'ok'})


# ======================================================================
# Cleansing — 结构化修改指令
# ======================================================================

@pipeline_bp.route('/<session_id>/cleansing', methods=['POST'])
def run_cleansing(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # 缓存
    if session.get('_ai_cleansing_done'):
        corrections = _mutations_to_corrections(session.get('_mutations', []))
        return jsonify({
            'cleansing_corrections': corrections,
            'sparky_message': session.get('_cleansing_sparky', ''),
            'has_export': bool(session.get('_cleansed_excel_path')),
        })

    code_results = session.get('_code_results')
    employees = session.get('_employees', [])
    field_map = session.get('_field_map', {})
    column_names = session.get('_column_names', [])

    if not code_results or not _has_api_key():
        session['_ai_cleansing_done'] = True
        session['_mutations'] = []
        return jsonify({'cleansing_corrections': [], 'sparky_message': '', 'has_export': False})

    try:
        # Step 1: CleansingAgent 做专业判断
        from app.agents.cleansing_agent import CleansingAgent
        agent = CleansingAgent()
        ai_judgments = agent.run(code_results)

        # Step 2: 生成结构化修改指令
        from app.agents.base_agent import BaseAgent
        writer = BaseAgent(temperature=0.3)
        system_prompt = writer.load_prompt('cleansing_mutations.txt')

        # 准备数据：代码检测 + AI 判断 + 涉及行的实际数据
        flagged_rows = set()
        for key in ('needs_annualize', 'salary_outliers', 'bonus_outliers',
                     'possible_13th_overlap', 'salary_inversions',
                     'allowance_alerts', 'future_dates', 'old_dates'):
            for item in (code_results.get(key) or []):
                rn = item.get('row_number') or item.get('row')
                if rn:
                    flagged_rows.add(rn)

        employee_context = []
        for emp in employees:
            if emp.get('row_number') in flagged_rows:
                employee_context.append({
                    k: v for k, v in emp.items()
                    if k in ('row_number', 'id', 'job_title', 'grade', 'department',
                             'base_annual', 'fixed_bonus', 'variable_bonus',
                             'performance', 'hire_date')
                })

        prompt_data = {
            'code_detections': {
                k: v for k, v in code_results.items()
                if k not in ('sample_rows',) and v
            },
            'ai_judgments': ai_judgments if not ai_judgments.get('error') else None,
            'flagged_employees': employee_context,
            'field_map': field_map,
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(prompt_data, ensure_ascii=False, indent=2)},
        ]
        response = writer.call_llm(messages)

        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]

        parsed = json.loads(response.strip())
        mutations = parsed.get('mutations', [])
        sparky_message = parsed.get('sparky_message', '')

        # 给每条 mutation 补 id 和默认字段
        for i, m in enumerate(mutations):
            m.setdefault('id', i + 1)
            m.setdefault('reverted', False)
            m.setdefault('auto_applied', m.get('confidence') != 'low' and m.get('new_value') is not None)

        # 日志：看 AI 返回了什么
        print(f'[Cleansing] AI returned {len(mutations)} mutations')
        for m in mutations:
            print(f'  - row={m.get("row_number")} field={m.get("field")} old={m.get("old_value")} new={m.get("new_value")} conf={m.get("confidence")}')

        # Step 3: 校验 + 执行
        from app.services.mutation_engine import validate_mutations, apply_mutations
        mutations = validate_mutations(mutations, employees, field_map)
        print(f'[Cleansing] after validation: {len(mutations)} mutations')
        auto = [m for m in mutations if m.get('auto_applied')]
        apply_mutations(employees, auto, field_map)

        # Step 4: 生成标注 Excel
        cleansed_path = None
        upload_path = session.get('upload_file_path')
        if upload_path and os.path.exists(upload_path):
            cleansed_path = upload_path.rsplit('.', 1)[0] + '_cleansed.xlsx'
            from app.services.excel_mutator import create_marked_excel
            create_marked_excel(upload_path, cleansed_path, mutations, field_map, column_names)

        # 存储
        session['_mutations'] = mutations
        session['_cleansing_sparky'] = sparky_message
        session['_cleansed_excel_path'] = cleansed_path
        session['_ai_cleansing_done'] = True
        session['cleaned_employees'] = employees

    except Exception as e:
        print(f'[Pipeline] AI cleansing failed: {e}')
        traceback.print_exc()
        mutations = []
        sparky_message = ''
        session['_mutations'] = []
        session['_ai_cleansing_done'] = True

    corrections = _mutations_to_corrections(mutations)
    if session.get('parse_result'):
        session['parse_result']['cleansing_corrections'] = corrections

    return jsonify({
        'cleansing_corrections': corrections,
        'sparky_message': sparky_message,
        'has_export': bool(session.get('_cleansed_excel_path')),
    })


def _mutations_to_corrections(mutations: list) -> list:
    """把 mutations 转成前端期望的 corrections 格式"""
    return [
        {
            'id': m['id'],
            'description': m.get('description', ''),
            'type': m.get('type', ''),
            'row_number': m.get('row_number'),
            'field': m.get('field'),
            'old_value': m.get('old_value'),
            'new_value': m.get('new_value'),
            'confidence': m.get('confidence', 'high'),
            'auto_applied': m.get('auto_applied', False),
            'reverted': m.get('reverted', False),
        }
        for m in mutations
    ]


# ======================================================================
# Revert / Re-apply
# ======================================================================

@pipeline_bp.route('/<session_id>/cleansing/revert', methods=['POST'])
def revert_cleansing(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    data = request.json or {}
    mutation_id = data.get('mutation_id')
    mutations = session.get('_mutations', [])
    target = next((m for m in mutations if m['id'] == mutation_id), None)
    if not target:
        return jsonify({'error': 'Mutation not found'}), 404

    employees = session.get('_employees', [])
    employees_original = session.get('_employees_original', [])
    field_map = session.get('_field_map', {})
    column_names = session.get('_column_names', [])

    from app.services.mutation_engine import revert_mutation, reapply_mutation
    if not target['reverted']:
        revert_mutation(employees, employees_original, mutations, mutation_id)
    else:
        reapply_mutation(employees, employees_original, mutations, mutation_id)

    # 同步 Excel
    excel_path = session.get('_cleansed_excel_path')
    if excel_path and os.path.exists(excel_path):
        from app.services.excel_mutator import update_cell_in_excel
        update_cell_in_excel(excel_path, target, field_map, column_names, is_revert=target['reverted'])

    session['cleaned_employees'] = employees

    return jsonify({
        'mutation_id': mutation_id,
        'reverted': target['reverted'],
    })


# ======================================================================
# Export
# ======================================================================

@pipeline_bp.route('/<session_id>/cleansing/export', methods=['GET'])
def export_cleansed_excel(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    path = session.get('_cleansed_excel_path')
    if not path or not os.path.exists(path):
        return jsonify({'error': 'No cleansed file available'}), 404

    return send_file(
        path,
        as_attachment=True,
        download_name='薪酬数据_清洗标注.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


# ======================================================================
# Grade matching
# ======================================================================

@pipeline_bp.route('/<session_id>/grade-match', methods=['POST'])
def run_grade_match(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    if session.get('_grade_match_done'):
        return jsonify({'grade_matching': session.get('grade_matching', [])})

    from app.services.pipeline import _run_grade_matching, _fallback_grade_matching
    grades_list = session.get('_grades_list', [])
    employees = session.get('_employees', [])
    field_map = session.get('_field_map', {})
    code_results = session.get('_code_results')

    if not _has_api_key():
        grade_matching = _fallback_grade_matching(grades_list)
    else:
        grade_matching = _run_grade_matching(grades_list, employees, [], field_map, code_results)

    session['grade_matching'] = grade_matching
    session['_grade_match_done'] = True
    if session.get('parse_result'):
        session['parse_result']['grade_matching'] = grade_matching
    return jsonify({'grade_matching': grade_matching})


# ======================================================================
# Function matching
# ======================================================================

@pipeline_bp.route('/<session_id>/func-match', methods=['POST'])
def run_func_match(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    if session.get('_func_match_done'):
        return jsonify({'function_matching': session.get('function_matching', [])})

    from app.services.pipeline import _run_function_matching, _fallback_function_matching_from_employees
    employees = session.get('_employees', [])

    if not _has_api_key():
        function_matching = _fallback_function_matching_from_employees(employees)
    else:
        function_matching = _run_function_matching(employees)

    session['function_matching'] = function_matching
    session['_func_match_done'] = True
    if session.get('parse_result'):
        session['parse_result']['function_matching'] = function_matching
    return jsonify({'function_matching': function_matching})


# ======================================================================
# Summary endpoints (AI 生成一句话)
# ======================================================================

@pipeline_bp.route('/<session_id>/completeness-summary', methods=['POST'])
def completeness_summary(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    data = request.json or {}
    if not _has_api_key():
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
            {"role": "user", "content": data.get('summary', '')},
        ]
        return jsonify({'message': agent.call_llm(messages).strip()})
    except Exception as e:
        print(f'[Pipeline] completeness-summary failed: {e}')
        return jsonify({'message': ''})


@pipeline_bp.route('/<session_id>/parse-summary', methods=['POST'])
def parse_summary(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    data = request.json or {}
    if not _has_api_key():
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
            {"role": "user", "content": data.get('summary', '')},
        ]
        return jsonify({'message': agent.call_llm(messages).strip()})
    except Exception as e:
        print(f'[Pipeline] parse-summary failed: {e}')
        return jsonify({'message': ''})
