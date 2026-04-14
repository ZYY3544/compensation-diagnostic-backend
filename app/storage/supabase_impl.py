"""
Supabase 存储实现。
启用条件：环境变量 SUPABASE_URL 和 SUPABASE_KEY 都有值。
"""
import os
from typing import Optional
from app.storage.base import BaseStorage


class SupabaseStorage(BaseStorage):
    def __init__(self):
        from supabase import create_client
        url = os.getenv('SUPABASE_URL', '').strip()
        key = os.getenv('SUPABASE_KEY', '').strip()
        if not url or not key:
            raise RuntimeError('SUPABASE_URL / SUPABASE_KEY not set')
        self.client = create_client(url, key)

    # ====== User ======
    def get_user(self, user_id: str) -> Optional[dict]:
        r = self.client.table('users').select('*').eq('user_id', user_id).limit(1).execute()
        return r.data[0] if r.data else None

    def save_user(self, user: dict) -> None:
        self.client.table('users').upsert(user, on_conflict='user_id').execute()

    # ====== DataSnapshot ======
    def get_snapshot(self, snapshot_id: str) -> Optional[dict]:
        r = self.client.table('data_snapshots').select('*').eq('snapshot_id', snapshot_id).limit(1).execute()
        return r.data[0] if r.data else None

    def save_snapshot(self, snapshot: dict) -> None:
        # Supabase 列名不允许下划线前缀，但我们 schema 里已经去掉了前缀，这里统一
        cleaned = {k.lstrip('_'): v for k, v in snapshot.items()}
        self.client.table('data_snapshots').upsert(cleaned, on_conflict='snapshot_id').execute()

    def list_snapshots_by_user(self, user_id: str) -> list:
        r = self.client.table('data_snapshots').select('*').eq('user_id', user_id).order('uploaded_at', desc=True).execute()
        return r.data or []

    def get_latest_snapshot(self, user_id: str) -> Optional[dict]:
        r = self.client.table('data_snapshots').select('*').eq('user_id', user_id).order('uploaded_at', desc=True).limit(1).execute()
        return r.data[0] if r.data else None

    # ====== Conversation ======
    def get_conversation(self, conv_id: str) -> Optional[dict]:
        r = self.client.table('conversations').select('*').eq('conv_id', conv_id).limit(1).execute()
        return r.data[0] if r.data else None

    def save_conversation(self, conv: dict) -> None:
        self.client.table('conversations').upsert(conv, on_conflict='conv_id').execute()

    def list_conversations_by_user(self, user_id: str) -> list:
        r = self.client.table('conversations').select('*').eq('user_id', user_id).order('started_at', desc=True).execute()
        return r.data or []

    # ====== SkillInvocation ======
    def save_invocation(self, inv: dict) -> None:
        self.client.table('skill_invocations').insert(inv).execute()

    def list_invocations_by_conv(self, conv_id: str) -> list:
        r = self.client.table('skill_invocations').select('*').eq('conv_id', conv_id).order('invoked_at').execute()
        return r.data or []

    # ====== Legacy session (迁移期间使用) ======
    def get_legacy_session(self, session_id: str) -> Optional[dict]:
        r = self.client.table('sessions_legacy').select('data').eq('session_id', session_id).limit(1).execute()
        return r.data[0]['data'] if r.data else None

    def save_legacy_session(self, session_id: str, data: dict) -> None:
        from datetime import datetime
        payload = {
            'session_id': session_id,
            'updated_at': datetime.utcnow().isoformat(),
            'data': _make_jsonable(data),
        }
        self.client.table('sessions_legacy').upsert(payload, on_conflict='session_id').execute()


def _make_jsonable(obj):
    """确保对象可以序列化到 JSONB"""
    import datetime
    if isinstance(obj, dict):
        return {str(k): _make_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_jsonable(v) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    # 其他类型尽力转字符串
    try:
        import json
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
