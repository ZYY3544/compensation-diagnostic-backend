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

    # Step 5: 偏离严重 Top 5（按职能×职级分组，回答"先调谁"）
    deviation_top, deviation_anomalies, summary_text = _compute_deviation_top(emps_with_cr)

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
        'deviation_top': deviation_top,
        'deviation_anomalies': deviation_anomalies,
        'summary_text': summary_text,
        'summary': {
            'total_headcount': total_with_cr,
            'below_p25_count': total_below_p25,
            'below_p25_pct': round(total_below_p25 / total_with_cr * 100, 1) if total_with_cr > 0 else 0,
            'avg_percentile': avg_percentile,
        },
        'status': 'warning' if (overall_cr and overall_cr < 0.9) else 'normal',
    }


def _median(values):
    """纯数值列表的中位数，空列表返回 0"""
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _compute_deviation_top(emps_with_cr):
    """
    按职能×职级分组，找出公司中位值偏离市场 P50 最严重的 Top 5。
    - 剔除 headcount < 3 的组（样本不足）
    - 偏离 > 200% 的组放 anomalies（疑似数据异常）
    - 返回 (deviation_top, deviation_anomalies, summary_text)
    """
    groups = defaultdict(list)
    for emp in emps_with_cr:
        jf = emp.get('job_function')
        gr = emp.get('grade')
        if jf and gr and emp.get('_market'):
            groups[(jf, gr)].append(emp)

    candidates = []
    anomalies = []
    for (jf, gr), group_emps in groups.items():
        headcount = len(group_emps)
        market_p50 = group_emps[0]['_market'].get('base_p50') or 0
        if not market_p50:
            continue
        company_median = _median([e.get('base_monthly', 0) for e in group_emps])
        deviation_pct = (company_median - market_p50) / market_p50 * 100

        entry = {
            'function': jf,
            'grade': gr,
            'headcount': headcount,
            'company_median': round(company_median),
            'market_p50': round(market_p50),
            'deviation_pct': round(deviation_pct, 1),
        }

        # 样本不足 或 偏离 > 200% → anomalies（不纳入 Top 5）
        if headcount < 3 or abs(deviation_pct) > 200:
            anomalies.append({**entry, 'note': '样本量过小或数据异常'})
            continue

        entry['direction'] = 'below' if deviation_pct < 0 else 'above'
        candidates.append(entry)

    candidates.sort(key=lambda x: abs(x['deviation_pct']), reverse=True)
    deviation_top = [{'rank': i + 1, **item} for i, item in enumerate(candidates[:5])]

    total = len(deviation_top)
    below = sum(1 for x in deviation_top if x['deviation_pct'] < 0)
    above = total - below
    if total == 0:
        summary_text = '暂未识别出明显偏离市场的岗位组'
    else:
        summary_text = f'共识别出 {total} 个明显偏离市场的岗位组，其中 {below} 个偏低需要补齐，{above} 个偏高建议核查'

    # anomalies 按偏离幅度绝对值倒序（最异常的在前）
    anomalies.sort(key=lambda x: abs(x['deviation_pct']), reverse=True)

    return deviation_top, anomalies, summary_text
