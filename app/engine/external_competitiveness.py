def analyze(employees, market_data_lookup):
    """
    外部竞争力分析
    - 计算每个员工的 CR 值 (actual_salary / market_p50)
    - 按职能分组计算平均 CR
    - 按部门×职级生成 CR 热力矩阵
    """
    from collections import defaultdict

    results = {
        'cr_by_function': [],
        'cr_heatmap': {
            'departments': [],
            'grades': [],
            'values': []
        }
    }

    # Calculate CR for each employee
    for emp in employees:
        market = market_data_lookup(emp.get('job_function'), emp.get('hay_grade'))
        if market and market['base_p50'] > 0:
            emp['cr'] = round(emp.get('base_monthly', 0) / market['base_p50'], 2)
        else:
            emp['cr'] = None

    # CR by function
    func_crs = defaultdict(list)
    for emp in employees:
        if emp.get('cr') and emp.get('job_function'):
            func_crs[emp['job_function']].append(emp['cr'])

    for func, crs in func_crs.items():
        results['cr_by_function'].append({
            'name': func,
            'cr': round(sum(crs) / len(crs), 2)
        })

    # CR heatmap (department x grade)
    departments = sorted(set(emp.get('department', '未知') for emp in employees if emp.get('department')))
    grades = sorted(set(emp.get('grade', '') for emp in employees if emp.get('grade')))

    results['cr_heatmap']['departments'] = departments
    results['cr_heatmap']['grades'] = grades

    dept_grade_crs = defaultdict(list)
    for emp in employees:
        if emp.get('cr') and emp.get('department') and emp.get('grade'):
            dept_grade_crs[(emp['department'], emp['grade'])].append(emp['cr'])

    for dept in departments:
        row = []
        for grade in grades:
            crs = dept_grade_crs.get((dept, grade), [])
            row.append(round(sum(crs) / len(crs), 2) if crs else None)
        results['cr_heatmap']['values'].append(row)

    return results
