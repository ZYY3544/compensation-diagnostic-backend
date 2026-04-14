"""
调薪预算模拟（轻模式）：
给定一组员工 + 目标分位值，算出调薪后的总预算、人均增量、分层建议。
"""
from app.services.market_data import lookup_market_salary
from app.engine.common import calculate_percentile_position


def run(employees: list, params: dict) -> dict:
    """
    params: {
      'filter': {'grade': 'L5', 'department': '研发部', ...},
      'target_percentile': 50,  # 目标分位值
      'strategy': 'uniform' | 'tiered',  # 统一调 or 分层
    }
    """
    filt = params.get('filter', {}) or {}
    target_pct = params.get('target_percentile', 50)
    strategy = params.get('strategy', 'tiered')

    filtered = _apply_filter(employees, filt)
    if not filtered:
        return {'error': '符合条件的员工不足', 'count': 0}

    # 算每个人的目标薪酬
    plan = []
    for emp in filtered:
        jf = emp.get('job_function', '')
        hg = emp.get('hay_grade')
        market = lookup_market_salary(jf, hg) if jf and hg else None
        if not market:
            continue

        current = emp.get('base_monthly', 0)
        target_key = f'base_p{target_pct}' if target_pct in (25, 50, 75) else 'base_p50'
        target_salary = market.get(target_key, market.get('base_p50', 0))

        # 分层策略：绩效 A 的优先调到 P60，其他人调到 P40
        if strategy == 'tiered':
            perf = str(emp.get('performance', '')).strip()
            if perf == 'A':
                # P60 近似用 (P50+P75)/2
                target_salary = round((market['base_p50'] + market['base_p75']) / 2)
            elif perf in ('B', 'B-', 'C'):
                # P40 近似用 (P25+P50)/2
                target_salary = round((market['base_p25'] + market['base_p50']) / 2)

        annual_delta = max(0, (target_salary - current) * 12)
        plan.append({
            'id': emp.get('id', ''),
            'job_title': emp.get('job_title', ''),
            'grade': emp.get('grade', ''),
            'performance': emp.get('performance', ''),
            'current_monthly': current,
            'target_monthly': target_salary,
            'monthly_delta': target_salary - current,
            'annual_delta': annual_delta,
        })

    total_annual_delta = sum(p['annual_delta'] for p in plan)
    hc = len(plan)
    avg_per_head = round(total_annual_delta / hc) if hc else 0

    # 同时算 uniform 版本（全部调到目标分位）做对比
    uniform_total = 0
    for emp in filtered:
        jf = emp.get('job_function', '')
        hg = emp.get('hay_grade')
        market = lookup_market_salary(jf, hg) if jf and hg else None
        if not market:
            continue
        target_key = f'base_p{target_pct}' if target_pct in (25, 50, 75) else 'base_p50'
        target_salary = market.get(target_key, market.get('base_p50', 0))
        uniform_total += max(0, (target_salary - emp.get('base_monthly', 0)) * 12)

    savings_pct = round((uniform_total - total_annual_delta) / uniform_total * 100) if uniform_total > 0 else 0

    return {
        'filter': filt,
        'target_percentile': target_pct,
        'strategy': strategy,
        'headcount': hc,
        'total_annual_delta': total_annual_delta,
        'avg_per_head': avg_per_head,
        'uniform_total': uniform_total,
        'savings_pct': savings_pct,
        'plan': plan,
    }


def _apply_filter(employees: list, filt: dict) -> list:
    result = employees
    for k, v in filt.items():
        if not v:
            continue
        result = [e for e in result if str(e.get(k, '')) == str(v)]
    return result
