"""
模块四：绩效关联分析
- 不同绩效等级的平均薪酬和 CR
- 绩效等级间的薪酬差异倍数
- 高绩效 vs 低绩效的薪酬拉开程度
"""
from collections import defaultdict
from app.engine.common import safe_mean


PERF_ORDER = ['A', 'B+', 'B', 'B-', 'C']


def analyze(data_snapshot=None, params=None):
    """统一 skill 签名 + 兼容旧调用 analyze(employees)"""
    if isinstance(data_snapshot, list):
        return _analyze_impl(data_snapshot)
    if not isinstance(data_snapshot, dict):
        data_snapshot = {}
    return _analyze_impl(data_snapshot.get('employees') or [])


def _analyze_impl(employees):
    # 按绩效分组
    perf_groups = defaultdict(list)
    for emp in employees:
        perf = str(emp.get('performance', '')).strip()
        if perf and emp.get('base_monthly') and emp['base_monthly'] > 0:
            perf_groups[perf].append(emp)

    # 按绩效等级计算平均薪酬和 CR
    perf_stats = []
    perf_avg_salary = {}
    for p in PERF_ORDER:
        emps = perf_groups.get(p, [])
        if not emps:
            continue
        salaries = [e['base_monthly'] for e in emps]
        crs = [e['cr'] for e in emps if e.get('cr') is not None]
        avg_salary = round(safe_mean(salaries))
        avg_cr = round(safe_mean(crs), 2) if crs else None
        perf_avg_salary[p] = avg_salary
        perf_stats.append({
            'grade': p,
            'count': len(emps),
            'avg_salary': avg_salary,
            'avg_cr': avg_cr,
        })

    # 薪酬差异倍数：A vs C
    a_avg = perf_avg_salary.get('A', 0)
    c_avg = perf_avg_salary.get('C', 0)
    a_vs_c_ratio = round(a_avg / c_avg, 2) if c_avg > 0 else None

    # 高绩效(A) vs 平均绩效(B) 的差距
    b_avg = perf_avg_salary.get('B', 0)
    a_vs_b_gap_pct = round((a_avg / b_avg - 1) * 100, 1) if b_avg > 0 else None

    # 各绩效等级的 TCC 对比（用于柱状图）
    tcc_by_perf = []
    for p in PERF_ORDER:
        emps = perf_groups.get(p, [])
        if not emps:
            continue
        tccs = [e.get('tcc', 0) or (e.get('base_monthly', 0) * 12 + (e.get('variable_bonus', 0) or 0)) for e in emps]
        tcc_by_perf.append({
            'grade': p,
            'avg_tcc': round(safe_mean(tccs)),
            'count': len(emps),
        })

    # 判断是否"撒胡椒面"（高低绩效差距不够大）
    spread_adequate = True
    if a_vs_b_gap_pct is not None and a_vs_b_gap_pct < 10:
        spread_adequate = False

    has_perf_data = len(perf_stats) >= 2

    return {
        'perf_stats': perf_stats,
        'tcc_by_perf': tcc_by_perf,
        'a_vs_c_ratio': a_vs_c_ratio,
        'a_vs_b_gap_pct': a_vs_b_gap_pct,
        'spread_adequate': spread_adequate,
        'has_data': has_perf_data,
        'status': 'attention' if not spread_adequate else ('normal' if has_perf_data else 'unavailable'),
    }
