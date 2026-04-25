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
import traceback
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from app.core.db import SessionLocal
from app.core.models import Job, JobBatch, JeProfile
from app.core.auth import require_auth
from app.tools.je.function_catalog import FUNCTION_CATALOG, is_valid_function
from app.tools.je.evaluator import evaluate_job, evaluate_with_factors
from app.services.je_batch import (
    parse_batch_excel, create_batch, start_batch_async, serialize_batch,
)
from app.services.je_match import match_employees_to_jobs
from app.services.je_library import generate_library
from app.services.je_compare import parse_legacy_excel, compare_to_jobs
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


# ============================================================================
# 组织画像 + AI 岗位库
# ============================================================================

@je_bp.route('/profile', methods=['GET'])
@require_auth
def get_profile():
    """返回当前 workspace 的组织画像 + 岗位库（如果已经访谈过）。没有就返回 null。"""
    db = SessionLocal()
    try:
        prof = db.query(JeProfile).filter_by(workspace_id=g.workspace_id).first()
        if not prof:
            return jsonify({'profile': None, 'library': None})
        return jsonify({
            'profile': prof.profile_data,
            'library': prof.library_data,
            'created_at': prof.created_at.isoformat() if prof.created_at else None,
            'updated_at': prof.updated_at.isoformat() if prof.updated_at else None,
        })
    finally:
        db.close()


@je_bp.route('/profile', methods=['PUT'])
@require_auth
def save_profile():
    """
    保存（或更新）当前 workspace 的组织画像。
    Body: { industry, headcount, departments[], layers[], department_layers?, existing_grade_system? }

    重新写画像不会清掉 library_data —— library 由 /library/generate 显式触发更新。
    """
    data = request.json or {}
    profile_data = {
        'industry': (data.get('industry') or '').strip() or None,
        'headcount': data.get('headcount'),
        'departments': data.get('departments') or [],
        'layers': data.get('layers') or [],
        'department_layers': data.get('department_layers') or {},
        'existing_grade_system': (data.get('existing_grade_system') or '').strip() or None,
    }

    db = SessionLocal()
    try:
        prof = db.query(JeProfile).filter_by(workspace_id=g.workspace_id).first()
        if prof:
            prof.profile_data = profile_data
        else:
            prof = JeProfile(workspace_id=g.workspace_id, profile_data=profile_data)
            db.add(prof)
        db.commit()
        db.refresh(prof)
        return jsonify({
            'profile': prof.profile_data,
            'library': prof.library_data,
        })
    finally:
        db.close()


@je_bp.route('/library/generate', methods=['POST'])
@require_auth
def generate_library_endpoint():
    """
    根据当前 workspace 的组织画像调 LLM 生成 20-40 个推荐岗位。
    必须先 PUT /profile 写好画像，才能调这个端点。

    返回的 library 已经写入 DB，前端拿到后展示在岗位库面板。
    """
    db = SessionLocal()
    try:
        prof = db.query(JeProfile).filter_by(workspace_id=g.workspace_id).first()
        if not prof or not prof.profile_data:
            return jsonify({
                'error': 'profile_required',
                'hint': '需要先完成组织画像访谈（PUT /api/je/profile）才能生成岗位库。',
            }), 400

        try:
            library = generate_library(prof.profile_data)
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': 'generation_failed', 'reason': str(e)[:300]}), 500

        prof.library_data = library
        prof.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(prof)
        return jsonify({'library': prof.library_data})
    finally:
        db.close()


@je_bp.route('/library', methods=['GET'])
@require_auth
def get_library():
    """直接返回当前 workspace 已生成的岗位库（不重新调 LLM）。"""
    db = SessionLocal()
    try:
        prof = db.query(JeProfile).filter_by(workspace_id=g.workspace_id).first()
        if not prof or not prof.library_data:
            return jsonify({'library': None})
        return jsonify({'library': prof.library_data})
    finally:
        db.close()


@je_bp.route('/functions', methods=['GET'])
@require_auth
def list_functions():
    """前端下拉用：按业务大类分组的职能字典。"""
    return jsonify({'catalog': FUNCTION_CATALOG})


@je_bp.route('/jobs/from-library', methods=['POST'])
@require_auth
def create_job_from_library():
    """
    从 AI 岗位库的某个 entry 创建一个 Job 记录。

    Body: {
      lib_id: 'lib_3',                 # library_data.entries[].id
      title?: '产品经理-用户增长方向',  # 可选，覆盖 entry.name
      department?: '产品部',           # 可选，覆盖 entry.department
    }

    后端用 entry 自带的 8 因子调 evaluate_with_factors 算分数 + 职级，
    存到 jobs 表（不调 LLM，毫秒级）。新建岗位的 jd_text 留空字符串
    （表示从库选的，没有 JD），后续用户可在详情页补 JD 触发精细评估。
    """
    data = request.json or {}
    lib_id = (data.get('lib_id') or '').strip()
    if not lib_id:
        return jsonify({'error': 'lib_id_required'}), 400

    db = SessionLocal()
    try:
        prof = db.query(JeProfile).filter_by(workspace_id=g.workspace_id).first()
        if not prof or not prof.library_data:
            return jsonify({'error': 'library_not_found',
                            'hint': '当前 workspace 还没有生成岗位库，请先完成访谈。'}), 400

        entries = (prof.library_data or {}).get('entries') or []
        entry = next((e for e in entries if e.get('id') == lib_id), None)
        if not entry:
            return jsonify({'error': 'lib_entry_not_found', 'lib_id': lib_id}), 404

        title = (data.get('title') or entry.get('name') or '').strip()
        department = (data.get('department') or entry.get('department') or '').strip() or None
        function = entry.get('function') or '通用职能'
        if not title:
            return jsonify({'error': 'title_required'}), 400
        if not is_valid_function(function):
            function = '通用职能'

        factors = entry.get('factors') or {}
        try:
            scored = evaluate_with_factors(factors)
        except Exception as e:
            return jsonify({'error': 'invalid_factors', 'reason': str(e)[:300]}), 400

        # 跟 evaluate_job 返回结构对齐：result 里去掉 factors（在 Job.factors 列已存）
        result = {k: v for k, v in scored.items() if k != 'factors'}
        # 标记来源信息，方便前端推断"待校准"状态（factors 跟 lib 完全一致 → 用户还没改过）
        result['source'] = 'library'
        result['lib_id'] = lib_id
        result['lib_factors'] = dict(factors)   # 复制一份原始档位作为基线

        job = Job(
            workspace_id=g.workspace_id,
            title=title,
            department=department,
            function=function,
            jd_text='',   # 库选没 JD；用户后续可"上传 JD 精细评估"补
            factors=factors,
            result=result,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return jsonify({'job': _serialize_job(job)}), 201
    finally:
        db.close()


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

    # 标记 source='single'，前端用来判断"路径 A 累积 5 个时触发升级提示"
    result_dict = {k: v for k, v in eval_result.items() if k != 'factors'}
    result_dict['source'] = 'single'

    db = SessionLocal()
    try:
        job = Job(
            workspace_id=g.workspace_id,
            title=title,
            department=department,
            function=function,
            jd_text=jd_text,
            factors=eval_result['factors'],
            result=result_dict,
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

        # 保留来源标记（source / lib_id / lib_factors），让前端能区分
        # "刚从库选的没改过" vs "用户校准过"两种状态
        prev_result = job.result or {}
        new_result = {k: v for k, v in eval_result.items() if k != 'factors'}
        for keep in ('source', 'lib_id', 'lib_factors'):
            if keep in prev_result:
                new_result[keep] = prev_result[keep]
        # 用户改过因子 → 标记 verified（前端"已校准"状态）
        new_result['verified'] = True

        job.factors = eval_result['factors']
        job.result = new_result
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


@je_bp.route('/match', methods=['GET'])
@require_auth
def match_to_session():
    """
    人岗匹配：取一个 session 的员工数据，跟当前 workspace 的 JE 岗位库连起来。

    Query: ?session_id=<id>

    没传 session_id 时尝试取当前 workspace 最新一个有员工数据的 session 兜底。
    """
    session_id = request.args.get('session_id', '').strip()

    from app.api.sessions import sessions_store

    if not session_id:
        return jsonify({
            'error': 'session_id_required',
            'hint': '请在主诊断里复制当前 session_id（浏览器 URL 或 localStorage 里都能看到），粘贴到上方输入框后再做人岗匹配。',
        }), 400

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'session_not_found', 'session_id': session_id}), 404
    if session.get('workspace_id') and session['workspace_id'] != g.workspace_id:
        return jsonify({'error': 'forbidden'}), 403

    employees = session.get('cleaned_employees') or session.get('_employees') or []
    if not employees:
        return jsonify({
            'error': 'session_has_no_employees',
            'session_id': session.get('id'),
            'hint': '这个 session 还没有解析出员工数据。请先完成主诊断的数据上传 + 字段映射。',
        }), 400

    grade_mapping = (session.get('_grade_match_result') or {}).get('grade_mapping') or {}

    db = SessionLocal()
    try:
        jobs = db.query(Job).filter_by(workspace_id=g.workspace_id).all()
        serialized = [_serialize_job(j) for j in jobs]
    finally:
        db.close()

    if not serialized:
        return jsonify({
            'error': 'no_jobs',
            'hint': '当前 workspace 还没有 JE 岗位。请先批量上传或单评几个岗位。',
        }), 400

    result = match_employees_to_jobs(employees, serialized, grade_mapping=grade_mapping)
    result['session_id'] = session.get('id')
    return jsonify(result)


@je_bp.route('/compare', methods=['POST'])
@require_auth
def compare_legacy_system():
    """
    上传现行职级体系 Excel，跟当前 workspace 的 AI 评估岗位做对比。

    multipart/form-data, file 字段。Excel 至少含"岗位名"+"职级"两列。
    职级支持 G12 / 12 / Hay 12 这类含数字格式；P 序列等需要用户先换算。
    """
    if 'file' not in request.files:
        return jsonify({'error': 'file_required'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'empty_file'}), 400

    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        legacy_rows, parse_errors = parse_legacy_excel(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if not legacy_rows:
        return jsonify({
            'error': 'no_valid_rows',
            'parse_errors': parse_errors,
            'hint': 'Excel 至少需要"岗位名"和"职级"两列',
        }), 400

    db = SessionLocal()
    try:
        jobs = db.query(Job).filter_by(workspace_id=g.workspace_id).all()
        serialized = [_serialize_job(j) for j in jobs]
    finally:
        db.close()

    if not serialized:
        return jsonify({
            'error': 'no_jobs',
            'hint': '当前 workspace 还没有 AI 评估的岗位，先评估几个再来对比',
        }), 400

    report = compare_to_jobs(legacy_rows, serialized)
    report['parse_errors'] = parse_errors
    return jsonify(report)


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
