"""
完整薪酬诊断 engine：触发五模块全量分析。
实际流程通过现有 POST /report/{id}/analyze 走，这里只是占位，让 skill 调用能走通。
"""


def run_all(data_snapshot=None, params=None):
    """
    触发完整诊断。实际复用 full_analysis 缓存结果。
    返回包含五个模块结果和摘要。
    """
    if not isinstance(data_snapshot, dict):
        return {'error': '缺少数据快照'}

    full = data_snapshot.get('full_analysis')
    if not full:
        return {'error': '全量分析未就绪，请先上传数据'}

    return {
        'status': 'ready',
        'modules': {
            'external': full.get('external_competitiveness'),
            'internal_equity': full.get('internal_equity'),
            'pay_mix': full.get('fix_variable_ratio'),
            'performance': full.get('pay_performance'),
            'cost_trend': full.get('labor_cost'),
        },
        'analyzed_at': full.get('analyzed_at'),
        'employee_count': full.get('employee_count'),
    }
