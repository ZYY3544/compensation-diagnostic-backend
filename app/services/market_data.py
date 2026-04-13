"""
从 static/ 目录加载市场薪酬数据。启动时加载一次，缓存在内存中。
"""
import openpyxl
import os

_cache = {}


def _get_static_path(filename):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', filename)


def get_market_data():
    """加载市场薪酬数据，返回按 (job_function, hay_grade) 索引的字典"""
    if 'market_index' in _cache:
        return _cache['market_index']

    path = _get_static_path('市场薪酬数据.xlsx')
    if not os.path.exists(path):
        _cache['market_index'] = {}
        return {}

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    index = {}
    for r in range(2, ws.max_row + 1):
        row = {}
        for c, h in enumerate(headers, 1):
            if h:
                row[h.strip()] = ws.cell(row=r, column=c).value

        job_func = str(row.get('Job Function', '')).strip()
        hay = row.get('Hay职级')
        if not job_func or hay is None:
            continue

        key = (job_func, int(hay))
        index[key] = {
            'job_family': str(row.get('Job Family', '')).strip(),
            'job_function': job_func,
            'hay_grade': int(hay),
            'level': str(row.get('层级', '')).strip(),
            'base_p25': _safe_int(row.get('base_p25')),
            'base_p50': _safe_int(row.get('base_p50')),
            'base_p75': _safe_int(row.get('base_p75')),
            'bonus_p25': _safe_int(row.get('bonus_p25')),
            'bonus_p50': _safe_int(row.get('bonus_p50')),
            'bonus_p75': _safe_int(row.get('bonus_p75')),
            'ttc_p25': _safe_int(row.get('ttc_p25')),
            'ttc_p50': _safe_int(row.get('ttc_p50')),
            'ttc_p75': _safe_int(row.get('ttc_p75')),
        }

    wb.close()
    _cache['market_index'] = index
    return index


def lookup_market_salary(job_function: str, hay_grade: int) -> dict | None:
    """查询特定职能+Hay职级的市场薪酬数据"""
    index = get_market_data()
    return index.get((job_function, hay_grade))


def get_all_job_functions() -> list[str]:
    """获取市场数据中所有 Job Function 名称"""
    index = get_market_data()
    return sorted(set(v['job_function'] for v in index.values()))


def _safe_int(val) -> int:
    if val is None:
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0
