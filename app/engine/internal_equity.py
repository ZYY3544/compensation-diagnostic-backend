"""
模块二：内部公平性分析
- 同职级同职能内的薪酬离散系数、极差比
- 部门×职级偏离度矩阵
- 各层级薪酬分布（用于箱线图）
"""
from collections import defaultdict
from app.engine.common import calculate_dispersion, calculate_range_ratio, safe_mean


def analyze(data_snapshot=None, params=None):
    """统一 skill 签名 + 兼容旧调用 analyze(employees)"""
    if isinstance(data_snapshot, list):
        return _analyze_impl(data_snapshot)
    if not isinstance(data_snapshot, dict):
        data_snapshot = {}
    return _analyze_impl(data_snapshot.get('employees') or [])


def _analyze_impl(employees):
    departments = sorted(set(e.get('department', '') for e in employees if e.get('department')))
    grades = sorted(set(e.get('grade', '') for e in employees if e.get('grade')))

    # 分组
    grade_salaries = defaultdict(list)
    dept_grade_salaries = defaultdict(list)

    for emp in employees:
        sal = emp.get('base_monthly', 0) or 0
        if sal > 0 and emp.get('grade'):
            grade_salaries[emp['grade']].append(sal)
            if emp.get('department'):
                dept_grade_salaries[(emp['department'], emp['grade'])].append(sal)

    # 偏离度矩阵（数值，不是字符串）
    deviation_values = []
    for dept in departments:
        row = []
        for grade in grades:
            dept_sals = dept_grade_salaries.get((dept, grade), [])
            all_sals = grade_salaries.get(grade, [])
            if dept_sals and all_sals:
                dept_avg = safe_mean(dept_sals)
                all_avg = safe_mean(all_sals)
                deviation = round((dept_avg / all_avg - 1) * 100, 1) if all_avg > 0 else 0
                row.append(deviation)
            else:
                row.append(None)
        deviation_values.append(row)

    # 离散度分析
    dispersion = []
    high_dispersion_count = 0
    for grade in grades:
        sals = grade_salaries.get(grade, [])
        if len(sals) < 2:
            continue
        coeff = calculate_dispersion(sals)
        range_ratio = calculate_range_ratio(sals)
        status = 'high' if coeff > 0.3 else 'normal'
        if status == 'high':
            high_dispersion_count += 1
        dispersion.append({
            'grade': grade,
            'count': len(sals),
            'mean': round(safe_mean(sals)),
            'min': min(sals),
            'max': max(sals),
            'coefficient': coeff,
            'range_ratio': range_ratio,
            'status': status,
        })

    # 箱线图数据（每个职级的分布）
    boxplot = []
    for grade in grades:
        sals = sorted(grade_salaries.get(grade, []))
        if len(sals) < 2:
            continue
        n = len(sals)
        boxplot.append({
            'grade': grade,
            'min': sals[0],
            'q1': sals[n // 4] if n >= 4 else sals[0],
            'median': sals[n // 2],
            'q3': sals[3 * n // 4] if n >= 4 else sals[-1],
            'max': sals[-1],
        })

    return {
        'deviation_matrix': {
            'departments': departments,
            'grades': grades,
            'values': deviation_values,
        },
        'dispersion': dispersion,
        'boxplot': boxplot,
        'high_dispersion_count': high_dispersion_count,
        'status': 'attention' if high_dispersion_count > 0 else 'normal',
    }
