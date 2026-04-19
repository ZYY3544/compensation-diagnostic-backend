"""
全量分析 JSON：一次计算，多维度覆盖。
所有 skill 都读这份 JSON，不重复计算。
数据变化（重新上传、调整映射）时需调用 invalidate() 清空。
"""
from app.engine import (
    external_competitiveness, internal_equity,
    pay_performance, fix_variable_ratio, labor_cost,
)
from app.engine.grade_trend import compute_grade_trend
from app.services.market_data import lookup_market_salary
from app.models import now_iso


def compute_full_analysis(employees: list, sheet2_summary: dict = None) -> dict:
    """
    跑五大模块 + 多维度聚合，输出一份完整的 JSON。
    叙事引擎和渲染引擎都读这份 JSON。
    """
    ext = external_competitiveness.analyze(employees, lookup_market_salary)
    eq = internal_equity.analyze(employees)
    pp = pay_performance.analyze(employees)
    fv = fix_variable_ratio.analyze(employees)
    lc = labor_cost.analyze(employees, sheet2_summary=sheet2_summary)

    # 职级薪酬趋势：方案 X —— 后端预聚合"公司整体" + 每个一级部门各一份，
    # 前端切换部门时本地切换数据，零额外请求。
    try:
        grade_trend_tcc = _build_grade_trend_by_department(employees, 'tcc')
        grade_trend_base = _build_grade_trend_by_department(employees, 'base')
    except Exception as e:
        print(f'[full_analysis] grade_trend failed: {e}')
        grade_trend_tcc = {'overall': {}, 'by_department': {}}
        grade_trend_base = {'overall': {}, 'by_department': {}}

    return {
        'external_competitiveness': ext,
        'internal_equity': eq,
        'pay_performance': pp,
        'fix_variable_ratio': fv,
        'labor_cost': lc,
        'grade_trend_tcc': grade_trend_tcc,
        'grade_trend_base': grade_trend_base,
        'analyzed_at': now_iso(),
        'employee_count': len([e for e in employees if e.get('base_monthly')]),
    }


def _build_grade_trend_by_department(employees: list, salary_type: str) -> dict:
    """
    方案 X：返回 {'overall': {...}, 'by_department': {部门: {...}}}。
    前端选择 '公司整体' 时读 overall；选某个部门时读 by_department[部门]。
    部门不足以画图（数据点 < 2）的就不放进 by_department，前端筛选时跳过。
    """
    overall = compute_grade_trend(employees, salary_type=salary_type)
    by_dept = {}
    departments = sorted({e.get('department') for e in employees if e.get('department')})
    for dept in departments:
        dept_emps = [e for e in employees if e.get('department') == dept]
        try:
            trend = compute_grade_trend(dept_emps, salary_type=salary_type)
            # 至少要有 2 个职级才放进部门视图，单点画不出曲线
            if trend and len(trend.get('grades', [])) >= 2:
                by_dept[dept] = trend
        except Exception as e:
            print(f'[grade_trend by_dept] {dept} failed: {e}')
    return {'overall': overall, 'by_department': by_dept}


def get_or_compute(session: dict) -> dict:
    """
    从 session 读取缓存的全量分析；不存在或过期则重新计算。
    """
    cached = session.get('_full_analysis')
    cached_at = session.get('_full_analysis_at')
    # 简单的失效判断：如果数据变过（data_version 不匹配）就重算
    data_version = _compute_data_version(session)
    if cached and cached_at and session.get('_full_analysis_version') == data_version:
        return cached

    employees = session.get('cleaned_employees') or session.get('_employees', [])
    sheet2_summary = None
    if session.get('parse_result'):
        sheet2_summary = session['parse_result'].get('sheet2_summary')

    result = compute_full_analysis(employees, sheet2_summary)
    session['_full_analysis'] = result
    session['_full_analysis_at'] = now_iso()
    session['_full_analysis_version'] = data_version
    return result


def _compute_data_version(session: dict) -> str:
    """基于关键数据字段生成简单的版本指纹。数据变化版本就变。"""
    import hashlib
    employees = session.get('cleaned_employees') or session.get('_employees', [])
    # 用员工数 + 清洗 mutation 数 + 映射状态组合
    fingerprint = (
        f'{len(employees)}'
        f':{len(session.get("_mutations", []))}'
        f':{bool(session.get("_ai_cleansing_done"))}'
        f':{bool(session.get("_grade_match_done"))}'
        f':{bool(session.get("_func_match_done"))}'
    )
    return hashlib.md5(fingerprint.encode()).hexdigest()[:12]


def invalidate(session: dict) -> None:
    """数据变化时调用：清空缓存，下次 get_or_compute 会重跑"""
    session.pop('_full_analysis', None)
    session.pop('_full_analysis_at', None)
    session.pop('_full_analysis_version', None)
