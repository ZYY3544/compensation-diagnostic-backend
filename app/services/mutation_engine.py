"""
数据修改引擎：在内存中执行/撤回结构化修改指令。
"""


def apply_mutations(employees: list, mutations: list, field_map: dict) -> list:
    """对 employees 执行所有 auto-applicable 的 mutation（原地修改）。返回已执行的 id 列表。"""
    applied = []
    for m in mutations:
        if m.get('reverted') or m.get('new_value') is None:
            continue
        emp = _find_employee(employees, m['row_number'])
        if not emp:
            continue
        field = m['field']
        if field in emp:
            m['old_value'] = emp[field]  # 确保 old_value 与实际一致
            emp[field] = m['new_value']
            m['auto_applied'] = True
            recompute_derived_fields(emp)
            applied.append(m['id'])
    return applied


def revert_mutation(employees: list, employees_original: list, mutations: list, mutation_id: int) -> None:
    """撤回一条 mutation：从原始快照重放该单元格所有未撤回的修改。"""
    target = next((m for m in mutations if m['id'] == mutation_id), None)
    if not target:
        return
    target['reverted'] = True
    _replay_cell(employees, employees_original, mutations, target['row_number'], target['field'])


def reapply_mutation(employees: list, employees_original: list, mutations: list, mutation_id: int) -> None:
    """恢复一条之前撤回的 mutation。"""
    target = next((m for m in mutations if m['id'] == mutation_id), None)
    if not target:
        return
    target['reverted'] = False
    _replay_cell(employees, employees_original, mutations, target['row_number'], target['field'])


def recompute_derived_fields(emp: dict) -> None:
    """重算派生字段：tcc / annual_bonus / base_monthly。"""
    base = emp.get('base_annual', 0) or 0
    fixed = emp.get('fixed_bonus', 0) or 0
    variable = emp.get('variable_bonus', 0) or 0
    cash = emp.get('cash_allowance', 0) or 0
    emp['tcc'] = base + fixed + variable + cash
    emp['annual_bonus'] = fixed + variable
    emp['base_monthly'] = base / 12 if base else 0


def validate_mutations(mutations: list, employees: list, field_map: dict) -> list:
    """过滤掉无效的 mutation（行号不存在、字段不存在等）。"""
    valid = []
    valid_fields = set(field_map.keys()) | {
        'base_annual', 'base_monthly', 'fixed_bonus', 'variable_bonus',
        'cash_allowance', 'reimbursement', 'tcc', 'annual_bonus',
        'performance', 'department', 'grade', 'job_title', 'hire_date',
    }
    for m in mutations:
        if not m.get('row_number') or not m.get('field'):
            continue
        if m['field'] not in valid_fields:
            continue
        emp = _find_employee(employees, m['row_number'])
        if not emp:
            continue
        valid.append(m)
    return valid


def _find_employee(employees: list, row_number: int):
    """按 row_number 查找 employee。"""
    for emp in employees:
        if emp.get('row_number') == row_number:
            return emp
    return None


def _replay_cell(employees, employees_original, mutations, row_number, field):
    """重置某个单元格到原始值，然后按顺序重放所有未撤回的 mutation。"""
    emp = _find_employee(employees, row_number)
    emp_orig = _find_employee(employees_original, row_number)
    if not emp or not emp_orig:
        return
    # 重置到原始值
    emp[field] = emp_orig.get(field)
    # 按 id 顺序重放未撤回的
    for m in sorted(mutations, key=lambda x: x['id']):
        if m['row_number'] == row_number and m['field'] == field and not m['reverted'] and m.get('new_value') is not None:
            emp[field] = m['new_value']
    recompute_derived_fields(emp)
