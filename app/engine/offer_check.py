"""
候选人定薪建议 engine。
基于市场数据 + 内部同级别数据给出建议薪资范围。
"""
from app.services.market_data import lookup_market_salary
from app.engine.common import calculate_percentile_position


def analyze(data_snapshot=None, params=None):
    """
    params: {
        'job_title': '高级前端工程师',
        'grade': 'L5',            # 公司职级
        'city': '深圳',           # 可选
        'candidate_ask': 35000,   # 可选
    }
    """
    params = params or {}
    job_title = (params.get('job_title') or '').strip()
    grade = str(params.get('grade') or '').strip()
    city = params.get('city') or '全国'
    candidate_ask = params.get('candidate_ask')

    if not job_title or not grade:
        return {'error': '需要 job_title 和 grade'}

    # 简单推断 hay_grade（后续可接标准职级映射表）
    hay_grade = _guess_hay_grade(grade)
    # 简单推断 job_function（从岗位名中提取关键词）
    job_function = _guess_function(job_title)

    market = None
    if hay_grade and job_function:
        market = lookup_market_salary(job_function, hay_grade)

    if not market:
        return {'error': f'未找到 {job_function or job_title} + Hay{hay_grade or "?"} 的市场数据'}

    market_info = {
        'function': job_function,
        'standard_grade': market.get('level'),
        'city': city,
        'p25': market['base_p25'],
        'p50': market['base_p50'],
        'p75': market['base_p75'],
    }

    # 内部对比（如果有 data_snapshot）
    internal_info = None
    if isinstance(data_snapshot, dict):
        emps = data_snapshot.get('employees') or []
        same_grade = [e for e in emps if str(e.get('grade', '')) == grade]
        if same_grade:
            sals = sorted([e.get('base_monthly', 0) or 0 for e in same_grade if e.get('base_monthly')])
            if sals:
                internal_info = {
                    'same_grade_median': sals[len(sals) // 2],
                    'same_grade_range': [sals[0], sals[-1]],
                    'headcount': len(sals),
                }

    result = {
        'market': market_info,
        'internal': internal_info,
    }

    if candidate_ask:
        market_pct = calculate_percentile_position(
            candidate_ask, market['base_p25'], market['base_p50'], market['base_p75']
        )
        internal_pct = None
        if internal_info:
            med = internal_info['same_grade_median']
            internal_pct = round(candidate_ask / med * 100) if med > 0 else None

        # 推荐薪酬范围：P25 ~ P75，结合内部情况
        suggested_low = market['base_p25']
        suggested_high = market['base_p75']
        if internal_info and internal_info['same_grade_range'][1]:
            # 上限不超过同级最高
            suggested_high = min(suggested_high, int(internal_info['same_grade_range'][1] * 1.1))

        rationale = _build_rationale(candidate_ask, market, internal_info)

        result['candidate'] = {
            'ask': candidate_ask,
            'market_percentile': market_pct,
            'internal_percentile': internal_pct,
        }
        result['recommendation'] = {
            'suggested_range': [suggested_low, suggested_high],
            'rationale': rationale,
        }

    return result


def _guess_hay_grade(company_grade: str):
    """L3→12，L4→14，L5→16，L6→18，L7→20 简单映射"""
    mp = {'L1': 8, 'L2': 10, 'L3': 12, 'L4': 14, 'L5': 16, 'L6': 18, 'L7': 20}
    return mp.get(company_grade.upper())


def _guess_function(job_title: str):
    """从岗位名提取标准职能"""
    title = job_title.lower()
    if any(k in title for k in ['前端', '后端', '开发', 'engineer', '工程师']):
        return '软件开发'
    if 'hrbp' in title or 'hr bp' in title:
        return 'HRBP'
    if '招聘' in title or 'recruit' in title:
        return '招聘'
    if '薪酬' in title or 'comp' in title:
        return '薪酬管理'
    if '绩效' in title:
        return '绩效管理'
    if '人才发展' in title or 'td' in title:
        return '人才发展'
    return None


def _build_rationale(ask, market, internal):
    if ask < market['base_p25']:
        return '候选人期望低于市场 P25，给到 P25-P50 即可吸引'
    if ask > market['base_p75']:
        return '候选人期望超过市场 P75，建议评估其经验是否匹配，或议价下调'
    if internal and ask > internal['same_grade_range'][1]:
        return '市场合理，但高于同级最高薪，需评估是否会造成内部倒挂'
    return '市场 P25-P75 之间，薪资范围合理'
