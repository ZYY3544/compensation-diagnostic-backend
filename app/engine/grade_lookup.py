"""
市场薪酬查询 engine。根据 职能 + 职级 + 城市 查询市场分位值。
"""
from app.services.market_data import lookup_market_salary, get_all_job_functions


def query(data_snapshot=None, params=None):
    """
    params: {'function': '软件开发', 'grade': 'L5', 'city': '深圳'}
    """
    params = params or {}
    func = (params.get('function') or '').strip()
    grade = str(params.get('grade') or '').strip()
    city = params.get('city') or '全国'

    if not func:
        return {
            'error': 'missing_function',
            'available_functions': get_all_job_functions()[:20],
        }
    if not grade:
        return {'error': 'missing_grade', 'function': func}

    hay = _guess_hay_grade(grade)
    if not hay:
        return {'error': f'无法识别职级 {grade}'}

    market = lookup_market_salary(func, hay)
    if not market:
        return {'error': f'市场数据未覆盖 {func} Hay{hay}', 'function': func, 'grade': grade}

    return {
        'lookup': {
            'function': func,
            'standard_grade': market.get('level'),
            'city': city,
            # 市场数据里只有 p25/p50/p75，这里补充 p10/p90 用线性外推
            'p10': round(market['base_p25'] * 0.85),
            'p25': market['base_p25'],
            'p50': market['base_p50'],
            'p75': market['base_p75'],
            'p90': round(market['base_p75'] * 1.15),
            'sample_size': None,
            'data_period': '2025',
        },
    }


def _guess_hay_grade(grade: str):
    mp = {'L1': 8, 'L2': 10, 'L3': 12, 'L4': 14, 'L5': 16, 'L6': 18, 'L7': 20}
    return mp.get(grade.upper())
