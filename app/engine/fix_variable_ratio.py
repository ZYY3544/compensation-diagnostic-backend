def analyze(employees):
    """
    薪酬固浮比分析
    - 按职级计算固定/浮动薪酬比例
    """
    from collections import defaultdict

    results = {'pay_mix': [], 'comparison': []}

    grade_data = defaultdict(lambda: {'fixed': [], 'variable': []})
    for emp in employees:
        if emp.get('grade') and emp.get('base_monthly') and emp.get('annual_bonus') is not None:
            annual_fixed = emp['base_monthly'] * 12
            variable = emp.get('annual_bonus', 0)
            grade_data[emp['grade']]['fixed'].append(annual_fixed)
            grade_data[emp['grade']]['variable'].append(variable)

    market_ref = {'Level2': 80, 'Level3': 80, 'Level4': 75, 'Level5': 70, 'Level6': 65, 'Level7': 60}

    for grade in sorted(grade_data.keys()):
        d = grade_data[grade]
        avg_fixed = int(sum(d['fixed']) / len(d['fixed']))
        avg_var = int(sum(d['variable']) / len(d['variable']))
        total = avg_fixed + avg_var
        fix_ratio = round(avg_fixed / total * 100) if total > 0 else 0

        results['pay_mix'].append({
            'grade': grade, 'fixed': avg_fixed, 'variable': avg_var
        })

        # Extract level number for market reference
        level_key = grade.split('-')[0] if '-' in grade else grade
        market_fix = market_ref.get(level_key, 75)

        diff = '接近' if abs(fix_ratio - market_fix) <= 5 else ('固定偏高' if fix_ratio > market_fix else '固定偏低')
        results['comparison'].append({
            'grade': grade, 'company': f'{fix_ratio}:{100 - fix_ratio}',
            'market': f'{market_fix}:{100 - market_fix}', 'diff': diff
        })

    return results
