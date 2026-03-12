from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Literal, Optional

import aiohttp
from fastmcp import FastMCP

from mcp_toolkit.core import config as _cfg
from mcp_toolkit.providers.base import BaseProvider

# ======================================================================
# Maps Provider —— 基于高德地图 Web 服务 API 的地图工具集
# 需要在环境变量中配置 AMAP_API_KEY
# ======================================================================


async def _amap_get(
    endpoint: str,
    params: Dict[str, Any],
    timeout: Optional[float] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """调用高德 API 并返回 JSON 结果。"""
    params["key"] = _cfg.AMAP_API_KEY
    params["output"] = "json"

    if timeout is None:
        timeout = _cfg.AMAP_TIMEOUT

    api_base = (base_url or _cfg.AMAP_BASE_URL).rstrip("/")
    url = f"{api_base}/{endpoint}"
    async with aiohttp.ClientSession() as session:
        async with asyncio.timeout(timeout):
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("status") == "1":
                    return {"ok": True, **data}
                return {
                    "ok": False,
                    "error": data.get("info", "UNKNOWN_ERROR"),
                    "infocode": data.get("infocode"),
                }


def _is_lnglat(value: str) -> bool:
    """判断字符串是否为 '经度,纬度' 格式。"""
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?", value.strip()))


def _normalize_lnglat(value: str) -> str:
    """将坐标标准化为 '经度,纬度'，移除逗号两侧空白。"""
    lng, lat = [part.strip() for part in value.split(",", 1)]
    return f"{lng},{lat}"


def _amap_v4_base_url() -> str:
    """根据当前 v3 基础地址推导 v4 地址。"""
    base = _cfg.AMAP_BASE_URL.rstrip("/")
    if base.endswith("/v3"):
        return f"{base[:-3]}/v4"
    return "https://restapi.amap.com/v4"


def _format_amap_error(error: str, infocode: Optional[str], mode: Optional[str] = None) -> str:
    """将高德错误信息转换成更适合直接展示的中文提示。"""
    if error == "OVER_DIRECTION_RANGE":
        if mode == "walking":
            return "OVER_DIRECTION_RANGE: 步行路径规划超出范围，步行模式最大支持约 100km，请缩短距离或改用驾车/公交。"
        if mode == "bicycling":
            return "OVER_DIRECTION_RANGE: 骑行路径规划超出范围，请缩短距离后重试。"
        if mode == "transit":
            return "OVER_DIRECTION_RANGE: 公交路径规划超出范围，请确认起终点城市与距离是否合理，必要时改用驾车。"
        return "OVER_DIRECTION_RANGE: 路线规划超出服务范围，请确认起终点距离或切换出行方式。"
    if error == "INVALID_PARAMS":
        return "INVALID_PARAMS: 请求参数不符合高德接口要求，请检查坐标格式、city 参数和出行方式。"
    if infocode:
        return f"{error} (infocode={infocode})"
    return error


async def _resolve_location(location: str, city: Optional[str] = None) -> str:
    """如果传入的是地址，则先通过 geocode 解析为经纬度。"""
    loc = location.strip()
    if _is_lnglat(loc):
        return _normalize_lnglat(loc)

    params: Dict[str, Any] = {"address": loc}
    if city:
        params["city"] = city
    result = await _amap_get("geocode/geo", params)
    if not result.get("ok"):
        raise ValueError(f"地址解析失败: {loc}，错误: {result.get('error', 'UNKNOWN_ERROR')}")

    geocodes = result.get("geocodes") or []
    if not geocodes or not geocodes[0].get("location"):
        raise ValueError(f"无法解析地址坐标: {loc}")
    return geocodes[0]["location"]


async def _resolve_locations(locations: str, city: Optional[str] = None) -> str:
    """解析多个位置，支持用 | 分隔的坐标或地址列表。"""
    items = [item.strip() for item in locations.split("|") if item.strip()]
    resolved = [await _resolve_location(item, city=city) for item in items]
    return "|".join(resolved)


async def _infer_city_code(location: str) -> Optional[str]:
    """从地址 geocode 结果中推断 citycode。"""
    loc = location.strip()
    if _is_lnglat(loc):
        return None

    result = await _amap_get("geocode/geo", {"address": loc})
    if not result.get("ok"):
        return None

    geocodes = result.get("geocodes") or []
    if not geocodes:
        return None

    citycode = geocodes[0].get("citycode")
    if isinstance(citycode, list):
        return citycode[0] if citycode else None
    return citycode


# ======================================================================
# Provider
# ======================================================================


class MapsProvider(BaseProvider):
    """高德地图 Web 服务工具集 Provider。"""

    @property
    def name(self) -> str:
        return "maps"

    def is_available(self) -> bool:
        return bool(_cfg.AMAP_API_KEY)

    async def initialize(self) -> None:
        self.logger.local("info", "MapsProvider 初始化完成")

    def register(self, mcp: FastMCP) -> None:

        @mcp.tool()
        async def maps_geocode(
            address: str,
            city: Optional[str] = None,
        ) -> Dict[str, Any]:
            """地址转经纬度（地理编码）。
            address: 结构化地址（如"北京市朝阳区阜通东大街6号"）
            city: 可选，指定城市以提高准确度
            """
            params: Dict[str, Any] = {"address": address}
            if city:
                params["city"] = city
            return await _amap_get("geocode/geo", params)

        @mcp.tool()
        async def maps_reverse_geocode(
            longitude: float,
            latitude: float,
            extensions: str = "base",
            radius: Optional[int] = None,
        ) -> Dict[str, Any]:
            """经纬度转地址（逆地理编码）。
            longitude: 经度
            latitude: 纬度
            extensions: base（基本信息）/ all（详细 POI、道路等）
            radius: 搜索半径（米），默认由 AMAP_DEFAULT_RADIUS 配置
            """
            params: Dict[str, Any] = {
                "location": f"{longitude},{latitude}",
                "extensions": extensions,
                "radius": radius if radius is not None else _cfg.AMAP_DEFAULT_RADIUS,
            }
            return await _amap_get("geocode/regeo", params)

        @mcp.tool()
        async def maps_search_places(
            keywords: str,
            city: Optional[str] = None,
            types: Optional[str] = None,
            page: int = 1,
            page_size: Optional[int] = None,
        ) -> Dict[str, Any]:
            """搜索地点（POI 关键词搜索）。
            keywords: 搜索关键词（如"肯德基"、"加油站"）
            city: 可选，限定城市
            types: 可选，POI 类型编码（多个用 | 分隔）
            page: 页码（默认 1）
            page_size: 每页条数，默认由 AMAP_DEFAULT_PAGE_SIZE 配置，最大 AMAP_MAX_PAGE_SIZE
            """
            if page_size is None:
                page_size = _cfg.AMAP_DEFAULT_PAGE_SIZE
            params: Dict[str, Any] = {
                "keywords": keywords,
                "page": page,
                "offset": min(page_size, _cfg.AMAP_MAX_PAGE_SIZE),
            }
            if city:
                params["city"] = city
            if types:
                params["types"] = types
            return await _amap_get("place/text", params)

        @mcp.tool()
        async def maps_search_nearby(
            longitude: float,
            latitude: float,
            keywords: Optional[str] = None,
            types: Optional[str] = None,
            radius: Optional[int] = None,
            page: int = 1,
            page_size: Optional[int] = None,
        ) -> Dict[str, Any]:
            """搜索附近地点（周边搜索）。
            longitude: 中心点经度
            latitude: 中心点纬度
            keywords: 可选，搜索关键词
            types: 可选，POI 类型编码
            radius: 搜索半径（米），默认由 AMAP_DEFAULT_RADIUS 配置，最大 AMAP_MAX_SEARCH_RADIUS
            page: 页码
            page_size: 每页条数，最大 AMAP_MAX_PAGE_SIZE
            """
            if radius is None:
                radius = _cfg.AMAP_DEFAULT_RADIUS
            if page_size is None:
                page_size = _cfg.AMAP_DEFAULT_PAGE_SIZE
            params: Dict[str, Any] = {
                "location": f"{longitude},{latitude}",
                "radius": min(radius, _cfg.AMAP_MAX_SEARCH_RADIUS),
                "page": page,
                "offset": min(page_size, _cfg.AMAP_MAX_PAGE_SIZE),
            }
            if keywords:
                params["keywords"] = keywords
            if types:
                params["types"] = types
            return await _amap_get("place/around", params)

        @mcp.tool()
        async def maps_get_place_details(
            place_id: str,
        ) -> Dict[str, Any]:
            """获取地点详情。
            place_id: POI 的唯一标识 ID
            """
            params = {"id": place_id}
            return await _amap_get("place/detail", params)

        @mcp.tool()
        async def maps_get_directions(
            origin: str,
            destination: str,
            mode: Literal["driving", "walking", "bicycling", "transit"] = "driving",
            city: Optional[str] = None,
            strategy: int = 0,
        ) -> Dict[str, Any]:
            """路线规划（驾车、步行、公交、骑行）。
            origin: 起点坐标（经度,纬度）或地址
            destination: 终点坐标或地址
            mode: 出行方式（driving / walking / bicycling / transit）
            city: 公交模式时必填，指定城市
            strategy: 策略（驾车：0-速度优先，1-费用优先，2-距离优先 等）
            """
            try:
                origin_coord = await _resolve_location(origin, city=city)
                destination_coord = await _resolve_location(destination, city=city)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

            params: Dict[str, Any] = {
                "origin": origin_coord,
                "destination": destination_coord,
            }

            if mode == "driving":
                params["strategy"] = strategy
                endpoint = "direction/driving"
            elif mode == "walking":
                endpoint = "direction/walking"
            elif mode == "bicycling":
                endpoint = "direction/bicycling"
                result = await _amap_get(endpoint, params, base_url=_amap_v4_base_url())
                if not result.get("ok"):
                    result["error"] = _format_amap_error(
                        str(result.get("error", "UNKNOWN_ERROR")),
                        result.get("infocode"),
                        mode=mode,
                    )
                result["resolved_origin"] = origin_coord
                result["resolved_destination"] = destination_coord
                return result
            elif mode == "transit":
                if not city:
                    city = await _infer_city_code(origin) or await _infer_city_code(destination)
                if not city:
                    return {"ok": False, "error": "公交模式需要指定 city 参数，或传入可解析到 citycode 的地址。"}
                params["city"] = city
                endpoint = "direction/transit/integrated"
            else:
                return {"ok": False, "error": f"不支持的出行方式: {mode}"}

            result = await _amap_get(endpoint, params)
            if not result.get("ok"):
                result["error"] = _format_amap_error(
                    str(result.get("error", "UNKNOWN_ERROR")),
                    result.get("infocode"),
                    mode=mode,
                )
            result["resolved_origin"] = origin_coord
            result["resolved_destination"] = destination_coord
            return result

        @mcp.tool()
        async def maps_get_distance(
            origins: str,
            destination: str,
            mode: Literal["driving", "walking"] = "driving",
        ) -> Dict[str, Any]:
            """计算起点到终点的距离和耗时。
            origins: 起点坐标（经度,纬度），多个起点用 | 分隔
            destination: 终点坐标（经度,纬度）
            mode: 出行方式（driving / walking）
            """
            try:
                origins_coord = await _resolve_locations(origins)
                destination_coord = await _resolve_location(destination)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

            type_map = {"driving": "1", "walking": "3"}
            params = {
                "origins": origins_coord,
                "destination": destination_coord,
                "type": type_map.get(mode, "1"),
            }
            result = await _amap_get("distance", params)
            if not result.get("ok"):
                result["error"] = _format_amap_error(
                    str(result.get("error", "UNKNOWN_ERROR")),
                    result.get("infocode"),
                    mode=mode,
                )
            result["resolved_origins"] = origins_coord
            result["resolved_destination"] = destination_coord
            return result
