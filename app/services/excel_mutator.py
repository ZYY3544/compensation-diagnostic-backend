"""
在 Excel 副本上执行修改 + 标记（黄色底色 + 批注）。
"""
import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.comments import Comment

HIGHLIGHT_FILL = PatternFill(start_color='FFFFCC00', end_color='FFFFCC00', fill_type='solid')  # 黄色：已修正
WARNING_FILL = PatternFill(start_color='FFFDE68A', end_color='FFFDE68A', fill_type='solid')   # 浅黄：需确认
REVERTED_FILL = PatternFill(start_color='FFCCCCCC', end_color='FFCCCCCC', fill_type='solid')   # 灰色：已撤回


# employee dict key → field_map key（两套命名不一致的地方）
_FIELD_ALIASES = {
    'base_annual': 'base_salary',
    'base_monthly': 'base_salary',
}


def _col_index(field: str, field_map: dict, column_names: list) -> int:
    """标准字段名 → Excel 列号（1-based）。找不到返回 -1。"""
    mapped = _FIELD_ALIASES.get(field, field)
    col_name = field_map.get(mapped)
    if col_name and col_name in column_names:
        return column_names.index(col_name) + 1
    return -1


def create_marked_excel(
    source_path: str,
    output_path: str,
    mutations: list,
    field_map: dict,
    column_names: list,
) -> str:
    """
    复制原始 Excel，对每条 mutation 标记对应单元格。
    - 已修正（有 new_value）：改值 + 黄色底色 + 批注
    - 需确认（new_value=None）：不改值 + 浅黄底色 + 批注
    """
    wb = openpyxl.load_workbook(source_path)
    ws = wb.active

    marked_count = 0
    for m in mutations:
        if m.get('reverted'):
            continue
        col_idx = _col_index(m['field'], field_map, column_names)
        if col_idx < 0:
            print(f'[ExcelMutator] field "{m["field"]}" not found in field_map, skipping row {m.get("row_number")}')
            continue
        row = m['row_number']
        cell = ws.cell(row=row, column=col_idx)
        old_val = cell.value

        if m.get('new_value') is not None:
            # 已修正：改值 + 黄色
            cell.value = m['new_value']
            cell.fill = HIGHLIGHT_FILL
            cell.comment = Comment(
                f"Sparky 已修正\n原始值: {old_val}\n{m.get('description', '')}",
                'Sparky'
            )
        else:
            # 需确认：不改值 + 浅黄标记
            cell.fill = WARNING_FILL
            cell.comment = Comment(
                f"Sparky 标记：需确认\n{m.get('description', '')}",
                'Sparky'
            )
        marked_count += 1

    print(f'[ExcelMutator] marked {marked_count}/{len(mutations)} cells in {output_path}')
    wb.save(output_path)
    wb.close()
    return output_path


def update_cell_in_excel(
    excel_path: str,
    mutation: dict,
    field_map: dict,
    column_names: list,
    is_revert: bool,
) -> None:
    """单条 mutation 的增量更新：撤回恢复原始值 + 灰色，恢复则重新改值 + 黄色。"""
    col_idx = _col_index(mutation['field'], field_map, column_names)
    if col_idx < 0:
        return

    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    cell = ws.cell(row=mutation['row_number'], column=col_idx)

    if is_revert:
        cell.value = mutation['old_value']
        cell.fill = REVERTED_FILL
        cell.comment = Comment(f"已撤回\n原修正: {mutation.get('description', '')}", 'Sparky')
    else:
        cell.value = mutation['new_value']
        cell.fill = HIGHLIGHT_FILL
        cell.comment = Comment(
            f"Sparky 修正\n原始值: {mutation['old_value']}\n{mutation.get('description', '')}",
            'Sparky'
        )

    wb.save(excel_path)
    wb.close()
