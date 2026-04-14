"""
存储层抽象。
- 环境变量 SUPABASE_URL + SUPABASE_KEY 都有值 → SupabaseStorage
- 否则 → MemoryStorage
用法：
    from app.storage import get_storage
    storage = get_storage()
"""
import os

_instance = None


def get_storage():
    global _instance
    if _instance is None:
        _instance = _create_storage()
    return _instance


def _create_storage():
    url = os.getenv('SUPABASE_URL', '').strip()
    key = os.getenv('SUPABASE_KEY', '').strip()
    if url and key:
        try:
            from app.storage.supabase_impl import SupabaseStorage
            s = SupabaseStorage()
            print('[Storage] Supabase connected')
            return s
        except Exception as e:
            print(f'[Storage] Supabase init failed, falling back to memory: {e}')
    from app.storage.memory import MemoryStorage
    print('[Storage] Using memory (no Supabase env)')
    return MemoryStorage()


def reset():
    """测试用：重置 storage 单例"""
    global _instance
    _instance = None
