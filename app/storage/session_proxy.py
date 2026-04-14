"""
Session Proxy：保持现有 sessions_store 的 dict 接口，但读写都走 storage。

关键难点：session 是 mutable dict，很多地方用 `session['key'] = value` 原地改。
我们用一个 TrackedDict 包装返回值，每次修改自动触发 save。
"""
from typing import Optional
from app.storage import get_storage


class TrackedDict(dict):
    """原地修改时自动 save 回 storage"""
    def __init__(self, session_id: str, data: dict):
        super().__init__(data)
        self._session_id = session_id
        self._dirty = False

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._dirty = True
        self._flush()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._dirty = True
        self._flush()

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default  # 触发 __setitem__
        return self[key]

    def pop(self, key, *args):
        try:
            val = super().pop(key, *args)
            self._dirty = True
            self._flush()
            return val
        except KeyError:
            if args:
                return args[0]
            raise

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._dirty = True
        self._flush()

    def _flush(self):
        """立即写回 storage"""
        try:
            storage = get_storage()
            storage.save_legacy_session(self._session_id, dict(self))
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
        tracked._flush()  # 初次写入

    def __delitem__(self, session_id: str):
        self._cache.pop(session_id, None)
        # storage 暂不支持删除 legacy session，留着不用就好

    def __contains__(self, session_id: str):
        return self.get(session_id) is not None
