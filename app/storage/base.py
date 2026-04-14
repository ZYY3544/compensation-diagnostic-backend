"""存储层抽象接口"""
from abc import ABC, abstractmethod
from typing import Optional


class BaseStorage(ABC):
    # ====== User ======
    @abstractmethod
    def get_user(self, user_id: str) -> Optional[dict]: ...

    @abstractmethod
    def save_user(self, user: dict) -> None: ...

    # ====== DataSnapshot ======
    @abstractmethod
    def get_snapshot(self, snapshot_id: str) -> Optional[dict]: ...

    @abstractmethod
    def save_snapshot(self, snapshot: dict) -> None: ...

    @abstractmethod
    def list_snapshots_by_user(self, user_id: str) -> list: ...

    @abstractmethod
    def get_latest_snapshot(self, user_id: str) -> Optional[dict]: ...

    def invalidate_analysis(self, snapshot_id: str) -> None:
        """数据变化时清空分析结果，触发重跑"""
        snap = self.get_snapshot(snapshot_id)
        if snap:
            snap['full_analysis_json'] = None
            snap['analyzed_at'] = None
            self.save_snapshot(snap)

    # ====== Conversation ======
    @abstractmethod
    def get_conversation(self, conv_id: str) -> Optional[dict]: ...

    @abstractmethod
    def save_conversation(self, conv: dict) -> None: ...

    @abstractmethod
    def list_conversations_by_user(self, user_id: str) -> list: ...

    # ====== SkillInvocation ======
    @abstractmethod
    def save_invocation(self, inv: dict) -> None: ...

    @abstractmethod
    def list_invocations_by_conv(self, conv_id: str) -> list: ...
