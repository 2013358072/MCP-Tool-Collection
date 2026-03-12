from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Literal, Protocol

IncomingMCPLevel = Literal[
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
    "alert",
    "emergency",
]
OutgoingMCPLevel = Literal["debug", "info", "warning", "error"]

from mcp_toolkit.core import config as _cfg

DEFAULT_LOGGER_NAME = "mcp_toolkit"
DEFAULT_LOG_FORMAT: str = _cfg.LOG_FORMAT
DEFAULT_DATE_FORMAT: str = _cfg.LOG_DATE_FORMAT
DEFAULT_LOG_DIR: Path = _cfg.LOG_DIR
DEFAULT_LOG_FILENAME: str = _cfg.LOG_FILENAME
DEFAULT_MAX_BYTES: int = _cfg.LOG_MAX_BYTES
DEFAULT_BACKUP_COUNT: int = _cfg.LOG_BACKUP_COUNT

MCP_TO_PYTHON_LEVEL: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "alert": logging.CRITICAL,
    "emergency": logging.CRITICAL,
}


class SupportsMCPContext(Protocol):
    async def log(
        self,
        level: OutgoingMCPLevel,
        message: str,
        logger_name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None: ...

    async def debug(
        self,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None: ...

    async def info(
        self,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None: ...

    async def warning(
        self,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None: ...

    async def error(
        self,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None: ...


def add_file_handler(
    logger: logging.Logger | None = None,
    *,
    filename: str = DEFAULT_LOG_FILENAME,
    log_dir: Path | str | None = None,
    level: int | str = logging.DEBUG,
    log_format: str = DEFAULT_LOG_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    encoding: str = "utf-8",
) -> RotatingFileHandler:
    """Attach a RotatingFileHandler to *logger* (or the root logger).

    The target directory is created automatically if it does not exist.
    Returns the handler so callers can further customise or remove it.
    """
    target_dir = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    log_path = target_dir / filename

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding=encoding,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt=log_format, datefmt=date_format))

    target_logger = logger if logger is not None else logging.getLogger()
    target_logger.addHandler(handler)
    return handler


def configure_logging(
    level: int | str = logging.INFO,
    *,
    logger_name: str = DEFAULT_LOGGER_NAME,
    log_format: str = DEFAULT_LOG_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
    force: bool = False,
    log_file: str | None = DEFAULT_LOG_FILENAME,
    log_dir: Path | str | None = DEFAULT_LOG_DIR,
    file_level: int | str = logging.DEBUG,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> logging.Logger:
    """Configure the standard Python logging system.

    Console output is set to *level*.  When *log_file* is not ``None`` a
    rotating file handler is also attached to the returned logger writing to
    ``<log_dir>/<log_file>`` at *file_level* (defaults to DEBUG so the file
    captures more detail than the console).  Pass ``log_file=None`` to disable
    file logging entirely.
    """
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        force=force,
    )
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    if log_file is not None:
        add_file_handler(
            logger,
            filename=log_file,
            log_dir=log_dir,
            level=file_level,
            log_format=log_format,
            date_format=date_format,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a standard Python logger for the project."""

    return logging.getLogger(name or DEFAULT_LOGGER_NAME)


def get_mcp_logger(name: str | None = None) -> "FastMCPLogger":
    """Return a helper that can log locally and to a FastMCP client."""

    return FastMCPLogger(name=name or DEFAULT_LOGGER_NAME)


def _normalize_message(message: Any) -> str:
    return "" if message is None else str(message)


def _normalize_extra(extra: Any) -> dict[str, Any] | None:
    if extra is None:
        return None
    if isinstance(extra, Mapping):
        return dict(extra)
    return {"value": extra}


def _record_extra(
    extra: dict[str, Any] | None,
    *,
    source_logger: str | None = None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if source_logger:
        payload["mcp_logger"] = source_logger
    if extra:
        payload["mcp_extra"] = extra
    return payload or None


def _display_message(
    message: str,
    *,
    source_logger: str | None,
    target_logger: logging.Logger,
) -> str:
    if not source_logger or source_logger == target_logger.name:
        return message
    return f"[{source_logger}] {message}"


def _local_log(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    extra: dict[str, Any] | None = None,
    source_logger: str | None = None,
    exc_info: Any = None,
) -> None:
    kwargs: dict[str, Any] = {}
    record_extra = _record_extra(extra, source_logger=source_logger)
    if record_extra is not None:
        kwargs["extra"] = record_extra
    if exc_info is not None:
        kwargs["exc_info"] = exc_info

    logger.log(
        level,
        _display_message(
            message,
            source_logger=source_logger,
            target_logger=logger,
        ),
        **kwargs,
    )


async def emit_client_log(
    ctx: SupportsMCPContext | None,
    level: OutgoingMCPLevel,
    message: str,
    *,
    logger_name: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Send a log message to the MCP client if a context is available."""

    if ctx is None:
        return

    normalized_message = _normalize_message(message)
    normalized_extra = _normalize_extra(extra)

    if logger_name is not None:
        await ctx.log(
            level,
            normalized_message,
            logger_name=logger_name,
            extra=normalized_extra,
        )
        return

    if level == "debug":
        await ctx.debug(normalized_message, extra=normalized_extra)
    elif level == "info":
        await ctx.info(normalized_message, extra=normalized_extra)
    elif level == "warning":
        await ctx.warning(normalized_message, extra=normalized_extra)
    else:
        await ctx.error(normalized_message, extra=normalized_extra)


async def forward_log_message(
    message: Any,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Forward FastMCP client log messages into Python logging."""

    payload = message.data if isinstance(message.data, Mapping) else {}
    source_logger = message.logger
    target_logger = logger or get_logger(source_logger or "fastmcp.server")

    _local_log(
        target_logger,
        MCP_TO_PYTHON_LEVEL.get(message.level.lower(), logging.INFO),
        _normalize_message(payload.get("msg")),
        extra=_normalize_extra(payload.get("extra")),
        source_logger=source_logger,
    )


def _tool_result_log_level_and_message(
    tool_name: str,
    result: Any,
) -> tuple[str, str]:
    """根据工具返回值生成日志级别和摘要消息。"""
    if isinstance(result, Mapping):
        if result.get("ok") is False:
            error = result.get("error") or result.get("detail") or "UNKNOWN_ERROR"
            return "warning", f"工具调用失败: {tool_name} | error={error}"
        if result.get("ok") is True:
            return "info", f"工具调用成功: {tool_name}"
    return "info", f"工具调用完成: {tool_name}"


def build_logged_tool_decorator(
    tool_decorator: Callable[..., Any],
    *,
    logger: "FastMCPLogger",
    provider_name: str,
) -> Callable[..., Any]:
    """包装 FastMCP 的 tool 装饰器，为所有工具调用添加开始/成功/失败日志。"""

    def logged_tool(*decorator_args: Any, **decorator_kwargs: Any) -> Any:
        base_decorator = tool_decorator(*decorator_args, **decorator_kwargs)

        def apply_wrapper(fn: Callable[..., Any]) -> Any:
            tool_name = f"{provider_name}.{fn.__name__}"

            if inspect.iscoroutinefunction(fn):

                @wraps(fn)
                async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                    logger.local("info", f"工具调用开始: {tool_name}")
                    try:
                        result = await fn(*args, **kwargs)
                        level, message = _tool_result_log_level_and_message(tool_name, result)
                        logger.local(level, message)
                        return result
                    except Exception:
                        logger.exception(f"工具调用异常: {tool_name}")
                        raise

                return base_decorator(async_wrapped)

            @wraps(fn)
            def sync_wrapped(*args: Any, **kwargs: Any) -> Any:
                logger.local("info", f"工具调用开始: {tool_name}")
                try:
                    result = fn(*args, **kwargs)
                    level, message = _tool_result_log_level_and_message(tool_name, result)
                    logger.local(level, message)
                    return result
                except Exception:
                    logger.local("error", f"工具调用异常: {tool_name}", exc_info=True)
                    raise

            return base_decorator(sync_wrapped)

        return apply_wrapper

    return logged_tool


def build_client_log_handler(
    name: str = "fastmcp.client",
) -> Callable[[Any], Awaitable[None]]:
    """Create a FastMCP client log_handler compatible callback."""

    client_logger = get_logger(name)

    async def log_handler(message: Any) -> None:
        await forward_log_message(message, logger=client_logger)

    return log_handler


@dataclass(slots=True)
class FastMCPLogger:
    """Small helper that unifies local logging and client-visible logging."""

    name: str = DEFAULT_LOGGER_NAME
    logger: logging.Logger = field(init=False)

    def __post_init__(self) -> None:
        self.logger = get_logger(self.name)

    def child(self, suffix: str) -> "FastMCPLogger":
        return FastMCPLogger(name=f"{self.name}.{suffix}")

    def local(
        self,
        level: int | IncomingMCPLevel | OutgoingMCPLevel,
        message: str,
        *,
        extra: Mapping[str, Any] | None = None,
        exc_info: Any = None,
    ) -> None:
        normalized_level = (
            level if isinstance(level, int) else MCP_TO_PYTHON_LEVEL.get(level, logging.INFO)
        )
        _local_log(
            self.logger,
            normalized_level,
            _normalize_message(message),
            extra=_normalize_extra(extra),
            source_logger=self.name,
            exc_info=exc_info,
        )

    async def log(
        self,
        level: OutgoingMCPLevel,
        message: str,
        *,
        ctx: SupportsMCPContext | None = None,
        extra: Mapping[str, Any] | None = None,
        logger_name: str | None = None,
        also_local: bool = True,
    ) -> None:
        normalized_message = _normalize_message(message)
        normalized_extra = _normalize_extra(extra)
        source_logger = logger_name or self.name

        if also_local:
            _local_log(
                self.logger,
                MCP_TO_PYTHON_LEVEL[level],
                normalized_message,
                extra=normalized_extra,
                source_logger=source_logger,
            )

        await emit_client_log(
            ctx,
            level,
            normalized_message,
            logger_name=source_logger,
            extra=normalized_extra,
        )

    async def debug(
        self,
        message: str,
        *,
        ctx: SupportsMCPContext | None = None,
        extra: Mapping[str, Any] | None = None,
        also_local: bool = True,
    ) -> None:
        await self.log("debug", message, ctx=ctx, extra=extra, also_local=also_local)

    async def info(
        self,
        message: str,
        *,
        ctx: SupportsMCPContext | None = None,
        extra: Mapping[str, Any] | None = None,
        also_local: bool = True,
    ) -> None:
        await self.log("info", message, ctx=ctx, extra=extra, also_local=also_local)

    async def warning(
        self,
        message: str,
        *,
        ctx: SupportsMCPContext | None = None,
        extra: Mapping[str, Any] | None = None,
        also_local: bool = True,
    ) -> None:
        await self.log("warning", message, ctx=ctx, extra=extra, also_local=also_local)

    async def error(
        self,
        message: str,
        *,
        ctx: SupportsMCPContext | None = None,
        extra: Mapping[str, Any] | None = None,
        also_local: bool = True,
    ) -> None:
        await self.log("error", message, ctx=ctx, extra=extra, also_local=also_local)

    async def exception(
        self,
        message: str,
        *,
        ctx: SupportsMCPContext | None = None,
        extra: Mapping[str, Any] | None = None,
        also_local: bool = True,
    ) -> None:
        normalized_message = _normalize_message(message)
        normalized_extra = _normalize_extra(extra)

        if also_local:
            _local_log(
                self.logger,
                logging.ERROR,
                normalized_message,
                extra=normalized_extra,
                source_logger=self.name,
                exc_info=True,
            )

        await emit_client_log(
            ctx,
            "error",
            normalized_message,
            logger_name=self.name,
            extra=normalized_extra,
        )


__all__ = [
    "DEFAULT_BACKUP_COUNT",
    "DEFAULT_DATE_FORMAT",
    "DEFAULT_LOG_DIR",
    "DEFAULT_LOG_FILENAME",
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_LOGGER_NAME",
    "DEFAULT_MAX_BYTES",
    "FastMCPLogger",
    "MCP_TO_PYTHON_LEVEL",
    "add_file_handler",
    "build_client_log_handler",
    "build_logged_tool_decorator",
    "configure_logging",
    "emit_client_log",
    "forward_log_message",
    "get_logger",
    "get_mcp_logger",
]
