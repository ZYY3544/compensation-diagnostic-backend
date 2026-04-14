"""
市场薪酬查询（轻模式）：
根据职能 + Hay 职级 查询市场薪酬。
"""
from app.services.market_data import lookup_market_salary, get_all_job_functions


def run(employees: list, params: dict) -> dict:
    """
    params: {
      'job_function': 'HRBP',
      'hay_grade': 14,
    }
    """
    jf = params.get('job_function', '').strip()
    hg = params.get('hay_grade')

    if not jf:
        return {
            'error': 'missing_function',
            'available_functions': get_all_job_functions()[:20],
        }

    if not hg:
        return {'error': 'missing_hay_grade', 'job_function': jf}

    market = lookup_market_salary(jf, int(hg))
    if not market:
        return {'error': f'市场数据未覆盖 {jf} Hay{hg}', 'job_function': jf, 'hay_grade': hg}

    return {
        'job_function': jf,
        'hay_grade': hg,
        'level': market.get('level', ''),
        'base': {
            'p25': market['base_p25'],
            'p50': market['base_p50'],
            'p75': market['base_p75'],
        },
        'bonus': {
            'p25': market['bonus_p25'],
            'p50': market['bonus_p50'],
            'p75': market['bonus_p75'],
        },
        'ttc': {
            'p25': market['ttc_p25'],
            'p50': market['ttc_p50'],
            'p75': market['ttc_p75'],
        },
    }
