"""
诊断报告编排：
1. 跑 5 个分析引擎（纯代码计算）
2. 生成结构化结果供前端图表使用
3. AI 生成诊断摘要、模块解读、行动建议（Phase 3）
"""
from flask import Blueprint, jsonify
from app.services.market_data import lookup_market_salary

report_bp = Blueprint('report', __name__)


@report_bp.route('/<session_id>', methods=['GET'])
def get_report(session_id):
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
    from app.api.sessions import sessions_store
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    session['status'] = 'analyzing'

    employees = session.get('cleaned_employees') or session.get('_employees', [])
    if not employees:
        return jsonify({'error': 'No employee data'}), 400

    sheet2_summary = None
    if session.get('parse_result'):
        sheet2_summary = session['parse_result'].get('sheet2_summary')

    # ==============================
    # Phase 1: 跑 5 个计算引擎
    # ==============================
    from app.engine import (
        external_competitiveness, internal_equity,
        pay_performance, fix_variable_ratio, labor_cost,
    )

    ext_comp = external_competitiveness.analyze(employees, lookup_market_salary)
    int_equity = internal_equity.analyze(employees)
    pay_perf = pay_performance.analyze(employees)
    fix_var = fix_variable_ratio.analyze(employees)
    lab_cost = labor_cost.analyze(employees, sheet2_summary=sheet2_summary)

    # ==============================
    # 健康分（基于各模块 status 综合打分）
    # ==============================
    health_score = _calculate_health_score(ext_comp, int_equity, pay_perf, fix_var, lab_cost)

    # ==============================
    # 关键发现（代码逻辑提取，Phase 3 会加 AI 交叉验证）
    # ==============================
    key_findings = _generate_key_findings(ext_comp, int_equity, pay_perf, fix_var, lab_cost)

    report = {
        'health_score': health_score,
        'key_findings': key_findings,
        'modules': {
            'external_competitiveness': ext_comp,
            'internal_equity': int_equity,
            'pay_performance': pay_perf,
            'fix_variable_ratio': fix_var,
            'labor_cost': lab_cost,
        },
    }

    session['status'] = 'report_done'
    session['analysis_results'] = report

    return jsonify(report), 200


def _calculate_health_score(ext_comp, int_equity, pay_perf, fix_var, lab_cost):
    """综合健康分（0-100），基于各模块的核心指标"""
    scores = []

    # 外部竞争力：CR 越接近 1.0 越好
    cr = ext_comp.get('overall_cr')
    if cr:
        # CR=1.0 → 100分，CR=0.8 → 60分，CR=1.2 → 80分
        cr_score = max(0, min(100, 100 - abs(cr - 1.0) * 200))
        scores.append(cr_score * 0.3)  # 权重 30%

    # 内部公平性：离散度异常越少越好
    high_disp = int_equity.get('high_dispersion_count', 0)
    total_grades = len(int_equity.get('dispersion', []))
    if total_grades > 0:
        equity_score = max(0, 100 - high_disp / total_grades * 100)
        scores.append(equity_score * 0.25)  # 权重 25%

    # 绩效关联：A vs B 差距够大
    gap = pay_perf.get('a_vs_b_gap_pct')
    if gap is not None:
        # 差距 15%+ → 100分，差距 0% → 40分
        perf_score = min(100, 40 + gap * 4)
        scores.append(perf_score * 0.2)  # 权重 20%

    # 薪酬结构：固浮比合理
    fix_pct = fix_var.get('overall_fix_pct', 70)
    # 60-80% 固定占比最佳
    if 60 <= fix_pct <= 80:
        mix_score = 100
    else:
        mix_score = max(0, 100 - abs(fix_pct - 70) * 2)
    scores.append(mix_score * 0.15)  # 权重 15%

    # 人工成本：有数据就给基础分
    if lab_cost.get('has_trend_data'):
        scores.append(70 * 0.1)  # 权重 10%
    else:
        scores.append(50 * 0.1)

    total_weight = sum([0.3, 0.25, 0.2, 0.15, 0.1][:len(scores)])
    return round(sum(scores) / total_weight) if total_weight > 0 else 50


def _generate_key_findings(ext_comp, int_equity, pay_perf, fix_var, lab_cost):
    """生成 3-5 条关键发现，按优先级排序"""
    findings = []

    # 外部竞争力
    overall_cr = ext_comp.get('overall_cr')
    if overall_cr and overall_cr < 0.9:
        findings.append({
            'priority': 'P1', 'severity': 'red',
            'module': 'external_competitiveness',
            'text': f'整体薪酬竞争力不足（CR {overall_cr}），{ext_comp.get("total_below_p25", 0)} 人低于市场 P25',
        })

    for f in ext_comp.get('cr_by_function', []):
        if f.get('cr', 1) < 0.85 and f.get('below_p25_count', 0) > 0:
            findings.append({
                'priority': 'P1', 'severity': 'red',
                'module': 'external_competitiveness',
                'text': f'{f["name"]}薪酬严重偏低（CR {f["cr"]}），{f["below_p25_count"]} 人低于 P25',
            })

    # 内部公平性
    if int_equity.get('high_dispersion_count', 0) > 0:
        high_grades = [d['grade'] for d in int_equity.get('dispersion', []) if d['status'] == 'high']
        findings.append({
            'priority': 'P2', 'severity': 'amber',
            'module': 'internal_equity',
            'text': f'{", ".join(high_grades[:3])} 层级内部薪酬离散度偏高，存在同岗不同酬风险',
        })

    # 绩效关联
    if pay_perf.get('has_data') and not pay_perf.get('spread_adequate'):
        findings.append({
            'priority': 'P2', 'severity': 'amber',
            'module': 'pay_performance',
            'text': f'高绩效与平均绩效薪酬差距仅 {pay_perf.get("a_vs_b_gap_pct", 0)}%，激励区分度不足',
        })

    # 人工成本
    kpi = lab_cost.get('kpi', {})
    ratio = kpi.get('cost_revenue_ratio')
    if ratio and ratio > 30:
        findings.append({
            'priority': 'P2', 'severity': 'amber',
            'module': 'labor_cost',
            'text': f'人工成本占营收 {ratio}%，高于 30% 警戒线',
        })

    # 按优先级排序
    priority_order = {'P1': 0, 'P2': 1, 'P3': 2}
    findings.sort(key=lambda f: priority_order.get(f['priority'], 9))

    return findings[:5]
