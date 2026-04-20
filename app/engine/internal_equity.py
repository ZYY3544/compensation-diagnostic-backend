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
    """输出多维度预聚合视图：
    - 2 个薪酬口径：base（年基本工资）/ tcc（年度总现金）
    - 3 个范围：overall（公司整体）/ by_department.{部门} / by_function.{职能}

    前端通过 views[salary_type][scope] 切换，部门不足 2 人的职级/部门会被 boxplot
    自动跳过。顶层保留 base.overall 视图字段做老版兼容。"""
    departments = sorted(set(e.get('department', '') for e in employees if e.get('department')))
    grades = sorted(set(e.get('grade', '') for e in employees if e.get('grade')))
    functions = sorted(set(e.get('job_function', '') for e in employees if e.get('job_function')))

    def build(scope_emps):
        return {
            'base': _compute_view(scope_emps, 'base_annual', grades, departments),
            'tcc': _compute_view(scope_emps, 'tcc', grades, departments),
        }

    overall = build(employees)
    by_department = {
        dept: build([e for e in employees if e.get('department') == dept])
        for dept in departments
    }
    by_function = {
        func: build([e for e in employees if e.get('job_function') == func])
        for func in functions
    }

    base_overall = overall['base']
    return {
        # 顶层兼容字段 = base.overall 视图
        'deviation_matrix': base_overall['deviation_matrix'],
        'grade_dept_medians': base_overall['grade_dept_medians'],
        'dispersion': base_overall['dispersion'],
        'boxplot': base_overall['boxplot'],
        'high_dispersion_count': base_overall['high_dispersion_count'],
        'summary': base_overall['summary'],
        # 重模式切换：views[salary_type].{overall,by_department,by_function}
        'views': {
            'overall': overall,
            'by_department': by_department,
            'by_function': by_function,
        },
        'departments': departments,
        'functions': functions,
        'status': 'attention' if base_overall['high_dispersion_count'] > 0 else 'normal',
    }


def _compute_view(employees, salary_key, grades, departments):
    """按指定薪酬口径（salary_key: base_annual | tcc）算一套分析"""
    grade_salaries = defaultdict(list)
    dept_grade_salaries = defaultdict(list)

    for emp in employees:
        sal = emp.get(salary_key, 0) or 0
        if sal > 0 and emp.get('grade'):
            grade_salaries[emp['grade']].append(sal)
            if emp.get('department'):
                dept_grade_salaries[(emp['department'], emp['grade'])].append(sal)

    # 偏离度矩阵（老格式，保留做兼容）
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

    # 职级 × 部门 中位值矩阵（新格式：行=职级，列=部门，最右列=不分部门整体中位）
    def _median(nums):
        if not nums: return None
        s = sorted(nums)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    grade_dept_median_values = []  # shape: [grade][dept]
    grade_overall_medians = []     # shape: [grade]
    for grade in grades:
        row = []
        for dept in departments:
            sals = dept_grade_salaries.get((dept, grade), [])
            row.append(round(_median(sals)) if sals else None)
        grade_dept_median_values.append(row)
        overall = _median(grade_salaries.get(grade, []))
        grade_overall_medians.append(round(overall) if overall else None)

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
            'grade': grade, 'count': len(sals),
            'mean': round(safe_mean(sals)),
            'min': min(sals), 'max': max(sals),
            'coefficient': coeff, 'range_ratio': range_ratio,
            'status': status,
        })

    # 箱线图
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

    # summary（light skill MetricGrid 用）
    summary = {
        'total_groups': len(dispersion),
        'high_dispersion_count': high_dispersion_count,
        'max_cv_grade': None, 'max_cv': None,
        'max_range_ratio_grade': None, 'max_range_ratio': None,
    }
    if dispersion:
        worst_cv = max(dispersion, key=lambda d: d['coefficient'])
        summary['max_cv_grade'] = worst_cv['grade']
        summary['max_cv'] = worst_cv['coefficient']
        worst_range = max(dispersion, key=lambda d: d['range_ratio'])
        summary['max_range_ratio_grade'] = worst_range['grade']
        summary['max_range_ratio'] = worst_range['range_ratio']

    return {
        'deviation_matrix': {
            'departments': departments, 'grades': grades, 'values': deviation_values,
        },
        # 新：职级 × 部门 中位值矩阵
        'grade_dept_medians': {
            'grades': grades,
            'departments': departments,
            'values': grade_dept_median_values,       # [grade][dept] 绝对中位值
            'overall_medians': grade_overall_medians, # [grade] 不分部门的整体中位
        },
        'dispersion': dispersion,
        'boxplot': boxplot,
        'high_dispersion_count': high_dispersion_count,
        'summary': summary,
    }
