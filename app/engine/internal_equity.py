def analyze(employees):
    """
    内部公平性分析
    - 部门薪酬偏离度矩阵 (部门均值/公司均值 - 1)
    - 同级别离散系数和极差比
    """
    from collections import defaultdict
    import statistics

    results = {
        'deviation_matrix': {'departments': [], 'grades': [], 'values': []},
        'dispersion': []
    }

    departments = sorted(set(e.get('department', '') for e in employees if e.get('department')))
    grades = sorted(set(e.get('grade', '') for e in employees if e.get('grade')))

    results['deviation_matrix']['departments'] = departments
    results['deviation_matrix']['grades'] = grades

    # Group salaries
    grade_salaries = defaultdict(list)
    dept_grade_salaries = defaultdict(list)

    for emp in employees:
        sal = emp.get('base_monthly', 0)
        if sal and emp.get('grade'):
            grade_salaries[emp['grade']].append(sal)
            if emp.get('department'):
                dept_grade_salaries[(emp['department'], emp['grade'])].append(sal)

    # Deviation matrix
    for dept in departments:
        row = []
        for grade in grades:
            dept_sals = dept_grade_salaries.get((dept, grade), [])
            all_sals = grade_salaries.get(grade, [])
            if dept_sals and all_sals:
                dept_avg = sum(dept_sals) / len(dept_sals)
                all_avg = sum(all_sals) / len(all_sals)
                deviation = round((dept_avg / all_avg - 1) * 100)
                row.append(f"{'+' if deviation >= 0 else ''}{deviation}%")
            else:
                row.append(None)
        results['deviation_matrix']['values'].append(row)

    # Dispersion by grade
    for grade in grades:
        sals = grade_salaries.get(grade, [])
        if len(sals) >= 2:
            mean = sum(sals) / len(sals)
            stdev = statistics.stdev(sals)
            coeff = round(stdev / mean, 2) if mean > 0 else 0
            range_ratio = round(max(sals) / min(sals), 1) if min(sals) > 0 else 0
            status = 'high' if coeff > 0.3 else 'normal'
            results['dispersion'].append({
                'grade': grade, 'coefficient': coeff,
                'range_ratio': range_ratio, 'status': status
            })

    return results
