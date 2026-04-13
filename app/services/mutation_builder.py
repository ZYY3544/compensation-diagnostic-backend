"""
代码驱动的 mutation 生成器：
- 高置信度：用公式算出 new_value
- 低置信度：只标记，new_value=None
- 输出 mutations 列表 + summary_text（供 AI 写文案用）
"""
import statistics


# ======================================================================
# 绩效映射表
# ======================================================================
STANDARD_GRADES = {'A', 'B+', 'B', 'B-', 'C'}

_PERF_MAPPINGS = [
    # 3.25-3.75 制
    {'3.75': 'A', '3.5': 'B+', '3.25': 'B', '3.0': 'B-', '2.75': 'C'},
    # 1-5 制
    {'5': 'A', '4': 'B+', '3': 'B', '2': 'B-', '1': 'C',
     '5.0': 'A', '4.0': 'B+', '3.0': 'B', '2.0': 'B-', '1.0': 'C'},
    # 描述制
    {'优秀': 'A', '优': 'A', '良好': 'B+', '良': 'B+',
     '合格': 'B', '称职': 'B', '中': 'B',
     '待改进': 'B-', '基本合格': 'B-',
     '不合格': 'C', '差': 'C', '不称职': 'C'},
    # 字母制
    {'S': 'A', 'A+': 'A', 'A': 'A', 'B+': 'B+', 'B': 'B', 'B-': 'B-',
     'C': 'C', 'C+': 'B-', 'D': 'C'},
]

# 城市别名
_CITY_ALIASES = {
    'bj': '北京', 'beijing': '北京', '帝都': '北京', '北京市': '北京',
    'sh': '上海', 'shanghai': '上海', '魔都': '上海', '上海市': '上海',
    'gz': '广州', 'guangzhou': '广州', '广州市': '广州',
    'sz': '深圳', 'shenzhen': '深圳', '深圳市': '深圳',
    'cd': '成都', 'chengdu': '成都', '成都市': '成都',
    'hz': '杭州', 'hangzhou': '杭州', '杭州市': '杭州',
    'nj': '南京', 'nanjing': '南京', '南京市': '南京',
    'wh': '武汉', 'wuhan': '武汉', '武汉市': '武汉',
    'xm': '厦门', 'xiamen': '厦门', '厦门市': '厦门',
}


def build_mutations_from_code(
    code_results: dict,
    employees: list,
    field_map: dict,
) -> tuple[list[dict], str]:
    """
    代码层生成全部 mutation。
    返回 (mutations, summary_text)。
    """
    mutations = []
    summary_lines = []
    mut_id = 0

    def next_id():
        nonlocal mut_id
        mut_id += 1
        return mut_id

    # --- 高置信度 ---

    # 1. 年终奖年化
    for item in (code_results.get('needs_annualize') or []):
        emp = _find_emp(employees, item['row_number'])
        if not emp:
            continue
        old = emp['variable_bonus']
        months = item.get('months_worked', 1)
        new = round(old / max(months, 1) * 12, 2)
        mutations.append({
            'id': next_id(), 'row_number': item['row_number'],
            'field': 'variable_bonus', 'old_value': old, 'new_value': new,
            'type': 'annualize_bonus', 'confidence': 'high',
            'auto_applied': True, 'reverted': False, 'description': '',
            'context': f"入司{item.get('join_date','')}，在职约{months}个月",
        })
    annualize_count = sum(1 for m in mutations if m['type'] == 'annualize_bonus')
    if annualize_count:
        rows = [m['row_number'] for m in mutations if m['type'] == 'annualize_bonus']
        summary_lines.append(f"年化处理: {annualize_count}名员工入司不满一年，年终奖已按在职月数年化。行号: {rows}")

    # 2. 13薪重分类
    for item in (code_results.get('possible_13th_overlap') or []):
        emp = _find_emp(employees, item['row_number'])
        if not emp:
            continue
        monthly = item.get('monthly_salary', 0)
        if not monthly:
            continue
        old_fixed = emp['fixed_bonus']
        new_fixed = round(old_fixed + monthly, 2)
        mutations.append({
            'id': next_id(), 'row_number': item['row_number'],
            'field': 'fixed_bonus', 'old_value': old_fixed, 'new_value': new_fixed,
            'type': 'reclassify_13th', 'confidence': 'high',
            'auto_applied': True, 'reverted': False, 'description': '',
            'context': f"年终奖含1个月工资{monthly}，已拆分到固定薪酬",
        })
    reclassify_count = sum(1 for m in mutations if m['type'] == 'reclassify_13th')
    if reclassify_count:
        summary_lines.append(f"13薪重分类: {reclassify_count}名员工的13薪已从年终奖拆分到固定薪酬。")

    # 3. 绩效标准化
    perf_values = code_results.get('performance_values', [])
    non_standard = [v for v in perf_values if v not in STANDARD_GRADES]
    if non_standard:
        mapping = _detect_perf_mapping(perf_values)
        if mapping:
            perf_count = 0
            for emp in employees:
                perf = str(emp.get('performance', '')).strip()
                if perf in mapping and mapping[perf] != perf:
                    mutations.append({
                        'id': next_id(), 'row_number': emp['row_number'],
                        'field': 'performance', 'old_value': perf, 'new_value': mapping[perf],
                        'type': 'standardize_performance', 'confidence': 'high',
                        'auto_applied': True, 'reverted': False, 'description': '',
                        'context': f"{perf} → {mapping[perf]}",
                    })
                    perf_count += 1
            if perf_count:
                mapping_desc = ', '.join(f'{k}→{v}' for k, v in mapping.items() if k in non_standard)
                summary_lines.append(f"绩效标准化: {perf_count}名员工的绩效已映射到标准五档。规则: {mapping_desc}")

    # 4. 部门归并
    dept_merge = _detect_merge_groups([emp['department'] for emp in employees if emp.get('department')])
    if dept_merge:
        dept_count = 0
        for emp in employees:
            dept = emp.get('department', '')
            if dept in dept_merge:
                mutations.append({
                    'id': next_id(), 'row_number': emp['row_number'],
                    'field': 'department', 'old_value': dept, 'new_value': dept_merge[dept],
                    'type': 'merge_department', 'confidence': 'high',
                    'auto_applied': True, 'reverted': False, 'description': '',
                    'context': f"{dept} → {dept_merge[dept]}",
                })
                dept_count += 1
        if dept_count:
            groups_desc = ', '.join(f'{k}→{v}' for k, v in dept_merge.items())
            summary_lines.append(f"部门归并: {groups_desc}")

    # 5. 城市归并
    city_merge = _detect_city_merge([emp.get('city', '') for emp in employees if emp.get('city')])
    if city_merge:
        city_count = 0
        for emp in employees:
            city = emp.get('city', '')
            if city in city_merge:
                mutations.append({
                    'id': next_id(), 'row_number': emp['row_number'],
                    'field': 'city', 'old_value': city, 'new_value': city_merge[city],
                    'type': 'merge_city', 'confidence': 'high',
                    'auto_applied': True, 'reverted': False, 'description': '',
                    'context': f"{city} → {city_merge[city]}",
                })
                city_count += 1
        if city_count:
            summary_lines.append(f"城市归并: {city_count}条记录城市名已标准化")

    # --- 低置信度（仅标记）---

    for item in (code_results.get('salary_outliers') or []):
        mutations.append({
            'id': next_id(), 'row_number': item['row_number'],
            'field': 'base_annual', 'old_value': item['value'], 'new_value': None,
            'type': 'extreme_value_salary', 'confidence': 'low',
            'auto_applied': False, 'reverted': False, 'description': '',
            'context': f"月薪{item['value']}偏离同级({item.get('grade','')})中位值{item.get('median',0):.0f}，比值={item.get('ratio',0):.1f}",
        })
    sal_outlier_count = sum(1 for m in mutations if m['type'] == 'extreme_value_salary')
    if sal_outlier_count:
        summary_lines.append(f"标记: {sal_outlier_count}项月薪异常值需人工确认")

    for item in (code_results.get('bonus_outliers') or []):
        mutations.append({
            'id': next_id(), 'row_number': item['row_number'],
            'field': 'variable_bonus', 'old_value': item['value'], 'new_value': None,
            'type': 'extreme_value_bonus', 'confidence': 'low',
            'auto_applied': False, 'reverted': False, 'description': '',
            'context': f"年终奖{item['value']}偏离同级中位值{item.get('median',0):.0f}",
        })

    for item in (code_results.get('salary_inversions') or []):
        mutations.append({
            'id': next_id(), 'row_number': item['row_number'],
            'field': 'base_annual', 'old_value': item['value'], 'new_value': None,
            'type': 'salary_inversion', 'confidence': 'low',
            'auto_applied': False, 'reverted': False, 'description': '',
            'context': item.get('issue', ''),
        })

    for item in (code_results.get('future_dates') or []) + (code_results.get('old_dates') or []):
        mutations.append({
            'id': next_id(), 'row_number': item['row_number'],
            'field': 'hire_date', 'old_value': str(item.get('value', '')), 'new_value': None,
            'type': 'date_anomaly', 'confidence': 'low',
            'auto_applied': False, 'reverted': False, 'description': '',
            'context': item.get('issue', ''),
        })

    for item in (code_results.get('allowance_alerts') or []):
        mutations.append({
            'id': next_id(), 'row_number': item['row_number'],
            'field': 'cash_allowance', 'old_value': item.get('value'), 'new_value': None,
            'type': 'extreme_value_allowance', 'confidence': 'low',
            'auto_applied': False, 'reverted': False, 'description': '',
            'context': item.get('issue', ''),
        })

    low_count = sum(1 for m in mutations if m['confidence'] == 'low')
    if low_count:
        summary_lines.append(f"共标记 {low_count} 项低置信度问题需人工确认")

    high_count = sum(1 for m in mutations if m['confidence'] == 'high')
    summary = f"共 {high_count} 项自动修正，{low_count} 项需人工确认。" + ' '.join(summary_lines)

    return mutations, summary


# ======================================================================
# 内部辅助
# ======================================================================

def _find_emp(employees, row_number):
    for emp in employees:
        if emp.get('row_number') == row_number:
            return emp
    return None


def _detect_perf_mapping(perf_values):
    """检测绩效体系，返回映射表或 None"""
    if all(v in STANDARD_GRADES for v in perf_values):
        return None
    best, best_cov = None, 0
    for mapping in _PERF_MAPPINGS:
        covered = sum(1 for v in perf_values if v in mapping)
        cov = covered / len(perf_values) if perf_values else 0
        if cov > best_cov:
            best_cov = cov
            best = mapping
    return best if best_cov >= 0.5 else None


def _detect_merge_groups(names):
    """检测同名变体，返回 {变体: 标准名}"""
    if not names:
        return {}
    freq = {}
    for n in names:
        freq[n] = freq.get(n, 0) + 1
    unique = list(freq.keys())
    if len(unique) <= 1:
        return {}
    groups = []
    for name in unique:
        matched = False
        for group in groups:
            for existing in group:
                if _similar(name, existing):
                    group.add(name)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            groups.append({name})
    merge = {}
    for group in groups:
        if len(group) <= 1:
            continue
        canonical = max(group, key=lambda n: freq[n])
        for name in group:
            if name != canonical:
                merge[name] = canonical
    return merge


def _similar(a, b):
    if a in b or b in a:
        return True
    a_bi = set(a[i:i+2] for i in range(len(a)-1))
    b_bi = set(b[i:i+2] for i in range(len(b)-1))
    if not a_bi or not b_bi:
        return False
    return len(a_bi & b_bi) / len(a_bi | b_bi) > 0.6


def _detect_city_merge(cities):
    """城市名标准化"""
    if not cities:
        return {}
    merge = {}
    for city in set(cities):
        normalized = _CITY_ALIASES.get(city.lower().strip(), None)
        if normalized and normalized != city:
            merge[city] = normalized
        elif city.endswith('市') and len(city) > 2:
            merge[city] = city[:-1]
    return merge
