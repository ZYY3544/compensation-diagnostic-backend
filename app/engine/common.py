"""通用计算函数"""
import statistics


def calculate_cr(actual_salary, market_p50):
    """Compa-Ratio = 实际薪酬 / 市场中位值"""
    if not market_p50 or market_p50 <= 0:
        return None
    return round(actual_salary / market_p50, 2)


def calculate_percentile_position(actual, p25, p50, p75):
    """估算实际薪酬处于市场什么分位。返回 0-100 的整数。"""
    if not p25 or not p50 or not p75 or p25 <= 0:
        return None
    if actual <= p25:
        return max(1, int(25 * actual / p25))
    elif actual <= p50:
        return 25 + int(25 * (actual - p25) / max(p50 - p25, 1))
    elif actual <= p75:
        return 50 + int(25 * (actual - p50) / max(p75 - p50, 1))
    else:
        return min(99, 75 + int(25 * (actual - p75) / max(p75 - p50, 1)))


def calculate_dispersion(salaries):
    """离散系数 = 标准差 / 均值"""
    valid = [s for s in salaries if s and s > 0]
    if len(valid) < 2:
        return 0
    mean = statistics.mean(valid)
    if mean <= 0:
        return 0
    return round(statistics.stdev(valid) / mean, 3)


def calculate_range_ratio(salaries):
    """极差比 = 最大值 / 最小值"""
    valid = [s for s in salaries if s and s > 0]
    if len(valid) < 2:
        return 0
    return round(max(valid) / min(valid), 2)


def safe_mean(values):
    valid = [v for v in values if v is not None and v > 0]
    return round(statistics.mean(valid), 2) if valid else 0


def safe_median(values):
    valid = [v for v in values if v is not None and v > 0]
    return round(statistics.median(valid), 2) if valid else 0
