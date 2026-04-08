"""
从 static/ 目录加载 OrgChart、市场薪酬数据、层级定义。
启动时加载一次，缓存在内存中。
"""

import openpyxl
import os

_cache = {}


def _get_static_path(filename):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', filename)


def get_orgchart():
    """加载 OrgChart，返回结构化数据"""
    if 'orgchart' in _cache:
        return _cache['orgchart']

    wb = openpyxl.load_workbook(_get_static_path('Orgchart.xlsx'), read_only=True)
    ws = wb.active

    # 读取 Job Functions (row 2, columns 5+)
    job_functions = []
    for c in range(5, ws.max_column + 1):
        val = ws.cell(row=2, column=c).value
        if val:
            job_functions.append(val)

    # 读取岗位矩阵
    positions = []
    for r in range(4, ws.max_row + 1):
        hay = ws.cell(row=r, column=1).value
        level = ws.cell(row=r, column=2).value
        pro_title = ws.cell(row=r, column=3).value
        mgmt_title = ws.cell(row=r, column=4).value
        if not hay:
            continue

        for c_idx, func in enumerate(job_functions):
            col = c_idx + 5
            pos_name = ws.cell(row=r, column=col).value
            if pos_name:
                positions.append({
                    'job_family': '人力资源',
                    'job_function': func,
                    'position_name': pos_name,
                    'hay_grade': int(hay),
                    'level': level,
                    'pro_title': pro_title,
                    'mgmt_title': mgmt_title,
                })

    wb.close()
    result = {
        'job_family': '人力资源',
        'job_functions': job_functions,
        'positions': positions,
    }
    _cache['orgchart'] = result
    return result


def get_market_data():
    """加载市场薪酬数据"""
    if 'market' in _cache:
        return _cache['market']

    wb = openpyxl.load_workbook(_get_static_path('市场薪酬数据.xlsx'), read_only=True)
    ws = wb.active

    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    data = []
    for r in range(2, ws.max_row + 1):
        row = {}
        for c, h in enumerate(headers, 1):
            row[h] = ws.cell(row=r, column=c).value
        if row.get('Hay职级'):
            data.append(row)

    wb.close()
    _cache['market'] = data
    return data


def get_level_definitions():
    """加载层级定义"""
    if 'levels' in _cache:
        return _cache['levels']

    wb = openpyxl.load_workbook(_get_static_path('层级定义.xlsx'), read_only=True)
    ws = wb.active

    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    levels = []
    for r in range(2, ws.max_row + 1):
        row = {}
        for c, h in enumerate(headers, 1):
            row[h] = ws.cell(row=r, column=c).value
        if row.get('层级'):
            levels.append(row)

    wb.close()
    _cache['levels'] = levels
    return levels


def lookup_market_salary(job_function, hay_grade):
    """查询特定职能+职级的市场薪酬数据"""
    market = get_market_data()
    for row in market:
        if row.get('Job Function') == job_function and row.get('Hay职级') == hay_grade:
            return {
                'base_p25': row.get('base_p25', 0),
                'base_p50': row.get('base_p50', 0),
                'base_p75': row.get('base_p75', 0),
                'bonus_p25': row.get('bonus_p25', 0),
                'bonus_p50': row.get('bonus_p50', 0),
                'bonus_p75': row.get('bonus_p75', 0),
                'ttc_p25': row.get('ttc_p25', 0),
                'ttc_p50': row.get('ttc_p50', 0),
                'ttc_p75': row.get('ttc_p75', 0),
            }
    return None


def get_job_function_list():
    """获取所有 Job Function 名称列表（供 MatchingAgent 使用）"""
    oc = get_orgchart()
    return oc['job_functions']


def get_level_list():
    """获取层级列表和定义（供 MatchingAgent 使用）"""
    levels = get_level_definitions()
    return [{'level': l['层级'], 'hay_range': l['Hay职级范围'],
             'pro_title': l.get('专业通道Title', ''),
             'mgmt_title': l.get('管理通道Title', ''),
             'description': l['层级定义描述']} for l in levels]
