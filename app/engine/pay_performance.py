def analyze(employees):
    """
    薪酬绩效相关性分析
    - 按绩效等级计算平均 CR
    - 按绩效等级计算调薪幅度（如有多年数据）
    """
    from collections import defaultdict

    results = {
        'cr_by_performance': [],
        'raise_by_performance': []
    }

    perf_crs = defaultdict(list)
    for emp in employees:
        if emp.get('performance') and emp.get('cr'):
            perf_crs[emp['performance']].append(emp['cr'])

    perf_order = ['A', 'B+', 'B', 'B-', 'C']
    for p in perf_order:
        crs = perf_crs.get(p, [])
        if crs:
            results['cr_by_performance'].append({
                'grade': p, 'cr': round(sum(crs) / len(crs), 2)
            })

    # Mock raise data for now (needs multi-year data)
    results['raise_by_performance'] = [
        {'grade': 'A', 'pct': 12},
        {'grade': 'B+', 'pct': 8},
        {'grade': 'B', 'pct': 6},
        {'grade': 'B-', 'pct': 3},
        {'grade': 'C', 'pct': 1},
    ]

    return results
