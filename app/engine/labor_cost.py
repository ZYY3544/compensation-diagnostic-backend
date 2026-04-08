def analyze(employees, company_data=None):
    """
    人工成本分析
    - KPI 指标卡
    - 成本趋势（如有多年数据）
    """
    results = {
        'kpi': {},
        'trend': []
    }

    # Calculate from employee data
    total_base = sum(e.get('base_monthly', 0) * 12 for e in employees)
    total_bonus = sum(e.get('annual_bonus', 0) for e in employees)
    total_cost = total_base + total_bonus
    headcount = len(employees)

    if company_data:
        revenue = company_data.get('revenue', 0)
        profit = company_data.get('profit', 0)

        results['kpi'] = {
            'cost_revenue_ratio': {
                'value': round(total_cost / revenue * 100) if revenue else None,
                'trend': 'up', 'label': '偏高' if revenue and total_cost / revenue > 0.3 else '正常'
            },
            'revenue_per_head': {
                'value': round(revenue / headcount / 10000) if headcount else None,
                'trend': 'flat', 'label': '持平'
            },
            'profit_per_head': {
                'value': round(profit / headcount / 10000) if headcount else None,
                'trend': 'down', 'label': '偏低' if profit and profit / headcount < 150000 else '正常'
            },
            'cost_vs_revenue_growth': {'cost': None, 'revenue': None, 'label': '数据不足'},
        }
    else:
        results['kpi'] = {
            'cost_revenue_ratio': {'value': None, 'label': '缺少营收数据'},
            'revenue_per_head': {'value': None, 'label': '缺少营收数据'},
            'profit_per_head': {'value': None, 'label': '缺少利润数据'},
            'cost_vs_revenue_growth': {'value': None, 'label': '缺少经营数据'},
        }

    results['trend'] = [{'year': '当前', 'cost': round(total_cost / 10000)}]

    return results
