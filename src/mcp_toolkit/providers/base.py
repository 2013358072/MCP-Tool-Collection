from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from mcp_toolkit.core.logging import FastMCPLogger, get_mcp_logger

if TYPE_CHECKING:
    from fastmcp import FastMCP


class BaseProvider(ABC):
    """所有 Provider 的抽象基类。

    每个 Provider 代表一类工具集合（如文件系统、网络、邮件等），
    负责将自己的工具注册到 FastMCP 实例，并管理自身的初始化与销毁。

    子类必须实现：
        - ``name``        —— 唯一标识符（只读属性）
        - ``register``    —— 将工具挂载到 FastMCP 实例

    子类可选覆盖：
        - ``initialize``  —— 异步启动逻辑（如建立连接、加载配置）
        - ``shutdown``    —— 异步清理逻辑（如关闭连接、释放资源）
        - ``is_available``—— 运行时可用性检查（环境变量/依赖缺失等）
    """

    def __init__(self) -> None:
        self._logger: FastMCPLogger = get_mcp_logger(
            f"mcp_toolkit.providers.{self.name}"
        )
        self._initialized: bool = False

    # ------------------------------------------------------------------ #
    # 必须由子类实现                                                        #
    # ------------------------------------------------------------------ #

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 的唯一标识符，用于日志和注册表区分（如 'filesystem'、'web'）。"""

    @abstractmethod
    def register(self, mcp: "FastMCP") -> None:
        """将本 Provider 的所有工具注册到 FastMCP 实例。

        Args:
            mcp: 目标 FastMCP 实例，工具将通过 ``@mcp.tool`` 挂载到此实例。
        """

    # ------------------------------------------------------------------ #
    # 子类可选覆盖                                                          #
    # ------------------------------------------------------------------ #

    async def initialize(self) -> None:
        """异步初始化钩子，在 Provider 首次使用前调用。

        适合做以下工作：
        - 建立数据库/网络连接
        - 读取并校验配置
        - 预热缓存

        默认实现为空操作，子类按需覆盖。
        """

    async def shutdown(self) -> None:
        """异步清理钩子，在服务关闭时调用。

        适合做以下工作：
        - 关闭连接、释放资源
        - 刷新待写缓存

        默认实现为空操作，子类按需覆盖。
        """

    def is_available(self) -> bool:
        """检查当前运行环境是否满足本 Provider 的依赖条件。

        可在子类中检查必要的环境变量、第三方库或外部服务是否就绪。
        返回 False 时，``ProviderRegistry`` 会跳过该 Provider 的注册。

        默认返回 True（假设环境始终就绪）。
        """
        return True

    # ------------------------------------------------------------------ #
    # 框架内部调用（不建议子类覆盖）                                         #
    # ------------------------------------------------------------------ #

    async def _setup(self) -> None:
        """由框架调用：执行可用性检查 → 初始化 → 标记已就绪。"""
        if self._initialized:
            return

        if not self.is_available():
            self._logger.local(
                "warning",
                f"Provider '{self.name}' 不可用，跳过初始化。",
            )
            return

        self._logger.local("info", f"Provider '{self.name}' 开始初始化…")
        await self.initialize()
        self._initialized = True
        self._logger.local("info", f"Provider '{self.name}' 初始化完成。")

    async def _teardown(self) -> None:
        """由框架调用：执行清理 → 标记未就绪。"""
        if not self._initialized:
            return

        self._logger.local("info", f"Provider '{self.name}' 开始关闭…")
        await self.shutdown()
        self._initialized = False
        self._logger.local("info", f"Provider '{self.name}' 已关闭。")

    # ------------------------------------------------------------------ #
    # 通用工具                                                              #
    # ------------------------------------------------------------------ #

    @property
    def logger(self) -> FastMCPLogger:
        """返回本 Provider 专属的日志记录器。"""
        return self._logger

    @property
    def initialized(self) -> bool:
        """Provider 是否已完成初始化。"""
        return self._initialized

    def get_config(self, key: str, default: Any = None) -> Any:
        """从环境变量（经由 config 模块）读取配置项。

        子类可直接调用，避免重复导入 config。

        Args:
            key:     配置键名，对应 config.py 中的变量名。
            default: 键不存在时的回退值。
        """
        from mcp_toolkit.core import config  # 延迟导入，避免循环依赖

        return getattr(config, key, default)

    def __repr__(self) -> str:
        status = "已就绪" if self._initialized else "未初始化"
        return f"{self.__class__.__name__}(name={self.name!r}, status={status})"