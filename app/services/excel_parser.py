import openpyxl
from io import BytesIO

def parse_excel(file_path):
    """Parse uploaded Excel file"""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

    result = {
        'sheet1_data': [],  # Employee data
        'sheet2_data': {},  # Company data
        'column_names': [],
    }

    # Parse Sheet 1 (Employee data)
    if len(wb.sheetnames) >= 1:
        ws1 = wb[wb.sheetnames[0]]
        rows = list(ws1.iter_rows(values_only=True))
        if rows:
            result['column_names'] = [str(c) if c else f'Column_{i}' for i, c in enumerate(rows[0])]
            for i, row in enumerate(rows[1:], start=2):
                row_data = {}
                for j, val in enumerate(row):
                    if j < len(result['column_names']):
                        row_data[result['column_names'][j]] = val
                result['sheet1_data'].append({
                    'row_number': i,
                    'data': row_data
                })

    # Parse Sheet 2 (Company data) if exists
    if len(wb.sheetnames) >= 2:
        ws2 = wb[wb.sheetnames[1]]
        for row in ws2.iter_rows(values_only=True):
            if row and len(row) >= 2 and row[0]:
                result['sheet2_data'][str(row[0])] = row[1]

    wb.close()
    return result
