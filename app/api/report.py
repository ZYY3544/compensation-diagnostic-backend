from flask import Blueprint, jsonify

report_bp = Blueprint('report', __name__)

@report_bp.route('/<session_id>', methods=['GET'])
def get_report(session_id):
    """Get the diagnostic report for a session"""
    from app.api.sessions import sessions_store

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # For MVP: return mock report data
    return jsonify(get_mock_report())


@report_bp.route('/<session_id>/analyze', methods=['POST'])
def run_analysis(session_id):
    """Trigger analysis pipeline"""
    from app.api.sessions import sessions_store

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    session['status'] = 'analyzing'

    # For MVP: immediately set to done with mock data
    session['status'] = 'report_done'
    session['analysis_results'] = get_mock_report()

    return jsonify({'status': 'analyzing'}), 202


def get_mock_report():
    """Mock report data"""
    return {
        'health_score': 72,
        'key_findings': [
            {'severity': 'red', 'text': '销售 L4-L5 竞争力不足，CR 仅 0.84-0.88'},
            {'severity': 'amber', 'text': 'L5 层级内部薪酬离散度偏高，离散系数 0.32'},
            {'severity': 'amber', 'text': '绩效与薪酬关联偏弱，A vs C 差距仅 23%'},
            {'severity': 'red', 'text': '人工成本增速（22%）高于营收增速（15%）'},
        ],
        'modules': {
            'external_competitiveness': {
                'status': 'warning',
                'cr_by_function': [
                    {'name': '研发', 'cr': 1.05},
                    {'name': '产品', 'cr': 0.98},
                    {'name': '销售', 'cr': 0.88},
                    {'name': '人力资源', 'cr': 0.82},
                    {'name': '行政', 'cr': 0.85},
                ],
                'cr_heatmap': {
                    'departments': ['研发', '销售', '市场', '人力资源', '行政'],
                    'grades': ['L3', 'L4', 'L5', 'L6', 'L7', 'L8'],
                    'values': [
                        [1.05, 1.07, 1.04, 1.02, 1.07, 1.03],
                        [0.92, 0.97, 0.88, 0.84, 0.89, None],
                        [0.95, 0.89, 0.91, 0.88, None, 0.90],
                        [0.83, 0.82, 0.81, None, None, None],
                        [0.89, 0.85, None, None, None, None],
                    ]
                },
                'insight': '你提到销售团队流失严重，从数据来看确实如此——销售 L4-L5 的 CR 值仅 0.84-0.88，低于市场中位值 12-16%，薪酬竞争力不足很可能是流失的核心原因。',
            },
            'internal_equity': {
                'status': 'attention',
                'deviation_matrix': {
                    'departments': ['研发', '销售', '市场', '人力资源', '行政'],
                    'grades': ['L3', 'L4', 'L5', 'L6'],
                    'values': [
                        ['+8%', '+14%', '+12%', '+9%'],
                        ['-5%', '+3%', '-8%', '-12%'],
                        ['-2%', '-7%', '-4%', '-6%'],
                        ['-12%', '-10%', '-15%', None],
                        ['-8%', '-5%', None, None],
                    ]
                },
                'dispersion': [
                    {'grade': 'L3', 'coefficient': 0.18, 'range_ratio': 1.4, 'status': 'normal'},
                    {'grade': 'L4', 'coefficient': 0.25, 'range_ratio': 1.8, 'status': 'normal'},
                    {'grade': 'L5', 'coefficient': 0.32, 'range_ratio': 2.3, 'status': 'high'},
                    {'grade': 'L6', 'coefficient': 0.22, 'range_ratio': 1.9, 'status': 'normal'},
                    {'grade': 'L7', 'coefficient': 0.28, 'range_ratio': 1.7, 'status': 'normal'},
                ],
                'insight': 'L5 层级离散度偏高（离散系数 0.32，极差比 2.3），主要由研发与非研发岗薪酬差异导致。',
            },
            'pay_performance': {
                'status': 'attention',
                'cr_by_performance': [
                    {'grade': 'A', 'cr': 1.12},
                    {'grade': 'B+', 'cr': 1.05},
                    {'grade': 'B', 'cr': 0.98},
                    {'grade': 'B-', 'cr': 0.94},
                    {'grade': 'C', 'cr': 0.91},
                ],
                'raise_by_performance': [
                    {'grade': 'A', 'pct': 12},
                    {'grade': 'B+', 'pct': 8},
                    {'grade': 'B', 'pct': 6},
                    {'grade': 'B-', 'pct': 3},
                    {'grade': 'C', 'pct': 1},
                ],
                'insight': '你提到调薪预算 8% 按统一比例分配，这从数据上得到了印证——A 绩效 CR 1.12 vs C 绩效 CR 0.91，差距仅 23%。',
            },
            'fix_variable_ratio': {
                'status': 'normal',
                'pay_mix': [
                    {'grade': 'L3', 'fixed': 72000, 'variable': 12000},
                    {'grade': 'L4', 'fixed': 96000, 'variable': 18000},
                    {'grade': 'L5', 'fixed': 132000, 'variable': 36000},
                    {'grade': 'L6', 'fixed': 168000, 'variable': 60000},
                    {'grade': 'L7', 'fixed': 216000, 'variable': 96000},
                    {'grade': 'L8', 'fixed': 276000, 'variable': 156000},
                ],
                'insight': '整体呈合理梯度：越高职级浮动越多。但 L3-L4 浮动占比偏低（14-16%），市场通常 20%。',
            },
            'labor_cost': {
                'status': 'warning',
                'kpi': {
                    'cost_revenue_ratio': {'value': 32, 'trend': 'up', 'label': '偏高'},
                    'revenue_per_head': {'value': 68, 'trend': 'flat', 'label': '持平'},
                    'profit_per_head': {'value': 12, 'trend': 'down', 'label': '偏低'},
                    'cost_vs_revenue_growth': {'cost': 22, 'revenue': 15, 'label': '失衡'},
                },
                'trend': [
                    {'year': '2022', 'cost': 1850},
                    {'year': '2023', 'cost': 2340},
                    {'year': '2024', 'cost': 2890},
                    {'year': '2025', 'cost': 3250},
                ],
                'insight': '你提到明年的重点是降本增效，数据也显示这很紧迫——人工成本增速（22%）显著高于营收增速（15%）。',
            },
        }
    }
