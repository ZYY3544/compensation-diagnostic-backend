"""
JE 批量岗位评估服务。

职责：
1. 解析上传的 Excel → rows = [{title, function, department, jd_text}, ...]
2. 在 DB 创建一个 JobBatch 记录（status=queued, items=rows）
3. 后台线程池并行评估，每条评估完成后回写 batch 状态 + 创建 Job 记录
4. 模型一致性约定：单个岗位的所有 LLM 调用走 **同一个** model；不同岗位之间 round-robin
   分发到 BATCH_MODEL_POOL，避免单点故障和速率限制

并发模型：
- ThreadPoolExecutor（IO-bound：LLM 调用）
- 每个 worker 自己 SessionLocal()，scoped_session 按线程隔离
- 启动批次的 HTTP 请求立刻返回 batch_id，前端轮询 GET /batches/<id>

为什么不用 Celery / RQ：
- v1 Render 单实例部署，多进程协调没必要
- 批次典型 50-200 条，单批 3-10 分钟，进程内 ThreadPool 够用
- 进程重启会丢未跑完的批次 → 后续可以加 retry / resume，但 v1 不做
"""
from __future__ import annotations

import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import openpyxl

from app.core.db import SessionLocal
from app.core.models import Job, JobBatch
from app.tools.je.evaluator import evaluate_job
from app.tools.je.function_catalog import is_valid_function


# 跨岗位负载均衡的模型池。env 里配 BATCH_MODEL_POOL=a,b,c 可覆盖；
# 没配就用默认 OPENROUTER_MODEL（退化为单模型，仍保留批量并行能力）
def _model_pool() -> list[Optional[str]]:
    raw = os.getenv('BATCH_MODEL_POOL', '').strip()
    if not raw:
        return [None]  # None = 用默认 OPENROUTER_MODEL
    return [m.strip() for m in raw.split(',') if m.strip()]


# 单 batch 内并发数。LLM 调用 IO 等待为主，4-8 已经够用；过高会撞 OpenRouter 速率限制
MAX_WORKERS = int(os.getenv('JE_BATCH_WORKERS', '4'))


# ---------- Excel 解析 ----------

# 列名 → 标准字段的软匹配。读到 Excel 表头后逐列做 in/== 判断
_COLUMN_ALIASES = {
    'title':      ('岗位', '职位', 'title', 'job_title', 'position'),
    'function':   ('职能', 'function', '业务职能'),
    'department': ('部门', 'dept', 'department'),
    'jd_text':    ('jd', '岗位描述', '岗位说明书', '职位描述', '说明书', 'description'),
}


def _detect_columns(header: list[str]) -> dict[str, int]:
    """把 Excel 第一行表头映射到标准字段 → 列索引；找不到的字段不进 mapping。"""
    mapping: dict[str, int] = {}
    normalized = [(i, str(h or '').strip().lower()) for i, h in enumerate(header)]
    for field, aliases in _COLUMN_ALIASES.items():
        for idx, name in normalized:
            if not name:
                continue
            if any(alias.lower() in name for alias in aliases):
                mapping[field] = idx
                break
    return mapping


def parse_batch_excel(file_path: str) -> tuple[list[dict], list[str]]:
    """
    解析批量评估 Excel。路径 B 完整版：只有岗位名是必填，其他全可选。

    字段处理逻辑：
    - title    必填
    - function 可选；缺失或非法 → 用 '通用职能' fallback，标记 function_inferred=True
    - department 可选
    - jd_text  可选；缺失 → 拼接伪 JD（仅供 LLM 提取 PK 用），标记 has_jd=False
    - has_jd / function_inferred 透传给 _evaluate_one，最终写入 Job.result.confidence

    Returns:
        (rows, errors)
        rows: [{title, function, department, jd_text, has_jd, function_inferred}, ...]
        errors: 字符串列表，每条解释一行为什么被丢弃（一般是缺岗位名）
    """
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    if len(all_rows) < 2:
        return [], ['Excel 至少需要表头 + 1 行数据']

    header = list(all_rows[0])
    mapping = _detect_columns(header)

    if 'title' not in mapping:
        return [], ['必填列未识别到：岗位名（表头需要包含"岗位"、"职位"、"title"等关键词）']

    rows: list[dict] = []
    errors: list[str] = []
    for line_no, raw in enumerate(all_rows[1:], start=2):
        title = _cell(raw, mapping.get('title'))
        function_raw = _cell(raw, mapping.get('function'))
        department = _cell(raw, mapping.get('department'))
        jd_text_raw = _cell(raw, mapping.get('jd_text'))

        if not title:
            # 整行空跳过；只有 title 缺失才报错
            if any([function_raw, department, jd_text_raw]):
                errors.append(f'第 {line_no} 行：缺少岗位名')
            continue

        # function 缺失 / 非法 → fallback "通用职能"，标记需要 LLM 推断或仅依赖名称
        function_inferred = False
        if not function_raw or not is_valid_function(function_raw):
            function = '通用职能'
            function_inferred = True
        else:
            function = function_raw.strip()

        # JD 缺失 → 用伪 JD 让 LLM 仍可提取 PK，但标记 confidence='low'
        has_jd = bool(jd_text_raw and len(jd_text_raw.strip()) >= 20)
        if has_jd:
            jd_text = jd_text_raw.strip()
        else:
            jd_text = f'（未提供详细 JD，请基于岗位名和职能做最佳推断）\n岗位名称：{title}\n业务职能：{function}'
            if department:
                jd_text += f'\n所属部门：{department}'

        rows.append({
            'title': title.strip(),
            'function': function,
            'department': (department or '').strip() or None,
            'jd_text': jd_text,
            'has_jd': has_jd,
            'function_inferred': function_inferred,
        })
    return rows, errors


def _cell(row: tuple, idx: Optional[int]) -> str:
    if idx is None or idx >= len(row):
        return ''
    v = row[idx]
    return str(v).strip() if v is not None else ''


# ---------- 批次创建 + 调度 ----------

def create_batch(workspace_id: str, rows: list[dict]) -> str:
    """在 DB 创建 JobBatch 记录，返回 batch_id。还没开始跑。"""
    db = SessionLocal()
    try:
        items = [
            {
                'index': i,
                'title': r['title'],
                'function': r['function'],
                'department': r.get('department'),
                'jd_text': r['jd_text'],
                'has_jd': r.get('has_jd', True),
                'function_inferred': r.get('function_inferred', False),
                'status': 'pending',          # pending | running | done | failed
                'job_id': None,
                'model_used': None,
                'error': None,
            }
            for i, r in enumerate(rows)
        ]
        batch = JobBatch(
            workspace_id=workspace_id,
            status='queued',
            total=len(items),
            completed=0,
            failed=0,
            items=items,
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        return batch.id
    finally:
        db.close()


def start_batch_async(batch_id: str) -> None:
    """
    起一个 daemon 线程跑这批评估。HTTP handler 调完立刻返回，前端轮询拿进度。
    """
    t = threading.Thread(target=_run_batch, args=(batch_id,), daemon=True, name=f'je-batch-{batch_id}')
    t.start()


def _run_batch(batch_id: str) -> None:
    """实际跑批的入口（在后台线程内）。"""
    db = SessionLocal()
    try:
        batch = db.query(JobBatch).filter_by(id=batch_id).first()
        if not batch:
            print(f'[je-batch] {batch_id} 不存在，放弃')
            return
        workspace_id = batch.workspace_id
        items = list(batch.items)  # 复制一份在线程内跑
        batch.status = 'running'
        db.commit()
    except Exception as e:
        print(f'[je-batch] {batch_id} 启动阶段挂了: {e}')
        return
    finally:
        db.close()

    pool = _model_pool()

    def assign_model(idx: int) -> Optional[str]:
        return pool[idx % len(pool)]

    # ---- 真正的并行评估 ----
    futures = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for item in items:
            model = assign_model(item['index'])
            item['model_used'] = model
            futures[executor.submit(_evaluate_one, workspace_id, item, model)] = item['index']

        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                outcome = fut.result()
            except Exception as e:
                outcome = {'status': 'failed', 'error': f'unexpected: {e}'}
            _persist_item_outcome(batch_id, idx, outcome)

    _finalize_batch(batch_id)


def _evaluate_one(workspace_id: str, item: dict, model: Optional[str]) -> dict:
    """
    单条评估。在 worker 线程内执行：
    - 调 evaluate_job（含 LLM PK 提取 + 规则收敛）
    - 成功 → 在 DB 落一个 Job
    - 失败 → 返回错误信息，外层负责回写 item.status

    返回结构由 _persist_item_outcome 消费，**不要**直接改 batch.items（线程冲突风险）。
    """
    try:
        eval_result = evaluate_job(
            jd_text=item['jd_text'],
            job_title=item['title'],
            function=item['function'],
            model=model,
        )
    except Exception as e:
        traceback.print_exc()
        return {'status': 'failed', 'error': str(e)[:500]}

    # 写入路径 B 的来源标记 + 置信度，让前端知道每条岗位的评估深度
    result_dict = {k: v for k, v in eval_result.items() if k != 'factors'}
    result_dict['source'] = 'list'
    result_dict['confidence'] = 'high' if item.get('has_jd') else 'low'
    result_dict['function_inferred'] = bool(item.get('function_inferred'))

    db = SessionLocal()
    try:
        job = Job(
            workspace_id=workspace_id,
            title=item['title'],
            department=item.get('department'),
            function=item['function'],
            jd_text=item['jd_text'] if item.get('has_jd') else '',
            factors=eval_result['factors'],
            result=result_dict,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return {'status': 'done', 'job_id': job.id}
    except Exception as e:
        db.rollback()
        traceback.print_exc()
        return {'status': 'failed', 'error': f'db_save_failed: {e}'}
    finally:
        db.close()


# ---------- 状态回写 ----------

# 多 worker 并发完成时，多个线程会同时改 batch.items（同一行 JSON 列）。
# SQLAlchemy 默认每个线程自己 session，commit 时按整行写回，最后一个写赢。
# 为了保证计数器和 items 同步更新不丢失，在进程内加一把锁串行化回写。
# 这一步是 IO 完成后的快速操作，锁只持有几十毫秒，不会成为瓶颈。
_persist_lock = threading.Lock()


def _persist_item_outcome(batch_id: str, item_index: int, outcome: dict) -> None:
    with _persist_lock:
        db = SessionLocal()
        try:
            batch = db.query(JobBatch).filter_by(id=batch_id).first()
            if not batch:
                return
            items = list(batch.items)
            if item_index >= len(items):
                return

            item = dict(items[item_index])
            if outcome['status'] == 'done':
                item['status'] = 'done'
                item['job_id'] = outcome.get('job_id')
                item['error'] = None
                batch.completed = (batch.completed or 0) + 1
            else:
                item['status'] = 'failed'
                item['error'] = outcome.get('error') or 'unknown'
                batch.failed = (batch.failed or 0) + 1
            items[item_index] = item

            # SQLAlchemy 不会自动检测 JSON 列内部修改，必须重新赋值整个对象
            batch.items = items
            db.commit()
        except Exception as e:
            db.rollback()
            print(f'[je-batch] persist outcome failed: {e}')
        finally:
            db.close()


def _finalize_batch(batch_id: str) -> None:
    """整批跑完，更新 status + finished_at。"""
    with _persist_lock:
        db = SessionLocal()
        try:
            batch = db.query(JobBatch).filter_by(id=batch_id).first()
            if not batch:
                return
            batch.status = 'completed'  # 含部分失败也算 completed；前端按 failed > 0 提示
            batch.finished_at = datetime.utcnow()
            db.commit()
        except Exception as e:
            db.rollback()
            print(f'[je-batch] finalize failed: {e}')
        finally:
            db.close()


# ---------- 序列化（给 API 用）----------

def serialize_batch(batch: JobBatch) -> dict:
    items = batch.items or []
    return {
        'id': batch.id,
        'status': batch.status,
        'total': batch.total,
        'completed': batch.completed,
        'failed': batch.failed,
        'progress': round((batch.completed + batch.failed) / batch.total, 3) if batch.total else 0,
        'items': [
            {
                'index': it.get('index'),
                'title': it.get('title'),
                'function': it.get('function'),
                'department': it.get('department'),
                'has_jd': it.get('has_jd', True),
                'function_inferred': it.get('function_inferred', False),
                'status': it.get('status'),
                'job_id': it.get('job_id'),
                'model_used': it.get('model_used'),
                'error': it.get('error'),
            }
            for it in items
        ],
        'error': batch.error,
        'created_at': batch.created_at.isoformat() if batch.created_at else None,
        'finished_at': batch.finished_at.isoformat() if batch.finished_at else None,
    }
