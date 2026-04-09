"""
完整的上传后处理流水线：
Excel 解析 → 代码层检测 → AI 清洗判断 → 职级匹配 → 职能匹配
"""
import os
import traceback
from app.services.excel_parser import parse_excel
from app.services.preprocessor import run_code_checks
from app.agents.cleansing_agent import CleansingAgent
from app.agents.matching_agent import MatchingAgent


def run_full_pipeline(file_path: str, session: dict) -> dict:
    """
    完整的上传后处理流水线：
    1. 解析 Excel
    2. 代码层跑 15 条规则检测
    3. AI 清洗判断（只处理代码搞不定的问题）
    4. 职级匹配（LLM）
    5. 职能匹配（LLM）
    返回合并后的完整结果，格式与前端 ParseResult 对齐
    """
    # ------------------------------------------------------------------
    # Step 1: 解析 Excel
    # ------------------------------------------------------------------
    parsed = parse_excel(file_path)
    rows = parsed.get('sheet1_data', [])
    columns = parsed.get('column_names', [])
    sheet2 = parsed.get('sheet2_data', {})

    # 字段映射（复用 upload.py 的逻辑）
    field_map = _detect_fields(columns)

    # 提取基础统计
    grades = set()
    departments = set()
    employees = []

    for row in rows:
        d = row['data']
        grade = _get_mapped(d, field_map, 'grade')
        dept = _get_mapped(d, field_map, 'department')
        if grade:
            grades.add(str(grade))
        if dept:
            departments.add(str(dept))

        base_annual = _safe_float(_get_mapped(d, field_map, 'base_salary'))
        fixed_bonus = _safe_float(_get_mapped(d, field_map, 'fixed_bonus'))
        variable_bonus = _safe_float(_get_mapped(d, field_map, 'variable_bonus'))
        cash_allowance = _safe_float(_get_mapped(d, field_map, 'cash_allowance'))
        reimbursement = _safe_float(_get_mapped(d, field_map, 'reimbursement'))
        # TCC = 年度基本工资 + 年固定奖金 + 年浮动奖金 + 年现金津贴（不含报销）
        tcc = base_annual + fixed_bonus + variable_bonus + cash_allowance
        # 向后兼容：base_monthly 用于分析引擎的 CR 计算
        base_monthly = base_annual / 12 if base_annual else 0
        emp = {
            'id': _get_mapped(d, field_map, 'employee_id') or f'ROW{row["row_number"]}',
            'job_title': _get_mapped(d, field_map, 'job_title') or '',
            'grade': str(grade) if grade else '',
            'department': str(dept) if dept else '',
            'base_annual': base_annual,
            'base_monthly': base_monthly,
            'fixed_bonus': fixed_bonus,
            'variable_bonus': variable_bonus,
            'cash_allowance': cash_allowance,
            'reimbursement': reimbursement,
            'annual_bonus': fixed_bonus + variable_bonus,  # 向后兼容
            'tcc': tcc,
            'performance': _get_mapped(d, field_map, 'performance') or '',
            'hire_date': str(_get_mapped(d, field_map, 'hire_date') or ''),
            'manager': _get_mapped(d, field_map, 'manager') or '',
        }
        employees.append(emp)

    grades_list = sorted(grades)
    depts_list = sorted(departments)

    # 基础字段检测
    fields_detected = _detect_field_list(field_map)

    # 基础完整性检测（空值）
    row_missing = _detect_row_missing(rows, field_map)

    # 缺失的可选列
    column_missing = _detect_column_missing(field_map)

    # 模块解锁
    has_performance = 'performance' in field_map
    has_company_data = len(sheet2) > 0
    unlocked, locked = _compute_modules(has_performance, has_company_data)

    # 完整性得分
    required_count = len(['job_title', 'grade', 'base_salary', 'fixed_bonus'])
    completeness_score = int((1 - len(row_missing) / max(len(rows) * required_count, 1)) * 100)
    completeness_score = max(0, min(100, completeness_score))

    # Sparky 消息收集器
    sparky_messages = {}

    # ------------------------------------------------------------------
    # Step 2: 代码层 15 条规则检测
    # ------------------------------------------------------------------
    code_results = None
    try:
        code_results = run_code_checks(parsed)
    except Exception as e:
        print(f'[Pipeline] code checks failed: {e}')
        traceback.print_exc()

    # 从代码检测构建 cleansing_corrections
    corrections = _build_corrections_from_code(code_results)

    # ------------------------------------------------------------------
    # Step 3: AI 清洗判断（可选）
    # ------------------------------------------------------------------
    ai_results = None
    if code_results and _has_api_key():
        try:
            agent = CleansingAgent()
            ai_results = agent.run(code_results)
            if ai_results and not ai_results.get('error'):
                # 合并 AI 判断到 corrections
                corrections = _merge_ai_corrections(corrections, ai_results, code_results)
        except Exception as e:
            print(f'[Pipeline] AI cleansing skipped: {e}')

    # ------------------------------------------------------------------
    # Step 4: 职级匹配（LLM）
    # ------------------------------------------------------------------
    grade_matching = _run_grade_matching(grades_list, employees, rows, field_map, code_results)

    # ------------------------------------------------------------------
    # Step 5: 职能匹配（LLM）
    # ------------------------------------------------------------------
    function_matching = _run_function_matching(employees)

    # ------------------------------------------------------------------
    # Step 6: 组装最终结果
    # ------------------------------------------------------------------
    result = {
        'employee_count': len(rows),
        'grade_count': len(grades_list),
        'department_count': len(depts_list),
        'grades': grades_list,
        'departments': depts_list,
        'fields_detected': fields_detected,
        'completeness_issues': {
            'row_missing': row_missing[:20],
            'column_missing': column_missing,
        },
        'cleansing_corrections': corrections,
        'grade_matching': grade_matching,
        'function_matching': function_matching,
        'data_completeness_score': completeness_score,
        'unlocked_modules': unlocked,
        'locked_modules': locked,
        'sparky_messages': _build_sparky_messages(
            row_missing, column_missing, corrections,
            grade_matching, function_matching, unlocked, locked,
        ),
        '_employees': employees,
    }
    return result


# ======================================================================
# 内部辅助函数
# ======================================================================

def _has_api_key() -> bool:
    return bool(os.getenv('OPENROUTER_API_KEY', '').strip())


def _detect_fields(columns: list) -> dict:
    """列名 → 标准字段映射"""
    field_map = {}
    patterns = {
        'employee_id': ['工号', '姓名', '员工'],
        'job_title': ['岗位', '职位', '头衔'],
        'grade': ['职级', '级别', '层级', 'level'],
        'department': ['部门', '一级'],
        'base_salary': ['年度基本工资', '基本工资', '月薪', '固定月薪', '月度基本'],
        'fixed_bonus': ['年固定奖金', '固定奖金', '13薪', '十三薪', '年节礼金'],
        'variable_bonus': ['年浮动奖金', '浮动奖金', '绩效奖金', '年终奖', '奖金', '年终'],
        'cash_allowance': ['年现金津贴', '现金津贴', '津贴'],
        'reimbursement': ['年津贴报销', '津贴报销', '报销'],
        'performance': ['绩效', '考核', '评级'],
        'hire_date': ['入职', '入司', '入职日期'],
        'manager': ['上级', '汇报', '主管'],
        'management_track': ['管理岗', '专业岗', '通道'],
        'key_position': ['关键岗位', '核心岗位'],
        'management_complexity': ['管理复杂度', '复杂度'],
        'city': ['城市', 'base'],
        'age': ['年龄'],
        'education': ['学历', '教育'],
    }
    for col in columns:
        col_lower = col.lower() if col else ''
        for field_key, keywords in patterns.items():
            if field_key not in field_map:
                for kw in keywords:
                    if kw.lower() in col_lower:
                        field_map[field_key] = col
                        break
    return field_map


def _get_mapped(row_data: dict, field_map: dict, field_key: str):
    col_name = field_map.get(field_key)
    if col_name and col_name in row_data:
        return row_data[col_name]
    return None


def _safe_float(val) -> float:
    if val is None:
        return 0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0


def _detect_field_list(field_map: dict) -> list:
    standard_fields = [
        ('employee_id', '姓名/工号'), ('job_title', '岗位'), ('grade', '职级'),
        ('base_salary', '年度基本工资'), ('fixed_bonus', '年固定奖金'),
        ('variable_bonus', '年浮动奖金'), ('cash_allowance', '年现金津贴'),
        ('department', '部门'), ('performance', '绩效'), ('hire_date', '入司时间'),
    ]
    return [{'name': label, 'detected': key in field_map} for key, label in standard_fields]


def _detect_row_missing(rows: list, field_map: dict) -> list:
    missing = []
    required_fields = ['job_title', 'grade', 'base_salary', 'fixed_bonus']
    label_map = {'job_title': '岗位名称', 'grade': '职级', 'base_salary': '年度基本工资', 'fixed_bonus': '年固定奖金'}
    for row in rows:
        d = row['data']
        for req in required_fields:
            val = _get_mapped(d, field_map, req)
            if val is None or str(val).strip() == '':
                label = label_map.get(req, req)
                missing.append({
                    'row': row['row_number'],
                    'field': label,
                    'issue': f'{label}为空',
                })
    return missing


def _detect_column_missing(field_map: dict) -> list:
    missing = []
    optional_checks = [
        ('management_track', '管理岗/专业岗', '管理溢价分析不可用'),
        ('key_position', '是否关键岗位', '关键岗位下钻不可用'),
        ('management_complexity', '管理复杂度', '管理复杂度定价不可用'),
    ]
    for field_key, field_name, impact in optional_checks:
        if field_key not in field_map:
            missing.append({'field': field_name, 'impact': impact})
    return missing


def _compute_modules(has_performance: bool, has_company_data: bool):
    unlocked = ['外部竞争力分析', '内部公平性分析', '薪酬固浮比分析']
    locked = []
    if has_performance:
        unlocked.append('绩效关联分析')
    else:
        locked.append({'name': '绩效关联分析', 'reason': '缺少绩效字段'})
    if has_company_data:
        unlocked.append('人工成本趋势分析')
    else:
        locked.append({'name': '人工成本趋势分析', 'reason': '缺少公司经营数据'})
    return unlocked, locked


def _build_corrections_from_code(code_results: dict | None) -> list:
    """把代码层检测结果转换成前端期望的 cleansing_corrections 格式"""
    if not code_results:
        return []

    corrections = []
    corr_id = 0

    # 年化候选
    annualize = code_results.get('needs_annualize', [])
    if annualize:
        rows_str = '、'.join(str(a['row_number']) for a in annualize[:5])
        corr_id += 1
        corrections.append({
            'id': corr_id,
            'description': f'第 {rows_str} 行浮动奖金已年化处理（入司不满 1 年）',
            'type': 'annualize_bonus',
        })

    # 13薪重叠
    thirteenth = code_results.get('possible_13th_overlap', [])
    if thirteenth:
        corr_id += 1
        corrections.append({
            'id': corr_id,
            'description': f'发现 {len(thirteenth)} 条记录浮动奖金疑似包含固定奖金部分，已标记',
            'type': '13th_month_reclassify',
        })

    # 月薪异常值
    salary_out = code_results.get('salary_outliers', [])
    if salary_out:
        rows_str = '、'.join(str(s['row_number']) for s in salary_out[:3])
        corr_id += 1
        corrections.append({
            'id': corr_id,
            'description': f'第 {rows_str} 行基本工资偏离同级中位值超3倍，已标记为异常值',
            'type': 'extreme_value',
        })

    # 年终奖异常值
    bonus_out = code_results.get('bonus_outliers', [])
    if bonus_out:
        rows_str = '、'.join(str(b['row_number']) for b in bonus_out[:3])
        corr_id += 1
        corrections.append({
            'id': corr_id,
            'description': f'第 {rows_str} 行浮动奖金偏离同级中位值超3倍，已标记为异常值',
            'type': 'extreme_value',
        })

    # 薪酬倒挂
    inversions = code_results.get('salary_inversions', [])
    if inversions:
        corr_id += 1
        corrections.append({
            'id': corr_id,
            'description': f'发现 {len(inversions)} 对上下级薪酬倒挂，已标记',
            'type': 'salary_inversion',
        })

    # 津贴异常
    allowance_alerts = code_results.get('allowance_alerts', [])
    if allowance_alerts:
        corr_id += 1
        corrections.append({
            'id': corr_id,
            'description': f'{len(allowance_alerts)} 条记录津贴超月薪30%，已标记',
            'type': 'allowance_high',
        })

    # 入司日期异常
    future_dates = code_results.get('future_dates', [])
    old_dates = code_results.get('old_dates', [])
    date_issues = future_dates + old_dates
    if date_issues:
        corr_id += 1
        corrections.append({
            'id': corr_id,
            'description': f'{len(date_issues)} 条记录入司时间异常（未来日期或过早），已标记',
            'type': 'date_anomaly',
        })

    # 高年终奖疑似长期激励
    high_bonus = code_results.get('high_bonus_suspects', [])
    if high_bonus:
        corr_id += 1
        corrections.append({
            'id': corr_id,
            'description': f'{len(high_bonus)} 条高职级员工年终奖远超同级中位值，疑似包含长期激励',
            'type': 'lti_suspect',
        })

    return corrections


def _merge_ai_corrections(corrections: list, ai_results: dict, code_results: dict) -> list:
    """把 AI 判断结果合并进 corrections，只保留自动修正项（不保留需用户确认的）"""
    judgments = ai_results.get('judgments', [])
    corr_id = max((c['id'] for c in corrections), default=0)

    for j in judgments:
        # 只保留不需要用户确认的自动修正项
        if j.get('needs_user_confirm', False):
            continue
        action = j.get('action', '')
        if not action:
            continue
        corr_id += 1
        # 格式化成用户看得懂的描述
        desc = _format_ai_judgment(j)
        corrections.append({
            'id': corr_id,
            'description': desc,
            'type': j.get('rule', 'ai_judgment'),
        })

    # 绩效映射
    perf_mapping = ai_results.get('performance_mapping')
    if perf_mapping and isinstance(perf_mapping, dict):
        detected = perf_mapping.get('detected_system', '')
        mapping = perf_mapping.get('mapping', {})
        confidence = perf_mapping.get('confidence', '')
        if mapping:
            corr_id += 1
            # 格式化成人话
            from_vals = list(mapping.keys())[:4]
            to_vals = list(mapping.values())[:4]
            from_str = '/'.join(str(v) for v in from_vals)
            to_str = '/'.join(str(v) for v in to_vals)
            corrections.append({
                'id': corr_id,
                'description': f'绩效等级已标准化（{from_str} → {to_str}）',
                'type': 'performance_mapping',
            })

    return corrections


def _format_ai_judgment(judgment: dict) -> str:
    """把 AI 判断结果格式化成用户看得懂的描述"""
    rule = judgment.get('rule', '')
    rows = judgment.get('rows', [])
    action = judgment.get('action', '')
    judgment_text = judgment.get('judgment', '')

    rows_str = '、'.join(str(r) for r in rows[:5]) if rows else ''

    if '年化' in rule or '年化' in action:
        return f'第 {rows_str} 行年终奖已年化处理（AI 判断为按月折算而非保底奖金）'
    elif '异常' in rule or '录入错误' in judgment_text:
        return f'第 {rows_str} 行薪酬异常值已修正（AI 判断为录入错误）'
    elif '13薪' in rule or '重复' in rule:
        return f'第 {rows_str} 行年终奖中13薪部分已分离'
    elif '长期激励' in rule or 'LTI' in rule.upper():
        return f'第 {rows_str} 行年终奖中疑似长期激励部分已标记'
    elif '部门' in rule:
        return f'部门名称已归并标准化'
    else:
        # 通用格式
        if judgment_text:
            return f'{judgment_text}（涉及第 {rows_str} 行）' if rows_str else judgment_text
        return action


def _run_grade_matching(grades_list: list, employees: list, rows: list, field_map: dict, code_results: dict | None) -> list:
    """运行职级匹配，LLM 失败则返回 low confidence 未匹配"""
    # 构建各职级详情（代表岗位 + 薪酬范围）
    grade_details = {}
    for emp in employees:
        g = emp['grade']
        if not g:
            continue
        if g not in grade_details:
            grade_details[g] = {
                'sample_titles': [],
                'salary_min': emp['base_monthly'] if emp['base_monthly'] > 0 else None,
                'salary_max': emp['base_monthly'] if emp['base_monthly'] > 0 else None,
                'count': 0,
            }
        detail = grade_details[g]
        detail['count'] += 1
        if emp['job_title'] and emp['job_title'] not in detail['sample_titles']:
            if len(detail['sample_titles']) < 3:
                detail['sample_titles'].append(emp['job_title'])
        sal = emp['base_monthly']
        if sal > 0:
            if detail['salary_min'] is None or sal < detail['salary_min']:
                detail['salary_min'] = sal
            if detail['salary_max'] is None or sal > detail['salary_max']:
                detail['salary_max'] = sal

    if not _has_api_key():
        return _fallback_grade_matching(grades_list)

    try:
        agent = MatchingAgent()
        result = agent.match_grades(grades_list, grade_details)
        llm_mapping = result.get('grade_mapping', [])

        # 转成前端期望的格式
        grade_matching = []
        matched_grades = set()
        for m in llm_mapping:
            client_g = m.get('client_grade', '')
            standard_g = m.get('standard_grade')
            conf = m.get('confidence', 'medium')
            grade_matching.append({
                'client_grade': client_g,
                'standard_grade': standard_g,
                'confidence': conf,
                'confirmed': conf == 'high',
            })
            matched_grades.add(client_g)

        # 补上 LLM 没返回的职级
        for g in grades_list:
            if g not in matched_grades:
                grade_matching.append({
                    'client_grade': g,
                    'standard_grade': None,
                    'confidence': 'low',
                    'confirmed': False,
                })

        return grade_matching

    except Exception as e:
        print(f'[Pipeline] grade matching LLM failed: {e}')
        return _fallback_grade_matching(grades_list)


def _fallback_grade_matching(grades_list: list) -> list:
    return [
        {'client_grade': g, 'standard_grade': None, 'confidence': 'low', 'confirmed': False}
        for g in grades_list
    ]


def _run_function_matching(employees: list) -> list:
    """运行职能匹配，LLM 失败则返回 low confidence 未匹配"""
    # 去重提取岗位名称 + 部门
    seen_titles = set()
    job_titles_with_dept = []
    for emp in employees:
        title = emp.get('job_title', '')
        if title and title not in seen_titles:
            seen_titles.add(title)
            job_titles_with_dept.append({
                'title': title,
                'department': emp.get('department', ''),
            })

    if not job_titles_with_dept:
        return []

    if not _has_api_key():
        return _fallback_function_matching(job_titles_with_dept)

    try:
        agent = MatchingAgent()
        result = agent.match_functions(job_titles_with_dept)
        llm_mapping = result.get('function_matching', [])

        # 转成前端期望的格式
        # LLM 返回的结果可能按输入顺序排列但缺少 title 字段，用索引回填
        func_matching = []
        matched_titles = set()
        for i, m in enumerate(llm_mapping):
            title = m.get('title', m.get('job_title', ''))
            # 如果 LLM 没返回 title，用输入列表的对应位置回填
            if not title and i < len(job_titles_with_dept):
                title = job_titles_with_dept[i]['title']
            matched_func = m.get('matched', m.get('matched_function'))
            conf = m.get('confidence', 'medium')
            alternatives = m.get('alternatives', [])
            # 跳过空 title（不该发生，但防御性处理）
            if not title:
                continue
            entry = {
                'title': title,
                'matched': matched_func,
                'confidence': conf,
                'confirmed': conf == 'high',
            }
            if alternatives:
                entry['alternatives'] = alternatives
            func_matching.append(entry)
            matched_titles.add(title)

        # 补上 LLM 没返回的岗位
        for jt in job_titles_with_dept:
            if jt['title'] not in matched_titles:
                func_matching.append({
                    'title': jt['title'],
                    'matched': None,
                    'confidence': 'low',
                    'confirmed': False,
                })

        return func_matching

    except Exception as e:
        print(f'[Pipeline] function matching LLM failed: {e}')
        return _fallback_function_matching(job_titles_with_dept)


def _fallback_function_matching(job_titles_with_dept: list) -> list:
    return [
        {'title': jt['title'], 'matched': None, 'confidence': 'low', 'confirmed': False}
        for jt in job_titles_with_dept
    ]


def _build_sparky_messages(
    row_missing, column_missing, corrections,
    grade_matching, function_matching, unlocked, locked,
) -> dict:
    """构建各步骤的 Sparky 消息，前端可用来替代硬编码"""
    msgs = {}

    # Step 2: 完整性
    if row_missing:
        sample = row_missing[:3]
        desc = '、'.join(f'第 {r["row"]} 行{r["field"]}' for r in sample)
        suffix = f'等 {len(row_missing)} 条' if len(row_missing) > 3 else f' {len(row_missing)} 条'
        msgs['step2_missing'] = f'有{suffix}记录关键字段缺失（{desc}）。建议你在 Excel 里补完后重新上传，或者直接跳过，我会排除这些记录继续分析。'
    else:
        msgs['step2_missing'] = '所有记录的关键字段都有值，数据完整度很好！'

    if column_missing:
        col_names = '、'.join(c['field'] for c in column_missing)
        msgs['step2_columns'] = f'另外有几个可选字段整列没填——{col_names}。这些不影响核心诊断，但相关的深度分析会受限。左边可以看详情。'
    else:
        msgs['step2_columns'] = ''

    # Step 3: 清洗
    if corrections:
        msgs['step3_corrections'] = f'发现几个需要处理的地方，我已经帮你自动修正了 {len(corrections)} 项。左边可以看到详情，有不对的可以撤回。'
    else:
        msgs['step3_corrections'] = '数据口径看起来没有明显问题，不需要额外修正。'

    # Step 4: 职级
    confirmed_grades = [g for g in grade_matching if g.get('confirmed')]
    unconfirmed_grades = [g for g in grade_matching if not g.get('confirmed')]
    if unconfirmed_grades:
        uncertain = '、'.join(g['client_grade'] for g in unconfirmed_grades[:3])
        msgs['step4_grades'] = f'大部分职级都对上了（{len(confirmed_grades)} 个高置信度），但 {uncertain} 我拿不准，需要你确认一下。'
    else:
        msgs['step4_grades'] = f'所有 {len(grade_matching)} 个职级都高置信度匹配上了！'

    # Step 5: 职能
    confirmed_funcs = [f for f in function_matching if f.get('confirmed')]
    unconfirmed_funcs = [f for f in function_matching if not f.get('confirmed') and f.get('title')]
    if unconfirmed_funcs:
        uncertain = '、'.join(f['title'] for f in unconfirmed_funcs[:3])
        msgs['step5_functions'] = f'大部分岗位都匹配上了（{len(confirmed_funcs)} 个高置信度），但 {uncertain} 我不太确定，需要你看一下。'
    else:
        msgs['step5_functions'] = f'所有 {len(function_matching)} 个岗位都匹配上了！'

    # Step 6: 就绪
    msgs['step6_ready'] = f'数据准备好了！这次诊断将覆盖{("、".join(unlocked[:3]))}等 {len(unlocked)} 个维度。'
    if locked:
        lock_hints = '、'.join(f'{l["name"]}（{l["reason"]}）' for l in locked)
        msgs['step6_locked'] = f'如果你能补充相关数据，我还能帮你做 {lock_hints}。不补也没关系，点"下一步"进入业务访谈。'
    else:
        msgs['step6_locked'] = '所有分析模块都已解锁！点"下一步"进入业务访谈。'

    return msgs
