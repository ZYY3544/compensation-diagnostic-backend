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


def _analyze_impl(employees, market_lookup_fn, params=None):
    """
    employees: 清洗后的员工列表，需要有 job_function, hay_grade, tcc, base_monthly, department, grade
    market_lookup_fn: (job_function, hay_grade) -> market dict 或 None
    """
    # Step 1: 给每个员工算 CR 和分位
    for emp in employees:
        jf = emp.get('job_function', '')
        hg = emp.get('hay_grade')
        market = market_lookup_fn(jf, hg) if jf and hg else None

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

    # Step 2: 按职能分组
    func_groups = defaultdict(list)
    for emp in emps_with_cr:
        func_groups[emp.get('job_function', '未知')].append(emp)

    cr_by_function = []
    for func, emps in sorted(func_groups.items()):
        crs = [e['cr'] for e in emps]
        percentiles = [e['percentile'] for e in emps if e.get('percentile') is not None]
        avg_cr = safe_mean(crs)
        avg_pct = round(safe_mean(percentiles)) if percentiles else None
        below_p25 = sum(1 for e in emps if (e.get('percentile') or 50) < 25)
        cr_by_function.append({
            'name': func,
            'cr': avg_cr,
            'avg_percentile': avg_pct,
            'count': len(emps),
            'below_p25_count': below_p25,
            'status': 'warning' if avg_cr < 0.9 else 'normal',
        })

    # Step 3: CR 热力图（部门 × 职级）
    departments = sorted(set(e.get('department', '未知') for e in employees if e.get('department')))
    grades = sorted(set(e.get('grade', '') for e in employees if e.get('grade')))

    dept_grade = defaultdict(list)
    for emp in emps_with_cr:
        if emp.get('department') and emp.get('grade'):
            dept_grade[(emp['department'], emp['grade'])].append(emp['cr'])

    heatmap_values = []
    for dept in departments:
        row = []
        for grade in grades:
            crs = dept_grade.get((dept, grade), [])
            row.append(round(safe_mean(crs), 2) if crs else None)
        heatmap_values.append(row)

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

    return {
        'overall_cr': overall_cr,
        'total_employees_with_cr': total_with_cr,
        'total_below_p25': total_below_p25,
        'cr_by_function': cr_by_function,
        'cr_heatmap': {
            'departments': departments,
            'grades': grades,
            'values': heatmap_values,
        },
        'below_p25_detail': below_p25_detail[:20],
        'benchmark_results': benchmark_results,
        'summary': {
            'total_headcount': total_with_cr,
            'below_p25_count': total_below_p25,
            'below_p25_pct': round(total_below_p25 / total_with_cr * 100, 1) if total_with_cr > 0 else 0,
            'avg_percentile': avg_percentile,
        },
        'status': 'warning' if (overall_cr and overall_cr < 0.9) else 'normal',
    }
