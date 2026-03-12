from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any

from mcp_toolkit.core.logging import get_mcp_logger

logger = get_mcp_logger("mcp_toolkit.core.session")


class SessionState(Enum):
    PENDING = auto()    # 已创建，尚未激活
    ACTIVE = auto()     # 使用中
    CLOSING = auto()    # 正在关闭
    CLOSED = auto()     # 已完全销毁


@dataclass
class Session:
    """单个客户端会话，持有完整的生命周期状态与时间戳。"""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict[str, Any] = field(default_factory=dict)
    state: SessionState = field(default=SessionState.PENDING, init=False)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), init=False
    )
    activated_at: datetime | None = field(default=None, init=False)
    closed_at: datetime | None = field(default=None, init=False)

    # ------------------------------------------------------------------ #
    # 生命周期状态转换                                                      #
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """将会话从 PENDING 推进到 ACTIVE，记录激活时间。"""
        if self.state is not SessionState.PENDING:
            raise SessionStateError(
                self.session_id, self.state, SessionState.ACTIVE
            )
        self.state = SessionState.ACTIVE
        self.activated_at = datetime.now(timezone.utc)

    def begin_close(self) -> None:
        """将会话标记为 CLOSING，表示正在执行清理逻辑。"""
        if self.state is not SessionState.ACTIVE:
            raise SessionStateError(
                self.session_id, self.state, SessionState.CLOSING
            )
        self.state = SessionState.CLOSING

    def finalize(self) -> None:
        """完成关闭流程，将状态置为 CLOSED 并记录关闭时间。"""
        if self.state not in (SessionState.CLOSING, SessionState.ACTIVE):
            raise SessionStateError(
                self.session_id, self.state, SessionState.CLOSED
            )
        self.state = SessionState.CLOSED
        self.closed_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------ #
    # 便捷属性                                                              #
    # ------------------------------------------------------------------ #

    @property
    def is_active(self) -> bool:
        """当前会话是否处于 ACTIVE 状态。"""
        return self.state is SessionState.ACTIVE

    @property
    def duration_seconds(self) -> float | None:
        """从激活到关闭（或到当前时刻）所经过的秒数；未激活时返回 None。"""
        if self.activated_at is None:
            return None
        end = self.closed_at or datetime.now(timezone.utc)
        return (end - self.activated_at).total_seconds()

    def __repr__(self) -> str:
        return (
            f"Session(id={self.session_id!r}, state={self.state.name}, "
            f"duration={self.duration_seconds}s)"
        )


class SessionStateError(RuntimeError):
    """尝试非法状态转换时抛出。"""

    def __init__(
        self,
        session_id: str,
        current: SessionState,
        attempted: SessionState,
    ) -> None:
        super().__init__(
            f"会话 {session_id!r}: 无法从 {current.name} 转换到 {attempted.name}"
        )
        self.session_id = session_id
        self.current = current
        self.attempted = attempted


class SessionNotFoundError(KeyError):
    """在注册表中找不到指定 session_id 时抛出。"""

    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self.session_id = session_id


class SessionManager:
    """基于 asyncio.Lock 的线程安全会话注册表，负责所有会话的创建与销毁。"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # 增删查                                                                #
    # ------------------------------------------------------------------ #

    async def create(self, metadata: dict[str, Any] | None = None) -> Session:
        """创建一个新会话并将其激活，返回已激活的 Session 对象。"""
        session = Session(metadata=metadata or {})
        async with self._lock:
            session.activate()
            self._sessions[session.session_id] = session
        logger.local("info", f"会话已创建: {session.session_id}")
        return session

    async def get(self, session_id: str) -> Session:
        """根据 session_id 查找会话；不存在时抛出 SessionNotFoundError。"""
        async with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError:
                raise SessionNotFoundError(session_id)

    async def close(self, session_id: str) -> Session:
        """优雅地关闭指定会话并将其从注册表中移除，返回已关闭的 Session 对象。"""
        async with self._lock:
            try:
                session = self._sessions[session_id]
            except KeyError:
                raise SessionNotFoundError(session_id)

            session.begin_close()
            session.finalize()
            del self._sessions[session_id]

        logger.local(
            "info",
            f"会话已关闭: {session_id} "
            f"(存活 {session.duration_seconds:.1f}s)",
        )
        return session

    async def close_all(self) -> list[Session]:
        """关闭所有已注册的会话，返回已关闭的 Session 列表。"""
        async with self._lock:
            ids = list(self._sessions.keys())

        closed: list[Session] = []
        for sid in ids:
            try:
                closed.append(await self.close(sid))
            except (SessionNotFoundError, SessionStateError):
                pass

        if closed:
            logger.local("info", f"已批量关闭 {len(closed)} 个会话。")
        return closed

    # ------------------------------------------------------------------ #
    # 查询                                                                  #
    # ------------------------------------------------------------------ #

    async def all_sessions(self) -> list[Session]:
        """返回当前所有活跃会话的快照列表。"""
        async with self._lock:
            return list(self._sessions.values())

    async def count(self) -> int:
        """返回当前活跃会话数量。"""
        async with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------ #
    # 上下文管理器                                                           #
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def lifespan(
        self, metadata: dict[str, Any] | None = None
    ) -> AsyncIterator[Session]:
        """异步上下文管理器：进入时创建并激活会话，退出时自动关闭（即使发生异常）。"""
        session = await self.create(metadata)
        try:
            yield session
        finally:
            if session.state is SessionState.ACTIVE:
                await self.close(session.session_id)


# 模块级默认管理器，无特殊隔离需求时直接使用此实例。
default_manager = SessionManager()


__all__ = [
    "Session",
    "SessionManager",
    "SessionNotFoundError",
    "SessionState",
    "SessionStateError",
    "default_manager",
]
