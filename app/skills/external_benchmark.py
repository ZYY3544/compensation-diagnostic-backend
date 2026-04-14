"""
外部市场对标（轻模式）：指定维度（职级 / 职能 / 部门 / 全公司）跟市场对比。
"""
from collections import defaultdict
from app.engine.common import calculate_cr, calculate_percentile_position, safe_mean
from app.services.market_data import lookup_market_salary


def run(employees: list, params: dict) -> dict:
    """
    params: {
      'dimension': 'grade' | 'function' | 'department' | 'overall',
      'filter': {'grade': 'L5', 'department': '研发部', ...}
    }
    返回结构化结果，叙事引擎读取生成 Sparky 文案。
    """
    dimension = params.get('dimension', 'grade')
    filt = params.get('filter', {}) or {}

    # 按筛选条件过滤
    filtered = _apply_filter(employees, filt)
    if not filtered:
        return {'error': '符合条件的员工数据不足', 'count': 0}

    # 给每个员工算 CR 和分位
    enriched = []
    for emp in filtered:
        jf = emp.get('job_function', '')
        hg = emp.get('hay_grade')
        market = lookup_market_salary(jf, hg) if jf and hg else None
        if market and market['base_p50'] > 0:
            cr = calculate_cr(emp.get('base_monthly', 0), market['base_p50'])
            pct = calculate_percentile_position(
                emp.get('base_monthly', 0),
                market['base_p25'], market['base_p50'], market['base_p75'],
            )
            enriched.append({**emp, '_cr': cr, '_pct': pct, '_market': market})

    if not enriched:
        return {'error': '市场数据未覆盖这些岗位', 'count': len(filtered)}

    # 按维度聚合
    if dimension == 'grade':
        groups = _group_by(enriched, 'grade')
    elif dimension == 'function':
        groups = _group_by(enriched, 'job_function')
    elif dimension == 'department':
        groups = _group_by(enriched, 'department')
    else:  # overall
        groups = {'全公司': enriched}

    rows = []
    for name, emps in groups.items():
        crs = [e['_cr'] for e in emps if e.get('_cr') is not None]
        pcts = [e['_pct'] for e in emps if e.get('_pct') is not None]
        if not crs:
            continue
        avg_cr = round(safe_mean(crs), 2)
        avg_pct = round(safe_mean(pcts)) if pcts else None
        median_salary = _median([e.get('base_monthly', 0) for e in emps])
        market_p50 = _median([e['_market']['base_p50'] for e in emps if e.get('_market')])
        market_p25 = _median([e['_market']['base_p25'] for e in emps if e.get('_market')])
        market_p75 = _median([e['_market']['base_p75'] for e in emps if e.get('_market')])
        rows.append({
            'name': str(name),
            'headcount': len(emps),
            'actual_median': round(median_salary),
            'market_p25': round(market_p25),
            'market_p50': round(market_p50),
            'market_p75': round(market_p75),
            'avg_cr': avg_cr,
            'avg_percentile': avg_pct,
            'gap_to_p50': round(median_salary - market_p50),
            'status': 'low' if avg_pct and avg_pct < 25 else 'mid' if avg_pct and avg_pct < 50 else 'ok',
        })

    rows.sort(key=lambda r: r.get('avg_percentile') or 50)

    total_cr = round(safe_mean([r['avg_cr'] for r in rows]), 2)
    lowest = rows[0] if rows else None

    return {
        'dimension': dimension,
        'filter': filt,
        'total_employees': len(enriched),
        'rows': rows,
        'overall_cr': total_cr,
        'lowest_group': lowest,
    }


def _apply_filter(employees: list, filt: dict) -> list:
    result = employees
    for k, v in filt.items():
        if not v:
            continue
        result = [e for e in result if str(e.get(k, '')) == str(v)]
    return result


def _group_by(items: list, key: str) -> dict:
    groups = defaultdict(list)
    for item in items:
        k = item.get(key) or '未知'
        groups[k].append(item)
    return dict(groups)


def _median(values: list) -> float:
    vs = sorted(v for v in values if v and v > 0)
    if not vs:
        return 0
    n = len(vs)
    return vs[n // 2] if n % 2 == 1 else (vs[n // 2 - 1] + vs[n // 2]) / 2
