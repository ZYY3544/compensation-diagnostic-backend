"""
调薪预算模拟 engine。
对比方案A（统一调至 P50）和方案B（分层调整，推荐）的预算差异。
"""
from app.services.market_data import lookup_market_salary


def simulate(data_snapshot=None, params=None):
    """
    params: {
        'scope': '全公司' | '指定部门' | '指定职级',
        'department': '研发'(可选),
        'target_percentile': 50,
    }
    """
    if not isinstance(data_snapshot, dict):
        return {'error': '缺少数据快照'}
    employees = data_snapshot.get('employees') or []
    params = params or {}

    # 筛选
    filtered = _apply_filter(employees, params)
    if not filtered:
        return {'error': '符合条件的员工不足', 'count': 0}

    target_pct = int(params.get('target_percentile', 50) or 50)

    # 方案 A：全部调到目标分位
    plan_a_total, plan_a_details = _simulate_uniform(filtered, target_pct)

    # 方案 B：分层调整（A 绩效到 P60，B 到 P50，B- 以下到 P40）
    plan_b_total, plan_b_details = _simulate_tiered(filtered, target_pct)

    # 薪酬总盘 = 当前月薪 × 12 × 人数
    current_payroll = sum(e.get('base_monthly', 0) or 0 for e in filtered) * 12
    pct_of_payroll_a = round(plan_a_total / current_payroll * 100, 1) if current_payroll > 0 else 0
    savings = round((plan_a_total - plan_b_total) / plan_a_total * 100) if plan_a_total > 0 else 0

    return {
        'scope': params.get('scope', '全公司'),
        'department': params.get('department'),
        'target_percentile': target_pct,
        'headcount_affected': len(filtered),
        'plan_a': {
            'name': f'统一调至 P{target_pct}',
            'total_budget': plan_a_total,
            'headcount_affected': len(filtered),
            'pct_of_payroll': pct_of_payroll_a,
            'details': plan_a_details[:20],
        },
        'plan_b': {
            'name': '分层调整（推荐）',
            'total_budget': plan_b_total,
            'savings': savings,
            'details': plan_b_details[:20],
        },
    }


def _apply_filter(employees, params):
    dept = params.get('department')
    grade = params.get('grade')
    result = employees
    if dept:
        result = [e for e in result if dept in str(e.get('department', ''))]
    if grade:
        result = [e for e in result if str(e.get('grade', '')) == str(grade)]
    return result


def _simulate_uniform(employees, target_pct):
    """方案A：所有人调到 target_pct"""
    total = 0
    details = []
    for emp in employees:
        market = lookup_market_salary(emp.get('job_function', ''), emp.get('hay_grade'))
        if not market:
            continue
        target_key = f'base_p{target_pct}' if target_pct in (25, 50, 75) else 'base_p50'
        target_salary = market.get(target_key, market.get('base_p50', 0))
        current = emp.get('base_monthly', 0) or 0
        delta = max(0, (target_salary - current) * 12)
        total += delta
        if delta > 0:
            details.append({
                'id': emp.get('id', ''), 'grade': emp.get('grade', ''),
                'current': current * 12, 'target': target_salary * 12,
                'annual_delta': delta,
            })
    return total, details


def _simulate_tiered(employees, target_pct):
    """方案B：按绩效分层（A→P60，B→P50，其他→P40）"""
    total = 0
    details = []
    for emp in employees:
        market = lookup_market_salary(emp.get('job_function', ''), emp.get('hay_grade'))
        if not market:
            continue
        perf = str(emp.get('performance', '')).strip()
        # 分层规则
        if perf == 'A':
            target_salary = round((market.get('base_p50', 0) + market.get('base_p75', 0)) / 2)  # ~P60
            tier = 'P60'
        elif perf in ('B+', 'B'):
            target_salary = market.get('base_p50', 0)
            tier = 'P50'
        else:
            target_salary = round((market.get('base_p25', 0) + market.get('base_p50', 0)) / 2)  # ~P40
            tier = 'P40'
        current = emp.get('base_monthly', 0) or 0
        delta = max(0, (target_salary - current) * 12)
        total += delta
        if delta > 0:
            details.append({
                'id': emp.get('id', ''), 'grade': emp.get('grade', ''),
                'performance': perf, 'tier': tier,
                'current': current * 12, 'target': target_salary * 12,
                'annual_delta': delta,
            })
    return total, details
