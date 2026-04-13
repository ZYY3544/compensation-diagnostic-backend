"""
在 Excel 副本上执行修改 + 标记（黄色底色 + 批注）。
"""
import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.comments import Comment

HIGHLIGHT_FILL = PatternFill(start_color='FFFFCC00', end_color='FFFFCC00', fill_type='solid')
REVERTED_FILL = PatternFill(start_color='FFCCCCCC', end_color='FFCCCCCC', fill_type='solid')


def _col_index(field: str, field_map: dict, column_names: list) -> int:
    """标准字段名 → Excel 列号（1-based）。找不到返回 -1。"""
    col_name = field_map.get(field)
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
    复制原始 Excel，对每条 mutation 修改对应单元格的值 + 标黄 + 加批注。
    返回 output_path。
    """
    wb = openpyxl.load_workbook(source_path)
    ws = wb.active

    for m in mutations:
        if m.get('reverted') or m.get('new_value') is None:
            continue
        col_idx = _col_index(m['field'], field_map, column_names)
        if col_idx < 0:
            continue
        row = m['row_number']
        cell = ws.cell(row=row, column=col_idx)
        old_val = cell.value
        cell.value = m['new_value']
        cell.fill = HIGHLIGHT_FILL
        cell.comment = Comment(
            f"Sparky 修正\n原始值: {old_val}\n{m.get('description', '')}",
            'Sparky'
        )

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
