"""
按需调用的 LLM pipeline 步骤，每个接口独立调用，避免上传时一次性超时。
"""
import os
import json
import traceback
from datetime import date, datetime
from flask import Blueprint, jsonify, request, send_file
from app.core.auth import require_auth


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
@require_auth
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
@require_auth
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

        # Step 4: 生成标注 Excel —— 完全从 parse_result 重建，不读用户原 xlsx
        # 避开 openpyxl 在用户文件里碰到 vml drawing 时崩溃的路径
        cleansed_path = None
        parse_result = session.get('parse_result')
        upload_path = session.get('upload_file_path')
        if parse_result and upload_path:
            cleansed_path = upload_path.rsplit('.', 1)[0] + '_cleansed.xlsx'
            from app.services.excel_mutator import create_marked_excel
            try:
                create_marked_excel(parse_result, mutations, cleansed_path, field_map)
            except Exception as e:
                print(f'[Pipeline] marked Excel generation failed: {e}')
                cleansed_path = None

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
@require_auth
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

    # 同步 Excel —— 整份重建（mutations 已携带最新的 reverted 状态）
    # 比"找到对应单元格增量改"更稳，且不依赖之前的 marked Excel 还在磁盘上
    parse_result = session.get('parse_result')
    excel_path = session.get('_cleansed_excel_path')
    if excel_path and parse_result:
        from app.services.excel_mutator import create_marked_excel
        try:
            create_marked_excel(parse_result, mutations, excel_path, field_map)
        except Exception as e:
            print(f'[Pipeline] revert Excel update failed: {e}')

    session['cleaned_employees'] = employees

    return jsonify({
        'mutation_id': mutation_id,
        'reverted': target['reverted'],
    })


# ======================================================================
# Export
# ======================================================================

@pipeline_bp.route('/<session_id>/cleansing/export', methods=['GET'])
@require_auth
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
@require_auth
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
        STANDARD_SUB_LEVELS, HAY_GRADE_MAP,
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

    # 没映射到的用智能 fallback：从公司职级名里提取数字
    import re as _re
    for g in grades_list:
        if g not in grade_mapping:
            m = _re.search(r'(\d+)', str(g))
            if m:
                n = int(m.group(1))
                if 1 <= n <= 7:
                    grade_mapping[g] = f'Level {n}'
                    continue
            grade_mapping[g] = 'Level 3'

    # 回写到 employees：hay_grade（基于 Level → 子级 → Hay 映射）
    # Level N → Level N-1 的 Hay 作为基准
    level_hay_base = {}
    for sub_key, hay_val in HAY_GRADE_MAP.items():
        level_num = sub_key.split('-')[0]  # "Level 3"
        if level_num not in level_hay_base or sub_key.endswith('-1'):
            level_hay_base[level_num] = hay_val
    for emp in employees:
        company_g = emp.get('grade', '')
        standard_lv = grade_mapping.get(company_g)
        if standard_lv and standard_lv in level_hay_base:
            emp['hay_grade'] = level_hay_base[standard_lv]
            emp['standard_level'] = standard_lv

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
        'standard_sub_levels': STANDARD_SUB_LEVELS,
        'hay_grade_map': HAY_GRADE_MAP,
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
@require_auth
def run_func_match(session_id):
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    if session.get('_func_match_done'):
        return jsonify(session.get('_func_match_result', {}))

    from app.services.func_matcher import (
        STANDARD_FAMILIES, FAMILY_LIST, FAMILY_DEFINITIONS,
        SUBFUNCTION_DEFINITIONS, build_func_match_data,
        ai_match_families, ai_match_subfunctions,
    )
    employees = session.get('_employees', [])
    field_map = session.get('_field_map', {})

    # Step 1: 代码判断数据源 + 分组统计
    data = build_func_match_data(employees, field_map)
    source_names = [s['source_name'] for s in data['source_stats']]

    # Step 2: AI #1 — 来源分类 → 标准职位族
    family_mapping = {}
    if _has_api_key() and source_names:
        try:
            family_mapping = ai_match_families(source_names)
        except Exception as e:
            print(f'[FuncMatch] AI family mapping failed: {e}')
    for name in source_names:
        if name not in family_mapping:
            family_mapping[name] = '其他'

    # 回写到 employees：job_function（映射后的标准职能族）
    # 数据源取决于 build_func_match_data 判断的优先级：
    #   优先 job_family 列，其次 department 一级，最后 job_title
    source_field = 'job_family'
    if not any(e.get('job_family') for e in employees):
        source_field = 'department'
    for emp in employees:
        key = str(emp.get(source_field, '') or '').strip()
        if not key:
            key = '未分类'
        standard_family = family_mapping.get(key)
        if standard_family:
            emp['job_function'] = standard_family
            emp['standard_family'] = standard_family

    # Step 3: AI #2 — 每个职位族内的职位类映射 + 岗位异常
    sub_mappings = {}
    all_mismatches = []
    for source_name, family in family_mapping.items():
        sub_group = data['sub_groups'].get(source_name, {})
        sub_names = list(sub_group.keys())
        # 收集该族下的岗位名称（去重，最多20个）
        titles = list(set(
            emp.get('job_title', '') for emps in sub_group.values() for emp in emps
            if emp.get('job_title')
        ))[:20]

        if _has_api_key() and (sub_names or titles):
            try:
                result = ai_match_subfunctions(family, sub_names, titles)
                sub_mappings[source_name] = result.get('sub_mapping', {})
                for mm in result.get('mismatches', []):
                    mm['source_family'] = source_name
                    all_mismatches.append(mm)
            except Exception as e:
                print(f'[FuncMatch] AI sub-match failed for {source_name}: {e}')
                sub_mappings[source_name] = {}
        else:
            sub_mappings[source_name] = {}

    # 组装返回结构
    family_table = []
    for s in data['source_stats']:
        family_table.append({
            'source_name': s['source_name'],
            'count': s['count'],
            'standard_family': family_mapping.get(s['source_name'], '其他'),
            'status': 'matched',
        })

    sub_details = {}
    for source_name in [s['source_name'] for s in data['source_stats']]:
        sub_group = data['sub_groups'].get(source_name, {})
        sm = sub_mappings.get(source_name, {})
        family = family_mapping.get(source_name, '其他')
        available_subs = STANDARD_FAMILIES.get(family, ['未分类'])

        sub_rows = []
        for sub_name, emps in sub_group.items():
            emp_list = []
            for emp in emps:
                is_mismatch = any(
                    mm.get('title') == emp.get('job_title') and mm.get('source_family') == source_name
                    for mm in all_mismatches
                )
                mismatch_info = next(
                    (mm for mm in all_mismatches
                     if mm.get('title') == emp.get('job_title') and mm.get('source_family') == source_name),
                    None
                )
                emp_list.append({
                    'row_number': emp.get('row_number'),
                    'id': emp.get('id', ''),
                    'job_title': emp.get('job_title', ''),
                    'current_subfunction': sm.get(sub_name, available_subs[0] if available_subs else '未分类'),
                    'is_mismatch': is_mismatch,
                    'suggested_family': mismatch_info.get('suggested_family') if mismatch_info else None,
                    'mismatch_reason': mismatch_info.get('reason') if mismatch_info else None,
                })

            mismatch_count = sum(1 for e in emp_list if e['is_mismatch'])
            sub_rows.append({
                'sub_source_name': sub_name,
                'count': len(emp_list),
                'standard_subfunction': sm.get(sub_name, available_subs[0] if available_subs else '未分类'),
                'available_subfunctions': available_subs,
                'mismatch_count': mismatch_count,
                'employees': emp_list,
            })

        total_mismatches = sum(r['mismatch_count'] for r in sub_rows)
        sub_details[source_name] = {
            'family': family,
            'sub_rows': sub_rows,
            'total': sum(r['count'] for r in sub_rows),
            'mismatch_count': total_mismatches,
        }

    # Sparky 消息
    total_families = len(family_table)
    total_mismatches = len(all_mismatches)
    sparky_message = f"职能匹配完成，{total_families} 个分类已映射到标准职位族。"
    if total_mismatches > 0:
        sparky_message += f"有 {total_mismatches} 个岗位的归属不太确定，需要你确认一下。"

    if _has_api_key():
        try:
            from app.agents.base_agent import BaseAgent
            agent = BaseAgent(temperature=0.5)
            messages = [
                {"role": "system", "content": (
                    "你是 Sparky，铭曦产品的 AI 薪酬诊断助手。"
                    "系统刚完成了职能匹配。用 2-3 句自然口语告诉用户为什么要做这一步、匹配情况如何。"
                    "语气轻松专业，不要用 markdown。"
                )},
                {"role": "user", "content": sparky_message},
            ]
            sparky_message = agent.call_llm(messages).strip() or sparky_message
        except:
            pass

    result = {
        'family_table': family_table,
        'sub_details': sub_details,
        'standard_families': STANDARD_FAMILIES,
        'family_definitions': FAMILY_DEFINITIONS,
        'subfunction_definitions': SUBFUNCTION_DEFINITIONS,
        'data_source': data['data_source'],
        'sparky_message': sparky_message,
    }

    session['_func_match_result'] = result
    session['_func_match_done'] = True
    return jsonify(result)


# ======================================================================
# Summary endpoints (AI 生成一句话)
# ======================================================================

@pipeline_bp.route('/<session_id>/completeness-summary', methods=['POST'])
@require_auth
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
@require_auth
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
