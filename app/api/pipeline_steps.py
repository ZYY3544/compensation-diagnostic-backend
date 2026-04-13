"""
按需调用的 LLM pipeline 步骤，每个接口独立调用，避免上传时一次性超时。
"""
import os
import json
import traceback
from datetime import date, datetime
from flask import Blueprint, jsonify, request, send_file


class _SafeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)

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

    # 确保 snapshot 已创建（防御性）
    if not session.get('_snapshot_done'):
        import copy
        session['_employees_original'] = copy.deepcopy(session.get('_employees', []))
        session['_snapshot_done'] = True

    code_results = session.get('_code_results')
    employees = session.get('_employees', [])
    field_map = session.get('_field_map', {})
    column_names = session.get('_column_names', [])

    if not code_results:
        session['_ai_cleansing_done'] = True
        session['_mutations'] = []
        return jsonify({'cleansing_corrections': [], 'sparky_message': '数据质量很好，不需要修正。', 'has_export': False})

    try:
        # Step 1: 代码算 mutation（确定性，不调 AI）
        from app.services.mutation_builder import build_mutations_from_code
        mutations, summary_text = build_mutations_from_code(code_results, employees, field_map)

        print(f'[Cleansing] code built {len(mutations)} mutations')
        for m in mutations:
            print(f'  - id={m["id"]} type={m["type"]} row={m["row_number"]} conf={m["confidence"]} new={m.get("new_value")}')

        if not mutations:
            session['_mutations'] = []
            session['_ai_cleansing_done'] = True
            return jsonify({'cleansing_corrections': [], 'sparky_message': '数据质量很好，不需要修正。', 'has_export': False})

        # Step 2: AI 只生成 sparky_message（左侧对话总结），右侧文案已由代码模板生成
        sparky_message = summary_text
        if _has_api_key():
            try:
                from app.agents.base_agent import BaseAgent
                writer = BaseAgent(temperature=0.5)
                messages = [
                    {"role": "system", "content": (
                        "你是 Sparky，铭曦产品的 AI 薪酬诊断助手。"
                        "系统刚完成了数据清洗。请根据下面的清洗摘要，"
                        "用 2-3 句自然口语告诉用户做了什么处理、有哪些需要确认的。"
                        "语气轻松专业，不要用 markdown 格式。"
                    )},
                    {"role": "user", "content": summary_text},
                ]
                sparky_message = writer.call_llm(messages).strip() or summary_text
            except Exception as e:
                print(f'[Cleansing] AI sparky_message failed: {e}')

        # Step 3: 校验 + 执行高置信度修改
        from app.services.mutation_engine import validate_mutations, apply_mutations
        mutations = validate_mutations(mutations, employees, field_map)
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
        print(f'[Pipeline] cleansing failed: {e}')
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
            'description': m.get('description', '') or m.get('context', ''),
            'type': m.get('type', ''),
            'context': m.get('context', ''),
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

    # 缓存
    if session.get('_grade_match_done'):
        return jsonify(session.get('_grade_match_result', {}))

    from app.services.grade_matcher import (
        STANDARD_GRADES, STANDARD_GRADE_DEFINITIONS,
        build_grade_match_data, ai_match_grades, ai_suggest_adjustments,
    )
    grades_list = session.get('_grades_list', [])
    employees = session.get('_employees', [])

    # Step 1: 代码统计 + 信号检测
    data = build_grade_match_data(employees, grades_list)

    # Step 2: AI #1 — 职级映射（输入小）
    grade_mapping = {}
    if _has_api_key() and grades_list:
        try:
            grade_mapping = ai_match_grades(grades_list)
        except Exception as e:
            print(f'[GradeMatch] AI mapping failed: {e}')

    # 没映射到的用默认值
    for g in grades_list:
        if g not in grade_mapping:
            grade_mapping[g] = '中级专业人员'

    # Step 3: AI #2 — 调整建议（只传有信号的人）
    suggestions = []
    if _has_api_key() and data['employees_with_signals']:
        try:
            suggestions = ai_suggest_adjustments(data['employees_with_signals'], grade_mapping)
        except Exception as e:
            print(f'[GradeMatch] AI suggestions failed: {e}')

    # 构建建议索引
    suggestion_map = {s['id']: s for s in suggestions}

    # 组装返回结果
    grade_table = []
    for gs in data['grade_stats']:
        g = gs['company_grade']
        grade_table.append({
            'company_grade': g,
            'count': gs['count'],
            'standard_grade': grade_mapping.get(g, ''),
            'status': 'matched',
        })

    employees_by_grade = {}
    for g, emps in data['all_employees_by_grade'].items():
        std_grade = grade_mapping.get(g, '')
        emp_list = []
        for e in emps:
            sug = suggestion_map.get(e['id'])
            signals = [s for ews in data['employees_with_signals'] if ews['id'] == e['id'] for s in ews['signals']]
            emp_list.append({
                'row_number': e['row_number'],
                'id': e['id'],
                'job_title': e['job_title'],
                'performance': e['performance'],
                'mapped_grade': std_grade,
                'suggested_grade': sug['suggested_grade'] if sug else None,
                'adjust_reason': sug['reason'] if sug else None,
                'signals': [s['reason'] for s in signals],
                'has_suggestion': bool(sug or signals),
            })
        # 有建议的排前面
        emp_list.sort(key=lambda x: (0 if x['has_suggestion'] else 1))
        suggestion_count = sum(1 for e in emp_list if e['has_suggestion'])
        employees_by_grade[g] = {
            'employees': emp_list,
            'suggestion_count': suggestion_count,
            'total': len(emp_list),
        }

    # Sparky 消息
    total_suggestions = sum(v['suggestion_count'] for v in employees_by_grade.values())
    sparky_message = f"职级映射已完成，{len(grades_list)} 个职级都对应上了标准体系。"
    if total_suggestions > 0:
        sparky_message += f"另外有 {total_suggestions} 名员工根据绩效和岗位情况，建议调整对标级别，请一起确认。"

    if _has_api_key():
        try:
            from app.agents.base_agent import BaseAgent
            agent = BaseAgent(temperature=0.5)
            messages = [
                {"role": "system", "content": (
                    "你是 Sparky，铭曦产品的 AI 薪酬诊断助手。"
                    "系统刚完成了职级匹配。请根据下面的摘要用 2-3 句自然口语告诉用户情况。"
                    "语气轻松专业，不要用 markdown。"
                )},
                {"role": "user", "content": sparky_message},
            ]
            sparky_message = agent.call_llm(messages).strip() or sparky_message
        except:
            pass

    result = {
        'grade_table': grade_table,
        'employees_by_grade': employees_by_grade,
        'standard_grades': STANDARD_GRADES,
        'standard_grade_definitions': STANDARD_GRADE_DEFINITIONS,
        'sparky_message': sparky_message,
    }

    session['_grade_match_result'] = result
    session['_grade_match_done'] = True
    # 向后兼容旧格式
    session['grade_matching'] = [
        {'client_grade': g['company_grade'], 'standard_grade': g['standard_grade'],
         'confidence': 'high', 'confirmed': True}
        for g in grade_table
    ]
    if session.get('parse_result'):
        session['parse_result']['grade_matching'] = session['grade_matching']

    return jsonify(result)


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
