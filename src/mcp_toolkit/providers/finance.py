from __future__ import annotations

import json
from typing import Any, Dict, Literal, Optional

from fastmcp import FastMCP

from mcp_toolkit.core import config as _cfg
from mcp_toolkit.providers.base import BaseProvider

# ======================================================================
# Finance Provider —— 基于 Yahoo Finance 的金融数据工具集
# 底层依赖：yahoo-finance-server（pip install yahoo-finance-server）
# ======================================================================

Sectors = Literal[
    "basic-materials",
    "communication-services",
    "consumer-cyclical",
    "consumer-defensive",
    "energy",
    "financial-services",
    "healthcare",
    "industrials",
    "real-estate",
    "technology",
    "utilities",
]

EntityType = Literal[
    "etfs",
    "mutual_funds",
    "companies",
    "growth_companies",
    "performing_companies",
]


def _parse_result(res: Any, fallback_key: str = "data") -> Dict[str, Any]:
    """将 helper 返回的结果统一转成 dict。"""
    if isinstance(res, str):
        try:
            return json.loads(res)
        except Exception:
            return {fallback_key: res}
    if isinstance(res, dict):
        return res
    return {fallback_key: res}


# ======================================================================
# Provider
# ======================================================================


class FinanceProvider(BaseProvider):
    """Yahoo Finance 金融数据工具集 Provider。"""

    @property
    def name(self) -> str:
        return "finance"

    def is_available(self) -> bool:
        try:
            from yahoo_finance_server import helper  # noqa: F401

            return True
        except ImportError:
            return False

    async def initialize(self) -> None:
        self.logger.local("info", "FinanceProvider 初始化完成")

    def register(self, mcp: FastMCP) -> None:
        from yahoo_finance_server.helper import (
            get_ticker_info,
            get_ticker_news,
            search_yahoo_finance,
            get_top_entities,
            get_price_history,
            get_ticker_option_chain,
            get_ticker_earnings,
            get_top_etfs,
            get_top_mutual_funds,
            get_top_companies,
            get_top_growth_companies,
            get_top_performing_companies,
        )

        @mcp.tool()
        async def finance_get_ticker_info(symbol: str) -> Dict[str, Any]:
            """获取股票/证券的基础信息（公司概况、财务指标、交易数据等）。
            symbol: 股票代码（如 AAPL、TSLA、600519.SS）
            """
            res = await get_ticker_info(symbol)
            return _parse_result(res, "ticker_info")

        @mcp.tool()
        async def finance_get_ticker_news(
            symbol: str,
            count: int = 10,
        ) -> Dict[str, Any]:
            """获取指定股票的最新新闻。
            symbol: 股票代码
            count: 返回条数（默认 10）
            """
            res = await get_ticker_news(symbol, count=count)
            return _parse_result(res, "news")

        @mcp.tool()
        async def finance_search_financial_info(
            query: str,
            count: int = 10,
        ) -> Dict[str, Any]:
            """在雅虎财经搜索证券、指数等信息。
            query: 搜索关键词
            count: 返回条数（默认 10）
            """
            res = await search_yahoo_finance(query, count=count)
            return _parse_result(res, "results")

        @mcp.tool()
        async def finance_get_financial_top_entities(
            entity_type: str,
            sector: str,
            count: int = 10,
        ) -> Dict[str, Any]:
            """获取指定板块中排名靠前的实体。
            entity_type: 实体类型（etfs / mutual_funds / companies / growth_companies / performing_companies）
            sector: 板块（如 technology、healthcare、energy 等）
            count: 返回条数（默认 10）
            """
            res = await get_top_entities(entity_type=entity_type, sector=sector, count=count)
            return _parse_result(res, "entities")

        @mcp.tool()
        async def finance_get_price_history(
            symbol: str,
            period: str = "1y",
            interval: str = "1d",
        ) -> Dict[str, Any]:
            """获取历史价格数据。
            symbol: 股票代码
            period: 时间范围（1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max）
            interval: K 线周期（1m/2m/5m/15m/30m/60m/90m/1h/1d/5d/1wk/1mo/3mo）
            """
            res = await get_price_history(symbol, period=period, interval=interval)
            return _parse_result(res, "history")

        @mcp.tool()
        async def finance_get_option_chain(
            symbol: str,
            option_type: str = "both",
            date: Optional[str] = None,
        ) -> Dict[str, Any]:
            """获取期权链数据。
            symbol: 股票代码
            option_type: 期权类型（call / put / both）
            date: 到期日（YYYY-MM-DD 格式，可选）
            """
            res = await get_ticker_option_chain(symbol, option_type=option_type, date=date)
            return _parse_result(res, "options")

        @mcp.tool()
        async def finance_get_ticker_earnings(
            symbol: str,
            period: str = "annual",
        ) -> Dict[str, Any]:
            """获取公司的收益/财报数据。
            symbol: 股票代码
            period: 周期（annual / quarterly）
            """
            res = await get_ticker_earnings(symbol, period=period)
            return _parse_result(res, "earnings")

        @mcp.tool()
        async def finance_get_top_growth_companies(
            sector: str,
            count: int = 10,
        ) -> Dict[str, Any]:
            """获取指定板块中增长最快的公司。
            sector: 板块（如 technology、healthcare 等）
            count: 返回条数（默认 10）
            """
            res = await get_top_growth_companies(sector=sector, count=count)
            return _parse_result(res, "companies")

        @mcp.tool()
        async def finance_get_top_performing_companies(
            sector: str,
            count: int = 10,
        ) -> Dict[str, Any]:
            """获取指定板块中表现最好的公司。
            sector: 板块
            count: 返回条数（默认 10）
            """
            res = await get_top_performing_companies(sector=sector, count=count)
            return _parse_result(res, "companies")

        @mcp.tool()
        async def finance_get_top_etfs_by_sector(
            sector: str,
            count: int = 10,
        ) -> Dict[str, Any]:
            """获取指定板块中排名靠前的 ETF。
            sector: 板块
            count: 返回条数（默认 10）
            """
            res = await get_top_etfs(sector=sector, count=count)
            return _parse_result(res, "etfs")

        @mcp.tool()
        async def finance_get_top_mutual_funds_by_sector(
            sector: str,
            count: int = 10,
        ) -> Dict[str, Any]:
            """获取指定板块中排名靠前的共同基金。
            sector: 板块
            count: 返回条数（默认 10）
            """
            res = await get_top_mutual_funds(sector=sector, count=count)
            return _parse_result(res, "mutual_funds")

        @mcp.tool()
        async def finance_get_top_companies_by_sector(
            sector: str,
            count: int = 10,
        ) -> Dict[str, Any]:
            """获取指定板块中排名靠前的公司。
            sector: 板块
            count: 返回条数（默认 10）
            """
            res = await get_top_companies(sector=sector, count=count)
            return _parse_result(res, "companies")
