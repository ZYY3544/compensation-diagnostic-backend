def calculate_cr(actual_salary, market_p50):
    """Calculate Compa-Ratio"""
    if not market_p50 or market_p50 == 0:
        return None
    return round(actual_salary / market_p50, 2)

def calculate_dispersion(salaries):
    """Calculate salary dispersion coefficient"""
    if len(salaries) < 2:
        return 0
    mean = sum(salaries) / len(salaries)
    if mean == 0:
        return 0
    variance = sum((s - mean) ** 2 for s in salaries) / len(salaries)
    std_dev = variance ** 0.5
    return round(std_dev / mean, 2)

def calculate_range_ratio(salaries):
    """Calculate max/min ratio"""
    if not salaries or min(salaries) == 0:
        return 0
    return round(max(salaries) / min(salaries), 1)
