"""
从 static/ 目录加载市场薪酬数据。启动时加载一次，缓存在内存中。
"""
import openpyxl
import os

_cache = {}


def _get_static_path(filename):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', filename)


def get_market_data():
    """加载市场薪酬数据，返回按 (job_function, hay_grade) 索引的字典。
    用 iter_rows 单遍流式读取——之前 ws.cell(r,c) 在 read_only 模式下每次都从头
    迭代 worksheet，O(N²×M) 复杂度，5000 行 × 20 列要 30s+ 直接把 gunicorn 撑超时。
    """
    if 'market_index' in _cache:
        return _cache['market_index']

    path = _get_static_path('市场薪酬数据.xlsx')
    if not os.path.exists(path):
        _cache['market_index'] = {}
        return {}

    import time
    t0 = time.monotonic()

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)
    try:
        first = next(rows_iter)
    except StopIteration:
        wb.close()
        _cache['market_index'] = {}
        return {}
    headers = [str(h).strip() if h is not None else '' for h in first]

    index = {}
    for row_values in rows_iter:
        row = {h: v for h, v in zip(headers, row_values) if h}

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
    print(f'[market_data] loaded {len(index)} rows in {time.monotonic() - t0:.2f}s')
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
