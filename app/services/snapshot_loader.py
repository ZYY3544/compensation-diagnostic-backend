"""
post-confirmation endpoint 的数据加载助手：优先从 data_snapshots 表读，
session 内存只作 fallback。

设计意图：让 analyze 之后的接口（diagnosis-summary / module-insight /
diagnosis-advice / export-pdf）不再依赖长生命周期的 in-memory session 来
持有大块数据。session 只留 KB 级工作流状态，MB 级业务数据走 DB。

返回的对象生命周期是请求级——caller 用完就 GC，不要再写回 session。
"""
from typing import Optional


def _read_snapshot(snapshot_id: str) -> dict:
    """从 storage 读 snapshot；任何错误都返回空 dict 让 caller 走 fallback"""
    try:
        from app.storage import get_storage
        return get_storage().get_snapshot(snapshot_id) or {}
    except Exception as e:
        print(f'[snapshot_loader] read failed for {snapshot_id}: {e}')
        return {}


def load_cleaned_employees(snapshot_id: str, session: Optional[dict] = None) -> list:
    """优先 DB，fallback 到 in-memory session（兼容尚未持久化的请求）"""
    snap = _read_snapshot(snapshot_id)
    emps = snap.get('cleaned_employees')
    if emps:
        return emps
    if session is not None:
        return session.get('cleaned_employees') or session.get('_employees', []) or []
    return []


def load_analysis_results(snapshot_id: str, session: Optional[dict] = None) -> Optional[dict]:
    """优先 DB，fallback 到 in-memory session"""
    snap = _read_snapshot(snapshot_id)
    report = snap.get('analysis_results')
    if report:
        return report
    if session is not None:
        return session.get('analysis_results')
    return None


def load_interview_notes(snapshot_id: str, session: Optional[dict] = None) -> dict:
    """优先 DB，fallback 到 session"""
    snap = _read_snapshot(snapshot_id)
    notes = snap.get('interview_notes')
    if notes:
        return notes
    if session is not None:
        return session.get('interview_notes', {}) or {}
    return {}
