"""
JE (Job Evaluation) endpoints — workspace 级岗位库 + Hay 评估。

GET    /api/je/functions             列出 36 个职能（按业务大类分组）
GET    /api/je/jobs                  当前 workspace 的岗位列表
POST   /api/je/jobs                  新建 + 同步评估  {title, function, department?, jd_text}
GET    /api/je/jobs/<id>             岗位详情
PATCH  /api/je/jobs/<id>/jd          更新 JD 并重新评估  {jd_text}
PATCH  /api/je/jobs/<id>/factors     手改 8 因子重算（不调 LLM）  {factors: {...}}
DELETE /api/je/jobs/<id>             删除岗位
"""
from flask import Blueprint, request, jsonify, g
from app.core.db import SessionLocal
from app.core.models import Job
from app.core.auth import require_auth
from app.tools.je.function_catalog import FUNCTION_CATALOG, is_valid_function
from app.tools.je.evaluator import evaluate_job, evaluate_with_factors

je_bp = Blueprint('je', __name__)


def _serialize_job(j: Job) -> dict:
    return {
        'id': j.id,
        'title': j.title,
        'department': j.department,
        'function': j.function,
        'jd_text': j.jd_text,
        'factors': j.factors,
        'result': j.result,
        'created_at': j.created_at.isoformat() if j.created_at else None,
        'updated_at': j.updated_at.isoformat() if j.updated_at else None,
    }


@je_bp.route('/functions', methods=['GET'])
@require_auth
def list_functions():
    """前端下拉用：按业务大类分组的职能字典。"""
    return jsonify({'catalog': FUNCTION_CATALOG})


@je_bp.route('/jobs', methods=['GET'])
@require_auth
def list_jobs():
    db = SessionLocal()
    try:
        jobs = (db.query(Job)
                .filter_by(workspace_id=g.workspace_id)
                .order_by(Job.created_at.desc())
                .all())
        return jsonify({'jobs': [_serialize_job(j) for j in jobs]})
    finally:
        db.close()


@je_bp.route('/jobs', methods=['POST'])
@require_auth
def create_job():
    data = request.json or {}
    title = (data.get('title') or '').strip()
    function = (data.get('function') or '').strip()
    department = (data.get('department') or '').strip() or None
    jd_text = (data.get('jd_text') or '').strip()

    if not title:
        return jsonify({'error': 'title_required'}), 400
    if not jd_text:
        return jsonify({'error': 'jd_text_required'}), 400
    if not is_valid_function(function):
        return jsonify({'error': 'function_invalid', 'hint': '必须是 function_catalog 内的职能'}), 400

    # 同步评估（v1：阻塞调用，~16s。v2 改异步队列）
    try:
        eval_result = evaluate_job(jd_text=jd_text, job_title=title, function=function)
    except Exception as e:
        return jsonify({'error': 'evaluation_failed', 'reason': str(e)}), 500

    db = SessionLocal()
    try:
        job = Job(
            workspace_id=g.workspace_id,
            title=title,
            department=department,
            function=function,
            jd_text=jd_text,
            factors=eval_result['factors'],
            result={k: v for k, v in eval_result.items() if k != 'factors'},
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return jsonify({'job': _serialize_job(job)}), 201
    finally:
        db.close()


@je_bp.route('/jobs/<job_id>', methods=['GET'])
@require_auth
def get_job(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter_by(id=job_id, workspace_id=g.workspace_id).first()
        if not job:
            return jsonify({'error': 'not_found'}), 404
        return jsonify({'job': _serialize_job(job)})
    finally:
        db.close()


@je_bp.route('/jobs/<job_id>/jd', methods=['PATCH'])
@require_auth
def update_jd(job_id: str):
    """改 JD 文本 → 重新走完整评估（含 LLM）。"""
    data = request.json or {}
    new_jd = (data.get('jd_text') or '').strip()
    if not new_jd:
        return jsonify({'error': 'jd_text_required'}), 400

    db = SessionLocal()
    try:
        job = db.query(Job).filter_by(id=job_id, workspace_id=g.workspace_id).first()
        if not job:
            return jsonify({'error': 'not_found'}), 404

        try:
            eval_result = evaluate_job(jd_text=new_jd, job_title=job.title, function=job.function)
        except Exception as e:
            return jsonify({'error': 'evaluation_failed', 'reason': str(e)}), 500

        job.jd_text = new_jd
        job.factors = eval_result['factors']
        job.result = {k: v for k, v in eval_result.items() if k != 'factors'}
        db.commit()
        db.refresh(job)
        return jsonify({'job': _serialize_job(job)})
    finally:
        db.close()


@je_bp.route('/jobs/<job_id>/factors', methods=['PATCH'])
@require_auth
def update_factors(job_id: str):
    """
    HR 反向手改某个或多个因子档位 → 重算分数（纯规则，不调 LLM）。

    Body: {factors: {practical_knowledge, ...}} —— 必须是完整的 8 因子。
    """
    data = request.json or {}
    factors = data.get('factors')
    if not isinstance(factors, dict):
        return jsonify({'error': 'factors_required'}), 400

    required = {
        'practical_knowledge', 'managerial_knowledge', 'communication',
        'thinking_challenge', 'thinking_environment',
        'freedom_to_act', 'magnitude', 'nature_of_impact',
    }
    missing = required - set(factors.keys())
    if missing:
        return jsonify({'error': 'factors_incomplete', 'missing': sorted(missing)}), 400

    db = SessionLocal()
    try:
        job = db.query(Job).filter_by(id=job_id, workspace_id=g.workspace_id).first()
        if not job:
            return jsonify({'error': 'not_found'}), 404

        try:
            eval_result = evaluate_with_factors(factors)
        except Exception as e:
            return jsonify({'error': 'evaluation_failed', 'reason': str(e)}), 400

        job.factors = eval_result['factors']
        job.result = {k: v for k, v in eval_result.items() if k != 'factors'}
        db.commit()
        db.refresh(job)
        return jsonify({'job': _serialize_job(job)})
    finally:
        db.close()


@je_bp.route('/jobs/<job_id>', methods=['DELETE'])
@require_auth
def delete_job(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter_by(id=job_id, workspace_id=g.workspace_id).first()
        if not job:
            return jsonify({'error': 'not_found'}), 404
        db.delete(job)
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()
