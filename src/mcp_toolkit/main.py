from contextlib import asynccontextmanager

from fastmcp import FastMCP

from mcp_toolkit.core.logging import build_logged_tool_decorator, configure_logging
from mcp_toolkit.providers.db import DBProvider
from mcp_toolkit.providers.docs import DocsProvider
from mcp_toolkit.providers.emai import EmailProvider
from mcp_toolkit.providers.filesystem import FilesystemProvider
from mcp_toolkit.providers.finance import FinanceProvider
from mcp_toolkit.providers.maps import MapsProvider
from mcp_toolkit.providers.pdf import PDFProvider
from mcp_toolkit.providers.sheets import SheetsProvider
from mcp_toolkit.providers.shell import ShellProvider
from mcp_toolkit.providers.slides import SlidesProvider
from mcp_toolkit.providers.web import WebProvider

# 初始化日志（控制台 + 文件）
configure_logging()

# 注册所有 Provider
_providers = [
    FilesystemProvider(),
    WebProvider(),
    DocsProvider(),
    SheetsProvider(),
    SlidesProvider(),
    PDFProvider(),
    EmailProvider(),
    ShellProvider(),
    DBProvider(),
    FinanceProvider(),
    MapsProvider(),
]


@asynccontextmanager
async def _lifespan(app: FastMCP):
    """服务启动时初始化所有 Provider，关闭时统一销毁。"""
    for p in _providers:
        await p._setup()
    try:
        yield
    finally:
        for p in reversed(_providers):
            await p._teardown()


mcp = FastMCP(lifespan=_lifespan)

_original_tool_decorator = mcp.tool
for _p in _providers:
    mcp.tool = build_logged_tool_decorator(
        _original_tool_decorator,
        logger=_p.logger,
        provider_name=_p.name,
    )
    _p.register(mcp)
mcp.tool = _original_tool_decorator


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8801)
