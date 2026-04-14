"""
候选人定薪建议（轻模式）：
输入：职级 + 职能 + 期望月薪（可选）
输出：市场 P25/P50/P75 对比 + 建议薪酬范围
"""
from app.services.market_data import lookup_market_salary
from app.engine.common import calculate_percentile_position


def run(employees: list, params: dict) -> dict:
    """
    params: {
      'job_function': 'HRBP',
      'hay_grade': 14,
      'expected_monthly': 18000,  # 可选
    }
    不依赖员工数据（candidate 是新人）。
    """
    jf = params.get('job_function', '').strip()
    hg = params.get('hay_grade')
    expected = params.get('expected_monthly', 0)

    if not jf or not hg:
        return {'error': '需要职能 + Hay 职级才能定薪'}

    market = lookup_market_salary(jf, int(hg))
    if not market:
        return {'error': f'市场数据未覆盖 {jf} Hay{hg}'}

    p25 = market['base_p25']
    p50 = market['base_p50']
    p75 = market['base_p75']

    result = {
        'job_function': jf,
        'hay_grade': hg,
        'level': market.get('level', ''),
        'market_p25': p25,
        'market_p50': p50,
        'market_p75': p75,
        'recommended_range': {'low': p25, 'target': p50, 'high': p75},
    }

    if expected:
        pct = calculate_percentile_position(expected, p25, p50, p75)
        result['expected_monthly'] = expected
        result['expected_percentile'] = pct
        if expected < p25:
            result['suggestion'] = 'low'  # 期望偏低，容易签到人
            result['suggestion_text'] = f'候选人期望 {expected} 低于市场 P25，给到 {p25}-{p50} 之间即可吸引人选'
        elif expected <= p50:
            result['suggestion'] = 'ok'
            result['suggestion_text'] = f'候选人期望在市场 P25-P50 之间，接近 {p50} 定薪比较合理'
        elif expected <= p75:
            result['suggestion'] = 'high'
            result['suggestion_text'] = f'候选人期望在 P50-P75 之间，需要评估其经验是否匹配'
        else:
            result['suggestion'] = 'too_high'
            result['suggestion_text'] = f'候选人期望超过市场 P75，建议评估核心岗位或议价下调'

    return result
