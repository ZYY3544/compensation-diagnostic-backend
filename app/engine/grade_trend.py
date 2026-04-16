"""
职级薪酬趋势计算：公司薪酬曲线 vs 市场 P25/P50/P75 曲线。
输出供前端画趋势图 + 代码生成 annotations / storyline。

市场分位线取法：同一 hay_grade 下所有 job_function 的分位值取中位数，
反映"该职级在市场上的整体水平"。
"""
import math
import statistics
from collections import defaultdict
from app.services.market_data import get_market_data


def compute_grade_trend(employees: list, salary_type: str = 'tcc',
                        use_standard_grade: bool = False) -> dict:
    """
    salary_type: 'tcc' (年度总现金) | 'base' (年度基本工资)
    use_standard_grade: True 则按 hay_grade 分组，False 用公司原始 grade
    """
    salary_key = 'tcc' if salary_type == 'tcc' else 'base_annual'

    # 按职级分组，收集每个职级的员工薪酬
    grade_salaries: dict[str, list[float]] = defaultdict(list)
    for emp in employees:
        grade = str(emp.get('hay_grade', '')) if use_standard_grade else str(emp.get('grade', ''))
        sal = emp.get(salary_key) or 0
        if not grade or sal <= 0:
            continue
        grade_salaries[grade].append(sal)

    if not grade_salaries:
        return _empty_result()

    # 排序职级（尝试数值排序，不行就字典序）
    grades = sorted(grade_salaries.keys(), key=_grade_sort_key)

    # 公司每个职级的中位值 + 人数
    company_medians = []
    company_counts = []
    for g in grades:
        vals = grade_salaries[g]
        company_medians.append(round(statistics.median(vals)))
        company_counts.append(len(vals))

    # 市场数据：同一 hay_grade 下所有 function 的 P25/P50/P75 取中位
    market_index = get_market_data()
    market_p25, market_p50, market_p75 = [], [], []
    market_grades_valid = []

    for i, g in enumerate(grades):
        hay = _to_hay_grade(g, employees, use_standard_grade)
        if hay is None:
            market_p25.append(None)
            market_p50.append(None)
            market_p75.append(None)
            continue

        p25s, p50s, p75s = [], [], []
        pkey = f'{salary_type}_p25' if salary_type == 'tcc' else 'base_p25'
        for (jf, hg), mkt in market_index.items():
            if hg != hay:
                continue
            if salary_type == 'tcc':
                p25s.append(mkt.get('ttc_p25', 0))
                p50s.append(mkt.get('ttc_p50', 0))
                p75s.append(mkt.get('ttc_p75', 0))
            else:
                p25s.append(mkt.get('base_p25', 0))
                p50s.append(mkt.get('base_p50', 0))
                p75s.append(mkt.get('base_p75', 0))

        p25s = [v for v in p25s if v > 0]
        p50s = [v for v in p50s if v > 0]
        p75s = [v for v in p75s if v > 0]

        market_p25.append(round(statistics.median(p25s)) if p25s else None)
        market_p50.append(round(statistics.median(p50s)) if p50s else None)
        market_p75.append(round(statistics.median(p75s)) if p75s else None)
        if p50s:
            market_grades_valid.append(i)

    # 趋势线：指数回归 log(y) = a + b*x
    x_seq = list(range(len(grades)))
    company_trend = _exp_regression(x_seq, company_medians)
    market_p25_trend = _exp_regression(x_seq, market_p25)
    market_p50_trend = _exp_regression(x_seq, market_p50)
    market_p75_trend = _exp_regression(x_seq, market_p75)

    # 代码生成 annotations
    annotations = _compute_annotations(grades, company_medians, market_p25, market_p50, market_p75)

    # 代码生成 storyline
    storyline = _compute_storyline(grades, company_medians, market_p50, annotations)

    return {
        'grades': grades,
        'company_counts': company_counts,
        'company_actual': company_medians,
        'company_trendline': company_trend,
        'market_p25_actual': market_p25,
        'market_p25_trendline': market_p25_trend,
        'market_p50_actual': market_p50,
        'market_p50_trendline': market_p50_trend,
        'market_p75_actual': market_p75,
        'market_p75_trendline': market_p75_trend,
        'annotations': annotations,
        'storyline': storyline,
        'salary_type': salary_type,
        'use_standard_grade': use_standard_grade,
    }


# ======================================================================
# 辅助
# ======================================================================

def _empty_result():
    return {
        'grades': [], 'company_counts': [],
        'company_actual': [], 'company_trendline': [],
        'market_p25_actual': [], 'market_p25_trendline': [],
        'market_p50_actual': [], 'market_p50_trendline': [],
        'market_p75_actual': [], 'market_p75_trendline': [],
        'annotations': [], 'storyline': '',
        'salary_type': 'tcc', 'use_standard_grade': False,
    }


def _grade_sort_key(g: str):
    """尝试提取数字做排序；不行就字典序"""
    import re
    nums = re.findall(r'\d+', g)
    if nums:
        return (0, int(nums[0]), g)
    return (1, 0, g)


def _to_hay_grade(grade_str: str, employees: list, use_standard: bool) -> int | None:
    """把职级字符串转成 hay_grade 整数。优先从员工数据里取映射关系。"""
    # 优先从员工数据里找——公司 grade 到 hay_grade 的映射是在 grade_matching 阶段建立的
    for emp in employees:
        if str(emp.get('grade', '')) == grade_str and emp.get('hay_grade'):
            return int(emp['hay_grade'])

    # 如果 use_standard=True，grade_str 本身就是 hay_grade
    if use_standard:
        import re
        nums = re.findall(r'\d+', grade_str)
        if nums:
            return int(nums[0])

    return None


def _exp_regression(x_vals: list[int], y_vals: list) -> list:
    """
    指数回归 y = a * e^(bx)。
    等价于 log(y) = log(a) + b*x 的 OLS。
    纯 Python 实现，不依赖 numpy。
    y_vals 里 None 或 <=0 的点跳过。
    """
    pairs = [(x, y) for x, y in zip(x_vals, y_vals) if y and y > 0]
    if len(pairs) < 2:
        return [y if y and y > 0 else None for y in y_vals]

    xs = [p[0] for p in pairs]
    log_ys = [math.log(p[1]) for p in pairs]
    n = len(xs)

    sum_x = sum(xs)
    sum_y = sum(log_ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, log_ys))

    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-12:
        return [y if y and y > 0 else None for y in y_vals]

    b = (n * sum_xy - sum_x * sum_y) / denom
    log_a = (sum_y - b * sum_x) / n
    a = math.exp(log_a)

    return [round(a * math.exp(b * x)) for x in x_vals]


def _compute_annotations(grades, company, mkt_p25, mkt_p50, mkt_p75) -> list:
    """代码生成关键点标注"""
    annotations = []

    # 1. 找偏离 P50 最大的点
    max_dev_idx = None
    max_dev_pct = 0
    for i in range(len(grades)):
        if company[i] and mkt_p50[i] and mkt_p50[i] > 0:
            dev = (company[i] - mkt_p50[i]) / mkt_p50[i] * 100
            if abs(dev) > abs(max_dev_pct):
                max_dev_pct = dev
                max_dev_idx = i

    if max_dev_idx is not None and abs(max_dev_pct) > 5:
        direction = '高于' if max_dev_pct > 0 else '低于'
        annotations.append({
            'grade': grades[max_dev_idx],
            'type': 'max_deviation',
            'text': f'{direction}市场 P50 约 {abs(round(max_dev_pct))}%',
        })

    # 2. 低于 P25 的职级
    for i in range(len(grades)):
        if company[i] and mkt_p25[i] and company[i] < mkt_p25[i]:
            annotations.append({
                'grade': grades[i],
                'type': 'below_p25',
                'text': '低于市场 P25',
            })

    # 3. 高于 P75 的职级
    for i in range(len(grades)):
        if company[i] and mkt_p75[i] and company[i] > mkt_p75[i]:
            annotations.append({
                'grade': grades[i],
                'type': 'above_p75',
                'text': '高于市场 P75',
            })

    # 4. 交叉点检测（公司线穿越 P50）
    for i in range(1, len(grades)):
        c_prev, c_now = company[i - 1], company[i]
        m_prev, m_now = mkt_p50[i - 1], mkt_p50[i]
        if c_prev is None or c_now is None or m_prev is None or m_now is None:
            continue
        diff_prev = c_prev - m_prev
        diff_now = c_now - m_now
        if diff_prev * diff_now < 0:  # 符号变化 = 交叉
            annotations.append({
                'grade': grades[i],
                'type': 'crossover',
                'text': f'公司线在 {grades[i-1]}-{grades[i]} 之间穿越市场 P50',
            })

    return annotations


def _compute_storyline(grades, company, mkt_p50, annotations) -> str:
    """代码生成一句话 storyline（不调 AI）"""
    if not grades or not any(mkt_p50):
        return '缺少市场数据，无法生成趋势对比。'

    # 整体偏向
    devs = []
    for i in range(len(grades)):
        if company[i] and mkt_p50[i] and mkt_p50[i] > 0:
            devs.append((company[i] - mkt_p50[i]) / mkt_p50[i] * 100)

    if not devs:
        return '缺少可对比数据。'

    avg_dev = sum(devs) / len(devs)

    crossovers = [a for a in annotations if a['type'] == 'crossover']
    below_p25 = [a for a in annotations if a['type'] == 'below_p25']

    parts = []
    if abs(avg_dev) < 10:
        parts.append('公司薪酬曲线整体接近市场 P50')
    elif avg_dev > 0:
        parts.append(f'公司薪酬整体高于市场 P50 约 {round(avg_dev)}%')
    else:
        parts.append(f'公司薪酬整体低于市场 P50 约 {abs(round(avg_dev))}%')

    if crossovers:
        parts.append(f'在 {crossovers[0]["grade"]} 附近出现交叉，存在结构性转折')

    # 检测上下倒挂：低职级偏高 + 高职级偏低
    if len(devs) >= 3:
        low_dev = sum(devs[:len(devs) // 2]) / max(len(devs) // 2, 1)
        high_dev = sum(devs[len(devs) // 2:]) / max(len(devs) - len(devs) // 2, 1)
        if low_dev > 5 and high_dev < -5:
            parts.append('低职级偏高、高职级偏低，呈上下倒挂结构')
        elif low_dev < -5 and high_dev > 5:
            parts.append('低职级偏低、高职级偏高')

    if below_p25:
        grades_below = [a['grade'] for a in below_p25]
        parts.append(f'{", ".join(grades_below)} 已低于市场 P25')

    return '，'.join(parts) + '。'
