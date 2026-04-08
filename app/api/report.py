from flask import Blueprint, jsonify
from app.services.market_data import lookup_market_salary

report_bp = Blueprint('report', __name__)


@report_bp.route('/<session_id>', methods=['GET'])
def get_report(session_id):
    """Get the diagnostic report for a session"""
    from app.api.sessions import sessions_store

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    report = session.get('analysis_results')
    if not report:
        return jsonify({'error': 'Analysis not complete'}), 400
    return jsonify(report)


@report_bp.route('/<session_id>/analyze', methods=['POST'])
def run_analysis(session_id):
    """Trigger analysis pipeline"""
    from app.api.sessions import sessions_store

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    session['status'] = 'analyzing'

    # Get cleaned employee data (for MVP, use mock data if real data not available)
    employees = session.get('cleaned_employees', get_mock_employees())
    company_data = session.get('company_data')

    # Run all analysis modules
    from app.engine import external_competitiveness, internal_equity, pay_performance, fix_variable_ratio, labor_cost

    ext_comp = external_competitiveness.analyze(employees, lookup_market_salary)
    int_equity = internal_equity.analyze(employees)
    pay_perf = pay_performance.analyze(employees)
    fix_var = fix_variable_ratio.analyze(employees)
    lab_cost = labor_cost.analyze(employees, company_data)

    # Calculate health score
    cr_values = [e.get('cr', 1.0) for e in employees if e.get('cr')]
    avg_cr = sum(cr_values) / len(cr_values) if cr_values else 1.0
    health_score = min(100, max(0, int(avg_cr * 70 + 30)))  # Simple formula

    report = {
        'health_score': health_score,
        'key_findings': generate_key_findings(ext_comp, int_equity, pay_perf, lab_cost),
        'modules': {
            'external_competitiveness': {**ext_comp, 'status': 'warning' if avg_cr < 0.95 else 'normal'},
            'internal_equity': {**int_equity, 'status': 'attention'},
            'pay_performance': {**pay_perf, 'status': 'attention'},
            'fix_variable_ratio': {**fix_var, 'status': 'normal'},
            'labor_cost': {**lab_cost, 'status': 'warning' if company_data else 'unavailable'},
        }
    }

    session['status'] = 'report_done'
    session['analysis_results'] = report

    return jsonify({'status': 'analyzing'}), 202


def generate_key_findings(ext_comp, int_equity, pay_perf, lab_cost):
    findings = []

    # Check CR by function
    for f in ext_comp.get('cr_by_function', []):
        if f['cr'] < 0.85:
            findings.append({'severity': 'red', 'text': f"{f['name']}薪酬竞争力不足，CR 仅 {f['cr']}"})

    # Check dispersion
    for d in int_equity.get('dispersion', []):
        if d['status'] == 'high':
            findings.append({'severity': 'amber', 'text': f"{d['grade']} 层级内部薪酬离散度偏高，离散系数 {d['coefficient']}"})

    # Check pay-performance
    cr_by_perf = pay_perf.get('cr_by_performance', [])
    if len(cr_by_perf) >= 2:
        top_cr = cr_by_perf[0].get('cr', 1.0)
        bottom_cr = cr_by_perf[-1].get('cr', 1.0)
        if bottom_cr > 0:
            gap = round((top_cr / bottom_cr - 1) * 100)
            if gap < 30:
                findings.append({'severity': 'amber', 'text': f'绩效与薪酬关联偏弱，最高与最低绩效薪酬差距仅 {gap}%'})

    return findings[:4]  # Max 4 findings


def get_mock_employees():
    """Generate mock employee data for testing"""
    import random
    random.seed(42)

    departments = ['研发部', '销售部', '市场部', '人力资源部', '行政部']
    grades = ['Level2-1', 'Level2-2', 'Level3-1', 'Level3-2', 'Level4-1', 'Level4-2', 'Level5-1', 'Level5-2']
    functions = ['招聘', '薪酬管理', 'HRBP', '绩效管理', '人才发展', '员工关系']
    performances = ['A', 'B+', 'B', 'B-', 'C']

    hay_map = {
        'Level2-1': 10, 'Level2-2': 11, 'Level3-1': 12, 'Level3-2': 13,
        'Level4-1': 14, 'Level4-2': 15, 'Level5-1': 16, 'Level5-2': 17,
    }
    base_salary_map = {
        'Level2-1': 7000, 'Level2-2': 8000, 'Level3-1': 10000, 'Level3-2': 12000,
        'Level4-1': 15000, 'Level4-2': 18000, 'Level5-1': 22000, 'Level5-2': 26000,
    }

    employees = []
    for i in range(80):
        grade = random.choice(grades)
        base = base_salary_map[grade]
        # Add some variance
        base = int(base * random.uniform(0.8, 1.25))
        bonus = int(base * random.uniform(1.0, 3.0))

        emp = {
            'id': f'EMP{i + 1:03d}',
            'department': random.choice(departments),
            'grade': grade,
            'hay_grade': hay_map[grade],
            'job_function': random.choice(functions),
            'base_monthly': base,
            'annual_bonus': bonus,
            'performance': random.choice(performances),
            'cr': None,  # Will be calculated
        }
        employees.append(emp)

    return employees
