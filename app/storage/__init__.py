"""
存储层抽象。当前默认内存实现，后续可替换为 Supabase。
用法：
    from app.storage import get_storage
    storage = get_storage()
    user = storage.get_user(user_id)
"""
from app.storage.memory import MemoryStorage

_instance = None


def get_storage():
    global _instance
    if _instance is None:
        _instance = MemoryStorage()
    return _instance
