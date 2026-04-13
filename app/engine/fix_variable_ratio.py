"""
模块三：薪酬结构（Pay Mix）分析
- 各部门/层级的固浮比
- 堆叠柱状图数据
"""
from collections import defaultdict
from app.engine.common import safe_mean


def analyze(employees):
    # 按职级分组
    grade_data = defaultdict(lambda: {'fixed': [], 'variable': [], 'tcc': []})
    dept_data = defaultdict(lambda: {'fixed': [], 'variable': [], 'tcc': []})

    for emp in employees:
        base = emp.get('base_monthly', 0) or 0
        fixed_bonus = emp.get('fixed_bonus', 0) or 0
        variable = emp.get('variable_bonus', 0) or 0
        annual_fixed = base * 12 + fixed_bonus
        tcc = annual_fixed + variable

        grade = emp.get('grade', '')
        dept = emp.get('department', '')

        if grade and base > 0:
            grade_data[grade]['fixed'].append(annual_fixed)
            grade_data[grade]['variable'].append(variable)
            grade_data[grade]['tcc'].append(tcc)

        if dept and base > 0:
            dept_data[dept]['fixed'].append(annual_fixed)
            dept_data[dept]['variable'].append(variable)
            dept_data[dept]['tcc'].append(tcc)

    # 按职级的固浮比
    pay_mix_by_grade = []
    for grade in sorted(grade_data.keys()):
        d = grade_data[grade]
        avg_fixed = round(safe_mean(d['fixed']))
        avg_var = round(safe_mean(d['variable']))
        total = avg_fixed + avg_var
        fix_pct = round(avg_fixed / total * 100) if total > 0 else 0
        var_pct = 100 - fix_pct
        pay_mix_by_grade.append({
            'grade': grade,
            'fixed': avg_fixed,
            'variable': avg_var,
            'total': total,
            'fix_pct': fix_pct,
            'var_pct': var_pct,
            'count': len(d['fixed']),
        })

    # 按部门的固浮比
    pay_mix_by_dept = []
    for dept in sorted(dept_data.keys()):
        d = dept_data[dept]
        avg_fixed = round(safe_mean(d['fixed']))
        avg_var = round(safe_mean(d['variable']))
        total = avg_fixed + avg_var
        fix_pct = round(avg_fixed / total * 100) if total > 0 else 0
        var_pct = 100 - fix_pct
        pay_mix_by_dept.append({
            'department': dept,
            'fixed': avg_fixed,
            'variable': avg_var,
            'total': total,
            'fix_pct': fix_pct,
            'var_pct': var_pct,
            'count': len(d['fixed']),
        })

    # 整体固浮比
    all_fixed = [e.get('base_monthly', 0) * 12 + (e.get('fixed_bonus', 0) or 0) for e in employees if e.get('base_monthly')]
    all_var = [e.get('variable_bonus', 0) or 0 for e in employees if e.get('base_monthly')]
    total_fixed = sum(all_fixed)
    total_var = sum(all_var)
    total_all = total_fixed + total_var
    overall_fix_pct = round(total_fixed / total_all * 100) if total_all > 0 else 0

    return {
        'pay_mix_by_grade': pay_mix_by_grade,
        'pay_mix_by_dept': pay_mix_by_dept,
        'overall_fix_pct': overall_fix_pct,
        'overall_var_pct': 100 - overall_fix_pct,
        'status': 'normal',
    }
