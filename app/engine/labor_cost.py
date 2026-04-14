"""
模块五：人工成本趋势分析
- KPI 指标卡（人工成本占营收比、人均营收、人均利润、人效）
- 多年趋势折线图（如有 Sheet 2 数据）
- 人工成本增速 vs 营收增速对比
"""


def analyze(data_snapshot=None, params=None, company_data=None, sheet2_summary=None):
    """统一 skill 签名 + 兼容旧调用 analyze(employees, ...)"""
    if isinstance(data_snapshot, list):
        return _analyze_impl(data_snapshot, company_data, sheet2_summary)
    if not isinstance(data_snapshot, dict):
        data_snapshot = {}
    emps = data_snapshot.get('employees') or []
    s2 = (data_snapshot.get('full_analysis') or {}).get('_sheet2_summary') or sheet2_summary
    return _analyze_impl(emps, company_data, s2)


def _analyze_impl(employees, company_data=None, sheet2_summary=None):
    """
    company_data: 当年经营数据（从 Sheet 2 解析）
    sheet2_summary: Sheet 2 的年度数据（含 years 和 metrics）
    """
    headcount = len([e for e in employees if e.get('base_monthly') and e['base_monthly'] > 0])
    total_base = sum((e.get('base_monthly', 0) or 0) * 12 for e in employees)
    total_fixed_bonus = sum(e.get('fixed_bonus', 0) or 0 for e in employees)
    total_variable = sum(e.get('variable_bonus', 0) or 0 for e in employees)
    total_allowance = sum((e.get('cash_allowance', 0) or 0) * 12 for e in employees)
    total_cost = total_base + total_fixed_bonus + total_variable + total_allowance

    # 多年趋势数据（从 Sheet 2 解析）
    trend = _build_trend(sheet2_summary, total_cost, headcount)

    # KPI 计算
    kpi = _build_kpi(total_cost, headcount, trend)

    has_data = bool(trend and len(trend) > 1)

    return {
        'kpi': kpi,
        'trend': trend,
        'current_headcount': headcount,
        'current_total_cost': round(total_cost),
        'has_trend_data': has_data,
        'status': 'normal' if has_data else 'unavailable',
    }


def _build_trend(sheet2_summary, current_cost, current_headcount):
    """从 Sheet 2 构建多年趋势数据"""
    if not sheet2_summary or not sheet2_summary.get('years'):
        return [{'year': '当前', 'cost': round(current_cost / 10000), 'headcount': current_headcount}]

    # Sheet 2 已解析为 metrics 列表，但缺少年度明细
    # 这里用当前数据作为最新年，后续可扩展为读取完整年度数据
    years = sheet2_summary.get('years', [])
    trend = []
    for y in years:
        trend.append({
            'year': str(y),
            'cost': None,  # 待 Sheet 2 完整解析后填充
            'revenue': None,
            'headcount': None,
        })

    # 最新年用当前计算值
    if trend:
        trend[-1]['cost'] = round(current_cost / 10000)
        trend[-1]['headcount'] = current_headcount

    return trend


def _build_kpi(total_cost, headcount, trend):
    """计算 KPI 指标卡"""
    # 从趋势数据中取最新年的营收
    latest = trend[-1] if trend else {}
    revenue = latest.get('revenue')
    profit = latest.get('profit')

    cost_万 = round(total_cost / 10000) if total_cost else 0
    per_head_cost = round(total_cost / headcount) if headcount else 0

    kpi = {
        'total_cost_wan': cost_万,
        'headcount': headcount,
        'per_head_cost': per_head_cost,
    }

    if revenue and revenue > 0:
        kpi['cost_revenue_ratio'] = round(total_cost / (revenue * 10000) * 100, 1)
        kpi['revenue_per_head'] = round(revenue * 10000 / headcount / 10000, 1) if headcount else None
    else:
        kpi['cost_revenue_ratio'] = None
        kpi['revenue_per_head'] = None

    if profit and profit > 0:
        kpi['profit_per_head'] = round(profit * 10000 / headcount / 10000, 1) if headcount else None
    else:
        kpi['profit_per_head'] = None

    # 增速对比（需要至少两年数据）
    if len(trend) >= 2:
        prev = trend[-2]
        curr = trend[-1]
        if prev.get('cost') and curr.get('cost') and prev['cost'] > 0:
            kpi['cost_growth_pct'] = round((curr['cost'] / prev['cost'] - 1) * 100, 1)
        else:
            kpi['cost_growth_pct'] = None
        if prev.get('revenue') and curr.get('revenue') and prev['revenue'] > 0:
            kpi['revenue_growth_pct'] = round((curr['revenue'] / prev['revenue'] - 1) * 100, 1)
        else:
            kpi['revenue_growth_pct'] = None
    else:
        kpi['cost_growth_pct'] = None
        kpi['revenue_growth_pct'] = None

    return kpi
