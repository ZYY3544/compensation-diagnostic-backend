"""
诊断报告编排 + AI 生成 + PDF 导出：
1. 跑 5 个分析引擎（纯代码计算）
2. 生成结构化结果供前端图表使用
3. AI 生成诊断摘要、模块解读、行动建议（Phase 3）
"""
from flask import Blueprint, jsonify, make_response
from app.services.market_data import lookup_market_salary

report_bp = Blueprint('report', __name__)


@report_bp.route('/<session_id>', methods=['GET'])
def get_report(session_id):
    from app.api.sessions import sessions_store
    from app.services.snapshot_loader import load_analysis_results
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    report = load_analysis_results(session_id, session)
    if not report:
        return jsonify({'error': 'Analysis not complete'}), 400
    return jsonify(report)


@report_bp.route('/<session_id>/analyze', methods=['POST'])
def run_analysis(session_id):
    from app.api.sessions import sessions_store
    from app.services.snapshot_loader import load_cleaned_employees
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    session['status'] = 'analyzing'

    # 优先 DB（重跑 analyze 时不依赖 in-memory），fallback 到 session
    employees = load_cleaned_employees(session_id, session)
    if not employees:
        return jsonify({'error': 'No employee data'}), 400

    # ==============================
    # 从 full_analysis 缓存读取（数据变化会自动失效重算）
    # ==============================
    from app.services.full_analysis import get_or_compute
    full = get_or_compute(session)

    ext_comp = full['external_competitiveness']
    int_equity = full['internal_equity']
    pay_perf = full['pay_performance']
    fix_var = full['fix_variable_ratio']
    lab_cost = full['labor_cost']

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
        'grade_trend_tcc': full.get('grade_trend_tcc', {}),
        'grade_trend_base': full.get('grade_trend_base', {}),
    }

    session['status'] = 'report_done'
    session['analysis_results'] = report

    # ==============================
    # 持久化 DataSnapshot（把 session 里的数据写入 data_snapshots 表）
    # 后续轻模式查询可直接从这里读，不用重新上传
    # ==============================
    _persist_snapshot(session_id, session, full, report)

    return jsonify(report), 200


def _persist_snapshot(snapshot_id, session, full_analysis, report):
    """把 session 的关键数据同步到 DataSnapshot。
    analysis_results 也写入 —— 让 downstream 接口（diagnosis-summary 等）能从 DB 读，
    不依赖 in-memory session。
    employees_original 和 code_results 不再写入：前者可由 mutations.old_value 重建，
    后者仅 cleansing 阶段需要，post-cleansing 没有读者。"""
    try:
        from app.storage import get_storage
        from datetime import datetime
        storage = get_storage()
        existing = storage.get_snapshot(snapshot_id) or {}
        snapshot = {
            **existing,
            'snapshot_id': snapshot_id,
            'status': 'analyzed',
            'cleaned_employees': session.get('cleaned_employees') or session.get('_employees', []),
            'interview_notes': session.get('interview_notes'),
            'parse_result': session.get('parse_result'),
            'grade_mapping': session.get('_grade_match_result'),
            'func_mapping': session.get('_func_match_result'),
            'full_analysis_json': full_analysis,
            'analysis_results': report,
            'analyzed_at': datetime.utcnow().isoformat(),
            'field_map': session.get('_field_map'),
            'column_names': session.get('_column_names'),
            'grades_list': session.get('_grades_list'),
            'mutations': session.get('_mutations'),
        }
        storage.save_snapshot(snapshot)
        print(f'[Snapshot] persisted {snapshot_id}')
    except Exception as e:
        print(f'[Snapshot] persist failed: {e}')
        import traceback
        traceback.print_exc()


# ======================================================================
# AI 生成接口
# ======================================================================

@report_bp.route('/<session_id>/diagnosis-summary', methods=['POST'])
def get_diagnosis_summary(session_id):
    """AI 生成诊断摘要（opening + findings）"""
    from app.api.sessions import sessions_store
    from app.services.snapshot_loader import load_analysis_results, load_interview_notes
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # 优先从 data_snapshots 读，session 仅作 fallback——避免内存里长期持有大块数据
    report = load_analysis_results(session_id, session)
    if not report:
        return jsonify({'error': 'Analysis not complete'}), 400

    interview_notes = load_interview_notes(session_id, session)

    import os, json
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        return jsonify({
            'opening': '诊断报告已生成，请查看右侧各模块详情。',
            'findings': report.get('key_findings', []),
        })

    # 构建紧凑数据摘要（只传关键数字，不传明细）
    modules = report.get('modules', {})
    ec = modules.get('external_competitiveness', {})
    ie = modules.get('internal_equity', {})
    pp = modules.get('pay_performance', {})
    fv = modules.get('fix_variable_ratio', {})
    lc_kpi = modules.get('labor_cost', {}).get('kpi', {})

    summary = {
        'health_score': report.get('health_score'),
        # 代码预算出的 findings（已按优先级排序）
        'code_findings': [
            {'priority': f.get('priority'), 'text': f.get('text')}
            for f in report.get('key_findings', [])[:5]
        ],
        'external_cr': ec.get('overall_cr'),
        'external_below_p25': ec.get('total_below_p25'),
        'equity_high_dispersion_grades': [
            d['grade'] for d in ie.get('dispersion', []) if d.get('status') == 'high'
        ],
        'performance_a_vs_b_gap_pct': pp.get('a_vs_b_gap_pct'),
        'performance_spread_adequate': pp.get('spread_adequate'),
        'fix_pct': fv.get('overall_fix_pct'),
        'labor_cost_per_head': lc_kpi.get('per_head_cost'),
    }
    user_content = json.dumps({
        'analysis_summary': summary,
        'interview_notes': (str(interview_notes) if interview_notes else '')[:1500],
    }, ensure_ascii=False)

    def _call_ai():
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.5)
        system_prompt = agent.load_prompt('diagnosis_summary.txt')
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        return agent.call_llm(messages).strip()

    # 单次重试：第一次失败等 2s 重试，再失败走 fallback
    text = None
    last_err = None
    import time
    for attempt in (1, 2):
        try:
            text = _call_ai()
            if text:
                break
        except Exception as e:
            last_err = e
            print(f'[Report] AI summary attempt {attempt} failed: {e}')
            if attempt == 1:
                time.sleep(2)

    if text:
        return jsonify({
            'opening': text,
            'findings': report.get('key_findings', []),
        })

    print(f'[Report] AI summary final fallback (last err: {last_err})')
    return jsonify({
        'opening': '诊断报告已生成，请查看右侧各模块详情。',
        'findings': report.get('key_findings', []),
    })


@report_bp.route('/<session_id>/module-insight', methods=['POST'])
def get_module_insight(session_id):
    """AI 生成单个模块的解读"""
    from flask import request
    from app.api.sessions import sessions_store
    from app.services.snapshot_loader import load_analysis_results, load_interview_notes
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    report = load_analysis_results(session_id, session)
    if not report:
        return jsonify({'error': 'Analysis not complete'}), 400

    data = request.json or {}
    module_key = data.get('module', '')
    module_data = report.get('modules', {}).get(module_key, {})
    interview_notes = load_interview_notes(session_id, session)

    import os, json
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        return jsonify({'insight': ''})

    # 精简模块数据（去掉大列表，只保留统计数字）
    slim_data = {k: v for k, v in module_data.items()
                 if k not in ('cr_heatmap', 'deviation_matrix', 'boxplot', 'below_p25_detail', 'trend')}
    user_content = json.dumps({
        'module': module_key,
        'module_data': slim_data,
        'diagnosis_summary': report.get('key_findings', [])[:3],
        'interview_notes': str(interview_notes)[:1000],
    }, ensure_ascii=False)

    def _call_ai():
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.5)
        system_prompt = agent.load_prompt('module_insight.txt')
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        return agent.call_llm(messages).strip()

    # 单次重试：第一次失败等 2s 重试一次，还失败走 fallback
    import time
    insight = ''
    last_err = None
    for attempt in (1, 2):
        try:
            insight = _call_ai()
            if insight:
                break
        except Exception as e:
            last_err = e
            print(f'[Report] AI insight {module_key} attempt {attempt} failed: {e}')
            if attempt == 1:
                time.sleep(2)

    if insight:
        return jsonify({'insight': insight})

    # fallback：基于 code findings 拼一句兜底文案，不是空白
    print(f'[Report] AI insight {module_key} final fallback (last err: {last_err})')
    mod_findings = [f for f in report.get('key_findings', []) if f.get('module') == module_key]
    if mod_findings:
        fallback = '；'.join(f['text'] for f in mod_findings[:2])
        return jsonify({'insight': f'该模块关键发现：{fallback}。详细解读暂时无法生成，请稍后重试或查看右侧图表。'})
    return jsonify({'insight': '详细解读暂时无法生成，请稍后重试或查看右侧图表。'})


@report_bp.route('/<session_id>/diagnosis-advice', methods=['POST'])
def get_diagnosis_advice(session_id):
    """AI 生成诊断建议"""
    from app.api.sessions import sessions_store
    from app.services.snapshot_loader import load_analysis_results, load_interview_notes
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    report = load_analysis_results(session_id, session)
    if not report:
        return jsonify({'error': 'Analysis not complete'}), 400

    interview_notes = load_interview_notes(session_id, session)

    import os, json
    if not os.getenv('OPENROUTER_API_KEY', '').strip():
        return jsonify({'advice': [], 'closing': ''})

    try:
        from app.agents.base_agent import BaseAgent
        agent = BaseAgent(temperature=0.5)
        system_prompt = agent.load_prompt('diagnosis_advice.txt')

        modules = report.get('modules', {})
        summary = {
            'health_score': report.get('health_score'),
            'key_findings': report.get('key_findings', []),
            'external_cr': modules.get('external_competitiveness', {}).get('overall_cr'),
            'below_p25_count': modules.get('external_competitiveness', {}).get('total_below_p25'),
            'high_dispersion_count': modules.get('internal_equity', {}).get('high_dispersion_count'),
            'a_vs_b_gap': modules.get('pay_performance', {}).get('a_vs_b_gap_pct'),
            'overall_fix_pct': modules.get('fix_variable_ratio', {}).get('overall_fix_pct'),
            'cost_revenue_ratio': modules.get('labor_cost', {}).get('kpi', {}).get('cost_revenue_ratio'),
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({
                'analysis_summary': summary,
                'interview_notes': str(interview_notes)[:2000],
            }, ensure_ascii=False)},
        ]
        response = agent.call_llm(messages)

        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]

        result = json.loads(response.strip())
        return jsonify(result)

    except Exception as e:
        print(f'[Report] AI advice failed: {e}')
        return jsonify({'advice': [], 'closing': ''})


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

    # 外部竞争力 —— 偏低
    overall_cr = ext_comp.get('overall_cr')
    if overall_cr and overall_cr < 0.9:
        findings.append({
            'priority': 'P1', 'severity': 'red',
            'module': 'external_competitiveness',
            'text': f'整体薪酬竞争力不足（CR {overall_cr}），{ext_comp.get("total_below_p25", 0)} 人低于市场 P25',
        })

    # 外部竞争力 —— 偏高（overpay，也是问题：人工成本虚高或数据口径有误）
    if overall_cr and overall_cr > 2.0:
        findings.append({
            'priority': 'P2', 'severity': 'amber',
            'module': 'external_competitiveness',
            'text': f'整体薪酬显著高于市场（CR {overall_cr}，>P75 x 2），建议核对职级对标口径或市场分位取值',
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
    if pay_perf.get('has_data'):
        gap = pay_perf.get('a_vs_b_gap_pct')
        if gap is not None and gap < 15:
            findings.append({
                'priority': 'P2', 'severity': 'amber',
                'module': 'pay_performance',
                'text': f'高绩效与平均绩效薪酬差距仅 {gap}%，激励区分度不足',
            })
        elif gap is not None and gap > 50:
            # 差距过大也要提示——可能数据有问题或过度分化
            findings.append({
                'priority': 'P2', 'severity': 'amber',
                'module': 'pay_performance',
                'text': f'高绩效与平均绩效薪酬差距 {gap}%（>50%），绩效薪酬分化过激，建议核对异常个体或政策边界',
            })

    # 薪酬结构 —— 固定占比过高
    fix_pct = fix_var.get('overall_fix_pct')
    if fix_pct is not None and fix_pct > 85:
        findings.append({
            'priority': 'P2', 'severity': 'amber',
            'module': 'fix_variable_ratio',
            'text': f'固定薪酬占比 {fix_pct}%（>85%），薪酬包刚性过强，调薪腾挪空间与绩效激励弹性不足',
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


@report_bp.route('/<session_id>/export-pdf', methods=['GET'])
def export_pdf(session_id):
    """导出诊断报告 PDF"""
    from app.api.sessions import sessions_store
    from app.services.snapshot_loader import load_analysis_results
    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    report = load_analysis_results(session_id, session)
    if not report:
        return jsonify({'error': 'Analysis not complete'}), 400

    advice = session.get('_diagnosis_advice')

    from app.services.pdf_exporter import generate_report_pdf
    pdf_bytes = generate_report_pdf(report, advice)

    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=compensation_diagnosis_report.pdf'
    return response
