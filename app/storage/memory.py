"""内存存储实现。Render 重启会丢，仅供开发 + MVP 阶段使用。未来迁 Supabase。"""
from app.storage.base import BaseStorage
from typing import Optional


class MemoryStorage(BaseStorage):
    def __init__(self):
        self._users: dict[str, dict] = {}
        self._snapshots: dict[str, dict] = {}
        self._conversations: dict[str, dict] = {}
        self._invocations: dict[str, dict] = {}

    # ====== User ======
    def get_user(self, user_id: str) -> Optional[dict]:
        return self._users.get(user_id)

    def save_user(self, user: dict) -> None:
        self._users[user['user_id']] = user

    # ====== DataSnapshot ======
    def get_snapshot(self, snapshot_id: str) -> Optional[dict]:
        return self._snapshots.get(snapshot_id)

    def save_snapshot(self, snapshot: dict) -> None:
        self._snapshots[snapshot['snapshot_id']] = snapshot

    def list_snapshots_by_user(self, user_id: str) -> list:
        return sorted(
            [s for s in self._snapshots.values() if s.get('user_id') == user_id],
            key=lambda s: s.get('uploaded_at', ''),
            reverse=True,
        )

    def get_latest_snapshot(self, user_id: str) -> Optional[dict]:
        items = self.list_snapshots_by_user(user_id)
        return items[0] if items else None

    # ====== Conversation ======
    def get_conversation(self, conv_id: str) -> Optional[dict]:
        return self._conversations.get(conv_id)

    def save_conversation(self, conv: dict) -> None:
        self._conversations[conv['conv_id']] = conv

    def list_conversations_by_user(self, user_id: str) -> list:
        return sorted(
            [c for c in self._conversations.values() if c.get('user_id') == user_id],
            key=lambda c: c.get('started_at', ''),
            reverse=True,
        )

    # ====== SkillInvocation ======
    def save_invocation(self, inv: dict) -> None:
        self._invocations[inv['invocation_id']] = inv

    def list_invocations_by_conv(self, conv_id: str) -> list:
        return sorted(
            [i for i in self._invocations.values() if i.get('conv_id') == conv_id],
            key=lambda i: i.get('invoked_at', ''),
        )
