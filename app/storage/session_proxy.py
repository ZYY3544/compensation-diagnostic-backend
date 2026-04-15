"""
Session Proxy：保持现有 sessions_store 的 dict 接口，但读写都走 storage。

关键难点：session 是 mutable dict，很多地方用 `session['key'] = value` 原地改。
我们用 TrackedDict 包装：修改时只标 dirty，flush 推迟到请求结束（after_request hook
统一调一次），避免 analyze 这种 6+ 次 setitem 的接口把整份 session 反复
deepcopy + JSON 序列化 + Supabase 上传，把 Render 512MB 直接撑爆。
"""
from typing import Optional
from app.storage import get_storage


# 不写回 storage 的 key —— 都是体积大、可由 cleaned_employees 重算的临时缓存
EPHEMERAL_KEYS = {
    '_full_analysis',
    '_full_analysis_at',
    '_full_analysis_version',
    '_code_results',
    '_employees_original',  # 仅 revert UI 用，重启后丢失可接受（重新 upload）
}


class TrackedDict(dict):
    """原地修改时只标 dirty；真正写回 storage 由 SessionsStore.flush_all_dirty 触发"""
    def __init__(self, session_id: str, data: dict):
        super().__init__(data)
        self._session_id = session_id
        self._dirty = False

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._dirty = True

    def __delitem__(self, key):
        super().__delitem__(key)
        self._dirty = True

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default  # 触发 __setitem__ → 标 dirty
        return self[key]

    def pop(self, key, *args):
        try:
            val = super().pop(key, *args)
            self._dirty = True
            return val
        except KeyError:
            if args:
                return args[0]
            raise

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._dirty = True

    def flush(self):
        """写回 storage——剥离 EPHEMERAL_KEYS 后只发瘦身后的 payload"""
        if not self._dirty:
            return
        try:
            payload = {k: v for k, v in self.items() if k not in EPHEMERAL_KEYS}
            storage = get_storage()
            storage.save_legacy_session(self._session_id, payload)
            self._dirty = False
        except Exception as e:
            print(f'[SessionProxy] flush failed for {self._session_id}: {e}')


class SessionsStore:
    """
    兼容原 sessions_store dict 的 proxy。
    - store.get(id) → 从 storage 读取，包装为 TrackedDict
    - store[id] = data → 写入 storage
    - id in store → 检查存在
    """
    def __init__(self):
        self._cache: dict[str, TrackedDict] = {}

    def get(self, session_id: str, default=None):
        if not session_id:
            return default
        if session_id in self._cache:
            return self._cache[session_id]
        storage = get_storage()
        data = storage.get_legacy_session(session_id)
        if data is None:
            return default
        tracked = TrackedDict(session_id, data)
        self._cache[session_id] = tracked
        return tracked

    def __getitem__(self, session_id: str):
        result = self.get(session_id)
        if result is None:
            raise KeyError(session_id)
        return result

    def __setitem__(self, session_id: str, data: dict):
        tracked = TrackedDict(session_id, data)
        self._cache[session_id] = tracked
        tracked._dirty = True
        tracked.flush()  # 初次写入立即落盘，不等 after_request

    def __delitem__(self, session_id: str):
        self._cache.pop(session_id, None)
        # storage 暂不支持删除 legacy session，留着不用就好

    def __contains__(self, session_id: str):
        return self.get(session_id) is not None

    def flush_all_dirty(self):
        """请求结束时由 after_request hook 调一次，把所有脏 session 一次性写回"""
        for tracked in self._cache.values():
            if tracked._dirty:
                tracked.flush()
