"""
JE (Job Evaluation) endpoints — workspace 级岗位库 + Hay 评估。

GET    /api/je/functions             列出 36 个职能（按业务大类分组）
GET    /api/je/jobs                  当前 workspace 的岗位列表
POST   /api/je/jobs                  新建 + 同步评估  {title, function, department?, jd_text}
GET    /api/je/jobs/<id>             岗位详情
PATCH  /api/je/jobs/<id>/jd          更新 JD 并重新评估  {jd_text}
PATCH  /api/je/jobs/<id>/factors     手改 8 因子重算（不调 LLM）  {factors: {...}}
DELETE /api/je/jobs/<id>             删除岗位

POST   /api/je/batches               批量评估：上传 Excel，立即返回 batch_id 供轮询
GET    /api/je/batches/<id>          查询批次状态 + 每行进度
GET    /api/je/batches               列出当前 workspace 的所有批次（最近优先）
GET    /api/je/anomalies             返回当前岗位库的职级异常告警（倒挂 / 膨胀 / 断层）
"""
import os
import tempfile
from flask import Blueprint, request, jsonify, g
from app.core.db import SessionLocal
from app.core.models import Job, JobBatch
from app.core.auth import require_auth
from app.tools.je.function_catalog import FUNCTION_CATALOG, is_valid_function
from app.tools.je.evaluator import evaluate_job, evaluate_with_factors
from app.services.je_batch import (
    parse_batch_excel, create_batch, start_batch_async, serialize_batch,
)
from app.tools.je.anomaly import detect_anomalies

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


# ============================================================================
# 批量评估
# ============================================================================

@je_bp.route('/batches', methods=['POST'])
@require_auth
def create_batch_endpoint():
    """
    上传一个 Excel，启动批量评估。
    multipart/form-data, file 字段名 'file'。

    立即返回 batch_id；评估在后台跑，前端轮询 GET /batches/<id>。
    """
    if 'file' not in request.files:
        return jsonify({'error': 'file_required', 'hint': '需要在 multipart 里附 file 字段'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'empty_file'}), 400

    # 写到临时文件让 openpyxl 解析（read_only 模式需要文件路径）
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        rows, parse_errors = parse_batch_excel(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if not rows:
        return jsonify({
            'error': 'no_valid_rows',
            'parse_errors': parse_errors,
            'hint': 'Excel 需要至少包含 "岗位名" 和 "业务职能" 两列',
        }), 400

    batch_id = create_batch(g.workspace_id, rows)
    start_batch_async(batch_id)
    return jsonify({
        'batch_id': batch_id,
        'total': len(rows),
        'parse_errors': parse_errors,
    }), 202


@je_bp.route('/batches/<batch_id>', methods=['GET'])
@require_auth
def get_batch(batch_id: str):
    db = SessionLocal()
    try:
        batch = db.query(JobBatch).filter_by(id=batch_id, workspace_id=g.workspace_id).first()
        if not batch:
            return jsonify({'error': 'not_found'}), 404
        return jsonify({'batch': serialize_batch(batch)})
    finally:
        db.close()


@je_bp.route('/anomalies', methods=['GET'])
@require_auth
def list_anomalies():
    """返回当前 workspace 的所有岗位职级异常（倒挂 / 膨胀 / 断层）。"""
    db = SessionLocal()
    try:
        jobs = db.query(Job).filter_by(workspace_id=g.workspace_id).all()
        serialized = [_serialize_job(j) for j in jobs]
        anomalies = detect_anomalies(serialized)
        return jsonify({
            'anomalies': anomalies,
            'job_count': len(jobs),
        })
    finally:
        db.close()


@je_bp.route('/batches', methods=['GET'])
@require_auth
def list_batches():
    db = SessionLocal()
    try:
        batches = (db.query(JobBatch)
                   .filter_by(workspace_id=g.workspace_id)
                   .order_by(JobBatch.created_at.desc())
                   .limit(50)
                   .all())
        return jsonify({
            'batches': [
                {
                    'id': b.id,
                    'status': b.status,
                    'total': b.total,
                    'completed': b.completed,
                    'failed': b.failed,
                    'created_at': b.created_at.isoformat() if b.created_at else None,
                    'finished_at': b.finished_at.isoformat() if b.finished_at else None,
                }
                for b in batches
            ]
        })
    finally:
        db.close()
