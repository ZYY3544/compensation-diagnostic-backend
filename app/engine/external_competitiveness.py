"""
模块一：外部竞争力分析
- 每个员工的 TCC 与市场 P25/P50/P75 对比
- 按部门×职级生成 CR 热力图
- 按职能分组计算平均 CR 和分位
- 标记低于 P25 的岗位
"""
from collections import defaultdict
from app.engine.common import calculate_cr, calculate_percentile_position, safe_mean


def analyze(data_snapshot=None, params=None, **kwargs):
    """
    统一 skill 签名入口：analyze(data_snapshot, params)
    兼容旧调用：analyze(employees, market_lookup_fn)
    """
    from app.services.market_data import lookup_market_salary

    # 兼容旧签名
    if isinstance(data_snapshot, list):
        return _analyze_impl(data_snapshot, kwargs.get('market_lookup_fn') or params or lookup_market_salary)

    # 新签名
    if not isinstance(data_snapshot, dict):
        data_snapshot = {}
    employees = data_snapshot.get('employees') or []
    params = params or {}

    # 应用 params.filter
    filtered = _apply_filter(employees, params)
    return _analyze_impl(filtered, lookup_market_salary, params=params)


def _apply_filter(employees, params):
    """按 params 筛选员工（scope/department/grade/function）"""
    scope = params.get('scope', '全公司')
    dept = params.get('department')
    grade = params.get('grade')
    func = params.get('function')

    result = employees
    if dept:
        result = [e for e in result if dept in str(e.get('department', ''))]
    if grade:
        result = [e for e in result if str(e.get('grade', '')) == str(grade)]
    if func:
        result = [e for e in result if func in str(e.get('job_function', ''))]
    return result


def _guess_market_function(job_title: str, family: str = '') -> str:
    """从 job_title / family 名称推断市场数据里的 job_function"""
    t = (job_title or '').lower()
    f = (family or '')
    # HR 族细分
    if 'hrbp' in t or 'hr bp' in t: return 'HRBP'
    if '招聘' in t or 'recruit' in t: return '招聘'
    if '薪酬' in t or 'comp' in t or 'c&b' in t: return '薪酬管理'
    if '绩效' in t: return '绩效管理'
    if '培训' in t or 'td' in t or '人才发展' in t: return '人才发展'
    if '员工关系' in t or 'er' in t: return '员工关系'
    if '组织' in t or 'od' in t: return '组织文化'
    if 'hr' in t or '人力' in t or f == '人力资源':
        return 'HRBP'  # 默认 HR 族走 HRBP
    return ''


def _analyze_impl(employees, market_lookup_fn, params=None):
    """
    employees: 清洗后的员工列表，需要有 job_function, hay_grade, tcc, base_monthly, department, grade
    market_lookup_fn: (job_function, hay_grade) -> market dict 或 None
    """
    # Step 1: 给每个员工算 CR 和分位
    for emp in employees:
        jf = emp.get('job_function', '')
        hg = emp.get('hay_grade')
        # 先用 emp.job_function 查；查不到用 job_title 关键词兜底映射到市场职能
        market = market_lookup_fn(jf, hg) if jf and hg else None
        if not market and hg:
            fallback_jf = _guess_market_function(emp.get('job_title', ''), jf)
            if fallback_jf and fallback_jf != jf:
                market = market_lookup_fn(fallback_jf, hg)
                if market:
                    jf = fallback_jf
                    emp['job_function'] = fallback_jf

        if market and market['base_p50'] > 0:
            emp['cr'] = calculate_cr(emp.get('base_monthly', 0), market['base_p50'])
            emp['percentile'] = calculate_percentile_position(
                emp.get('base_monthly', 0),
                market['base_p25'], market['base_p50'], market['base_p75'],
            )
            emp['_market'] = market
        else:
            emp['cr'] = None
            emp['percentile'] = None
            emp['_market'] = None

    emps_with_cr = [e for e in employees if e.get('cr') is not None]

    # Step 3: CR 热力图（职能 × 职级）—— 部门视角已经被职级偏离柱图覆盖，这里换职能维度避免重复
    departments = sorted(set(e.get('department', '未知') for e in employees if e.get('department')))
    grades = sorted(set(e.get('grade', '') for e in employees if e.get('grade')))
    functions = sorted(set(e.get('job_function', '') for e in employees if e.get('job_function')))

    func_grade = defaultdict(list)
    for emp in emps_with_cr:
        if emp.get('job_function') and emp.get('grade'):
            func_grade[(emp['job_function'], emp['grade'])].append(emp['cr'])

    heatmap_values = []
    heatmap_counts = []
    for func in functions:
        row_values = []
        row_counts = []
        for grade in grades:
            crs = func_grade.get((func, grade), [])
            row_values.append(round(safe_mean(crs), 2) if crs else None)
            row_counts.append(len(crs))
        heatmap_values.append(row_values)
        heatmap_counts.append(row_counts)

    # benchmark_results 还是按部门×职级（给意图查询用），保留 dept_grade 索引
    dept_grade = defaultdict(list)
    for emp in emps_with_cr:
        if emp.get('department') and emp.get('grade'):
            dept_grade[(emp['department'], emp['grade'])].append(emp['cr'])

    # Step 4: 低于 P25 的岗位明细（前端可展示）
    below_p25_detail = []
    for emp in emps_with_cr:
        if (emp.get('percentile') or 50) < 25:
            below_p25_detail.append({
                'id': emp.get('id', ''),
                'job_title': emp.get('job_title', ''),
                'department': emp.get('department', ''),
                'grade': emp.get('grade', ''),
                'base_monthly': emp.get('base_monthly', 0),
                'cr': emp['cr'],
                'percentile': emp['percentile'],
            })

    # 汇总
    overall_cr = safe_mean([e['cr'] for e in emps_with_cr]) if emps_with_cr else None
    total_below_p25 = len(below_p25_detail)
    total_with_cr = len(emps_with_cr)

    # 计算平均分位（skill 的 output_schema 里要的 summary.avg_percentile）
    percentiles = [e.get('percentile') for e in emps_with_cr if e.get('percentile') is not None]
    avg_percentile = round(safe_mean(percentiles)) if percentiles else None

    # 分位段人数分布：<P25 / P25-P50 / P50-P75 / >P75（顶部 KPI 总览用）
    seg_counts = {'below_p25': 0, 'p25_p50': 0, 'p50_p75': 0, 'above_p75': 0}
    for p in percentiles:
        if p < 25: seg_counts['below_p25'] += 1
        elif p < 50: seg_counts['p25_p50'] += 1
        elif p < 75: seg_counts['p50_p75'] += 1
        else: seg_counts['above_p75'] += 1
    total_p = len(percentiles)
    segment_distribution = [
        {'key': 'below_p25', 'label': '< P25', 'count': seg_counts['below_p25'],
         'pct': round(seg_counts['below_p25'] / total_p * 100, 1) if total_p else 0},
        {'key': 'p25_p50', 'label': 'P25 - P50', 'count': seg_counts['p25_p50'],
         'pct': round(seg_counts['p25_p50'] / total_p * 100, 1) if total_p else 0},
        {'key': 'p50_p75', 'label': 'P50 - P75', 'count': seg_counts['p50_p75'],
         'pct': round(seg_counts['p50_p75'] / total_p * 100, 1) if total_p else 0},
        {'key': 'above_p75', 'label': '> P75', 'count': seg_counts['above_p75'],
         'pct': round(seg_counts['above_p75'] / total_p * 100, 1) if total_p else 0},
    ]

    # benchmark_results: 按部门×层级聚合
    benchmark_results = []
    for dept in departments:
        for grade in grades:
            crs = dept_grade.get((dept, grade), [])
            if not crs:
                continue
            group_emps = [e for e in emps_with_cr if e.get('department') == dept and e.get('grade') == grade]
            if not group_emps:
                continue
            group_pcts = [e.get('percentile') for e in group_emps if e.get('percentile') is not None]
            company_median = sorted([e['base_monthly'] for e in group_emps])[len(group_emps) // 2] if group_emps else 0
            markets = [e.get('_market') for e in group_emps if e.get('_market')]
            if not markets:
                continue
            market = markets[0]
            pct = round(safe_mean(group_pcts)) if group_pcts else None
            benchmark_results.append({
                'department': dept,
                'grade': grade,
                'headcount': len(group_emps),
                'company_median': company_median,
                'market_p25': market.get('base_p25'),
                'market_p50': market.get('base_p50'),
                'market_p75': market.get('base_p75'),
                'percentile': pct,
                'gap_to_p50': company_median - market.get('base_p50', 0),
                'status': 'below_p25' if pct and pct < 25 else 'below_p50' if pct and pct < 50 else 'normal',
            })

    # Step 5: 偏离市场最大的员工（取前 10%）
    # 先算公司同职级 P50（不分部门），给 deviation_top 每条加 company_grade_p50
    grade_company_p50 = {}
    grade_to_emps = defaultdict(list)
    for emp in emps_with_cr:
        if emp.get('grade'):
            grade_to_emps[emp['grade']].append(emp.get('base_monthly') or 0)
    for g, sals in grade_to_emps.items():
        sals_sorted = sorted([s for s in sals if s > 0])
        if sals_sorted:
            n = len(sals_sorted)
            grade_company_p50[g] = (sals_sorted[n // 2] if n % 2 else
                                    (sals_sorted[n // 2 - 1] + sals_sorted[n // 2]) / 2)

    deviation_top, summary_text = _compute_deviation_top(emps_with_cr, grade_company_p50)

    return {
        'overall_cr': overall_cr,
        'total_employees_with_cr': total_with_cr,
        'total_below_p25': total_below_p25,
        'cr_heatmap': {
            # 行维度从 departments 改为 functions（保持 'rows' 这个语义化键，
            # 同时为兼容旧前端短期保留 functions 别名）
            'rows': functions,
            'row_label': '职能',
            'functions': functions,
            'grades': grades,
            'values': heatmap_values,
            'counts': heatmap_counts,
        },
        'below_p25_detail': below_p25_detail[:20],
        'benchmark_results': benchmark_results,
        'deviation_top': deviation_top,
        'summary_text': summary_text,
        'summary': {
            'total_headcount': total_with_cr,
            'below_p25_count': total_below_p25,
            'below_p25_pct': round(total_below_p25 / total_with_cr * 100, 1) if total_with_cr > 0 else 0,
            'avg_percentile': avg_percentile,
            'segment_distribution': segment_distribution,
        },
        'status': 'warning' if (overall_cr and overall_cr < 0.9) else 'normal',
    }


def _compute_deviation_top(emps_with_cr, grade_company_p50=None):
    """
    按员工粒度（不再按岗位组），把每个人的 base_monthly vs 市场 P50 的偏离绝对值
    排序后取前 10%。
    - 异常值 should 已在数据清洗阶段处理，这里不再过滤
    - 至少返回 3 条避免太少；候选不足 3 时全返
    - grade_company_p50: {grade: 公司同职级 P50}，用于表格展示"所在级别公司 P50"
    - 返回 (deviation_top, summary_text)
    """
    import math
    grade_company_p50 = grade_company_p50 or {}
    candidates = []
    for emp in emps_with_cr:
        market = emp.get('_market') or {}
        market_p50 = market.get('base_p50') or 0
        base_monthly = emp.get('base_monthly') or 0
        if not market_p50 or not base_monthly:
            continue
        deviation_pct = (base_monthly - market_p50) / market_p50 * 100
        grade = emp.get('grade', '')
        candidates.append({
            'id': emp.get('id', ''),
            'job_title': emp.get('job_title', ''),
            'department': emp.get('department', ''),
            'function': emp.get('job_function', ''),
            'grade': grade,
            'base_monthly': round(base_monthly),
            'company_grade_p50': round(grade_company_p50.get(grade, 0)),
            'market_p50': round(market_p50),
            'deviation_pct': round(deviation_pct, 1),
            'direction': 'below' if deviation_pct < 0 else 'above',
        })

    candidates.sort(key=lambda x: abs(x['deviation_pct']), reverse=True)
    cutoff = max(3, math.ceil(len(candidates) * 0.1))
    deviation_top = [{'rank': i + 1, **item} for i, item in enumerate(candidates[:cutoff])]

    total = len(deviation_top)
    below = sum(1 for x in deviation_top if x['deviation_pct'] < 0)
    above = total - below
    if total == 0:
        summary_text = '暂未识别出偏离市场的员工'
    else:
        summary_text = (f'按个人偏离市场 P50 的幅度取前 10%（共 {total} 人），'
                        f'其中 {below} 人偏低需要补齐，{above} 人偏高建议核查')

    return deviation_top, summary_text
