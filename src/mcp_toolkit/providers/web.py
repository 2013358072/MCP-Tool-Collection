from __future__ import annotations

import asyncio
import json
import re
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp
import requests
from bs4 import BeautifulSoup
from readability import Document
from fastmcp import FastMCP

from mcp_toolkit.core import config as _cfg
from mcp_toolkit.providers.base import BaseProvider


# ======================================================================
# 内部 HTTP 工具
# ======================================================================

def _headers() -> Dict[str, str]:
    return {"User-Agent": _cfg.USER_AGENT}


def _http_get_text(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    retries: int = 2,
) -> str:
    """同步 HTTP GET，带重试。"""
    last_err: Any = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=_cfg.TIMEOUT_S, headers=_headers())
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(0.4 * (i + 1))
    raise RuntimeError(f"GET 失败: {url}，错误={last_err}")


async def _async_get_text(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    retries: int = 2,
    timeout: float = _cfg.WEB_SEARCH_TIMEOUT,
) -> str:
    """异步 HTTP GET，带重试和超时。"""
    last_err: Any = None
    async with aiohttp.ClientSession() as session:
        for i in range(retries + 1):
            try:
                async with asyncio.timeout(timeout):
                    async with session.get(url, params=params, headers=_headers()) as resp:
                        resp.raise_for_status()
                        return await resp.text()
            except asyncio.TimeoutError as e:
                last_err = f"超时: {e}"
                if i < retries:
                    await asyncio.sleep(0.4 * (i + 1))
            except Exception as e:
                last_err = e
                if i < retries:
                    await asyncio.sleep(0.4 * (i + 1))
    raise RuntimeError(f"GET 失败: {url}，错误={last_err}")


async def _async_get_json(
    url: str,
    params: Dict[str, Any],
    timeout: float = _cfg.WEB_SEARCH_TIMEOUT,
) -> Dict[str, Any]:
    txt = await _async_get_text(url, params=params, timeout=timeout)
    return json.loads(txt)


# ======================================================================
# 搜索
# ======================================================================

async def _web_search(
    query: str,
    num: int = 5,
    language: str = "zh",
    start: int = 1,
) -> Dict[str, Any]:
    """通过 SerpAPI (Bing engine) 执行网页搜索。"""
    if not _cfg.SERPAPI_KEY:
        return {"ok": False, "error": "SERPAPI_KEY 未配置"}

    num = max(1, min(int(num), 10))
    params: Dict[str, Any] = {
        "api_key": _cfg.SERPAPI_KEY,
        "q": query,
        "num": num,
        "start": max(1, int(start)),
        "hl": language,
        "engine": "bing",
    }
    try:
        data = await _async_get_json("https://serpapi.com/search", params=params)
        items = data.get("organic_results") or []
        results = [
            {
                "title": it.get("title"),
                "link": it.get("link"),
                "snippet": it.get("snippet"),
                "display_link": it.get("display_link"),
            }
            for it in items
        ]
        return {"ok": True, "query": query, "results": results}
    except asyncio.TimeoutError:
        return {"ok": False, "query": query, "error": "搜索超时"}
    except Exception as e:
        return {"ok": False, "query": query, "error": str(e)}


async def _web_search_from_doubao(
    query: str,
    num: int = 5,
    language: str = "zh",
    start: int = 1,
) -> Dict[str, Any]:
    """通过豆包 Responses API 的 web_search 工具执行网页搜索。"""
    if not _cfg.DOUBAO_API_KEY:
        return {"ok": False, "error": "DOUBAO_API_KEY 未配置"}
    if not _cfg.DOUBAO_BASE_URL:
        return {"ok": False, "error": "DOUBAO_BASE_URL 未配置"}
    if not _cfg.DOUBAO_MODEL_NAME:
        return {"ok": False, "error": "DOUBAO_MODEL_NAME 未配置"}

    num = max(1, min(int(num), 10))
    start = max(1, int(start))
    url = f"{_cfg.DOUBAO_BASE_URL.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {_cfg.DOUBAO_API_KEY}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": _cfg.DOUBAO_MODEL_NAME,
        "stream": False,
        "tools": [
            {
                "type": "web_search",
                "max_keyword": 10,
            }
        ],
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "你不需要深度思考和别的输出，只需要搜索以下内容：\n"
                            f"语言偏好：{language}\n"
                            f"查询内容：{query}"
                        ),
                    }
                ],
            }
        ],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with asyncio.timeout(_cfg.WEB_SEARCH_TIMEOUT):
                async with session.post(url, headers=headers, json=payload) as resp:
                    data = await resp.json()

        output_items = data.get("output") or []
        annotations: List[Dict[str, Any]] = []
        for item in output_items:
            for content in item.get("content") or []:
                item_annotations = content.get("annotations") or []
                for ann in item_annotations:
                    if isinstance(ann, dict):
                        annotations.append(ann)

        if not annotations:
            return {
                "ok": False,
                "query": query,
                "error": data.get("error", {}).get("message", "未获取到搜索结果"),
                "raw": data,
            }

        sliced = annotations[start - 1 : start - 1 + num]
        return {
            "ok": True,
            "query": query,
            "results": sliced,
            "total": len(annotations),
            "model": _cfg.DOUBAO_MODEL_NAME,
        }
    except asyncio.TimeoutError:
        return {"ok": False, "query": query, "error": "搜索超时"}
    except Exception as e:
        return {"ok": False, "query": query, "error": str(e)}

# ======================================================================
# 网页抓取 / 抽取
# ======================================================================

def _parse_html_text(html: str) -> str:
    """从 HTML 中提取可读正文，优先 readability，回退 BeautifulSoup。"""
    doc = Document(html)
    main_html = doc.summary(html_partial=True)
    soup = BeautifulSoup(main_html, "lxml")
    text = soup.get_text("\n", strip=True)
    if len(text) < 200:
        soup2 = BeautifulSoup(html, "lxml")
        for tag in soup2(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
            tag.decompose()
        body = soup2.body or soup2
        text = body.get_text("\n", strip=True)
    return (text or "")[: _cfg.MAX_TEXT_CHARS]


async def _web_fetch(url: str) -> Dict[str, Any]:
    """抓取网页并返回标题和正文。"""
    try:
        html = await _async_get_text(url)
        doc = Document(html)
        text = _parse_html_text(html)
        return {"ok": True, "url": url, "title": doc.short_title(), "text": text}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


async def _web_extract(url: str) -> Dict[str, Any]:
    """抓取网页并抽取结构化信息：标题、描述、正文、链接列表、图片列表。"""
    try:
        html = await _async_get_text(url)
        doc = Document(html)
        soup_full = BeautifulSoup(html, "lxml")

        title = doc.short_title()
        meta_desc = ""
        meta_tag = soup_full.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag["content"].strip()

        text = _parse_html_text(html)

        links: List[Dict[str, str]] = []
        for a in soup_full.find_all("a", href=True):
            href = a["href"].strip()
            if href and not href.startswith(("#", "javascript:")):
                links.append({"text": a.get_text(strip=True), "href": href})
            if len(links) >= 200:
                break

        images: List[Dict[str, str]] = []
        for img in soup_full.find_all("img", src=True):
            images.append({"src": img["src"], "alt": img.get("alt", "")})
            if len(images) >= 100:
                break

        return {
            "ok": True,
            "url": url,
            "title": title,
            "description": meta_desc,
            "text": text,
            "links": links,
            "images": images,
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


# ======================================================================
# 通用 HTTP 请求 / 下载
# ======================================================================

async def _http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Any] = None,
    timeout: float = _cfg.TIMEOUT_S,
) -> Dict[str, Any]:
    """通用异步 HTTP 请求，支持 GET/POST/PUT/DELETE/PATCH。"""
    req_headers = _headers()
    if headers:
        req_headers.update(headers)

    try:
        async with aiohttp.ClientSession() as session:
            async with asyncio.timeout(timeout):
                kwargs: Dict[str, Any] = {
                    "method": method.upper(),
                    "url": url,
                    "headers": req_headers,
                    "params": params,
                }
                if body is not None:
                    if isinstance(body, (dict, list)):
                        kwargs["json"] = body
                    else:
                        kwargs["data"] = str(body)

                async with session.request(**kwargs) as r:
                    content_type = r.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        try:
                            resp_body: Any = await r.json()
                        except Exception:
                            resp_body = (await r.text())[: _cfg.MAX_TEXT_CHARS]
                    else:
                        resp_body = (await r.text())[: _cfg.MAX_TEXT_CHARS]

                    return {
                        "ok": r.ok,
                        "status_code": r.status,
                        "headers": dict(r.headers),
                        "body": resp_body,
                    }
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"请求超时（{timeout}s）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _http_download(url: str, save_path: str, timeout: float = _cfg.TIMEOUT_S) -> Dict[str, Any]:
    """将远程文件流式下载到本地路径。"""
    sandbox_root = Path(_cfg.FILESYSTEM_ROOT or Path.cwd()).resolve()
    p = Path(save_path)
    if p.is_absolute():
        p = p.resolve()
        try:
            p.relative_to(sandbox_root)
        except ValueError:
            return {
                "ok": False,
                "url": url,
                "error": "SAVE_PATH_OUTSIDE_SANDBOX",
                "save_path": str(p),
                "sandbox_root": str(sandbox_root),
            }
    else:
        p = (sandbox_root / p).resolve()
    try:
        async with aiohttp.ClientSession() as session:
            async with asyncio.timeout(timeout):
                async with session.get(url, headers=_headers()) as r:
                    r.raise_for_status()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    total = 0
                    with p.open("wb") as f:
                        async for chunk in r.content.iter_chunked(64 * 1024):
                            f.write(chunk)
                            total += len(chunk)
        return {"ok": True, "url": url, "save_path": str(p.resolve()), "bytes": total}
    except asyncio.TimeoutError:
        return {"ok": False, "url": url, "error": f"下载超时（{timeout}s）"}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


# ======================================================================
# RSS / Sitemap
# ======================================================================

def _rss_fetch(url: str, max_items: int = 50) -> Dict[str, Any]:
    """拉取 RSS/Atom feed 并解析条目。"""
    try:
        xml_text = _http_get_text(url)
        root = ET.fromstring(xml_text)
    except Exception as e:
        return {"ok": False, "error": f"拉取或解析失败: {e}"}

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: List[Dict[str, Any]] = []

    # RSS 2.0
    for item in root.iter("item"):
        if len(items) >= max_items:
            break
        entry: Dict[str, Any] = {}
        for tag in ("title", "link", "description", "pubDate", "author", "guid"):
            el = item.find(tag)
            if el is not None and el.text:
                entry[tag] = el.text.strip()
        if entry:
            items.append(entry)

    # Atom
    if not items:
        for entry_el in root.findall("atom:entry", ns):
            if len(items) >= max_items:
                break
            entry = {}
            for tag, key in [
                ("atom:title", "title"),
                ("atom:summary", "description"),
                ("atom:updated", "pubDate"),
            ]:
                el = entry_el.find(tag, ns)
                if el is not None and el.text:
                    entry[key] = el.text.strip()
            link_el = entry_el.find("atom:link", ns)
            if link_el is not None:
                entry["link"] = link_el.get("href", "")
            if entry:
                items.append(entry)

    feed_title = ""
    title_el = root.find("channel/title") or root.find("atom:title", ns)
    if title_el is not None and title_el.text:
        feed_title = title_el.text.strip()

    return {"ok": True, "feed_title": feed_title, "count": len(items), "items": items}


def _sitemap_fetch(url: str, max_urls: int = 500) -> Dict[str, Any]:
    """拉取 XML sitemap 并解析 URL 列表，支持 sitemap index 一层展开。"""
    try:
        xml_text = _http_get_text(url)
        root = ET.fromstring(xml_text)
    except Exception as e:
        return {"ok": False, "error": f"拉取或解析失败: {e}"}

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: List[Dict[str, str]] = []

    def _parse_urlset(r: ET.Element) -> None:
        for url_el in r.findall("sm:url", ns):
            if len(urls) >= max_urls:
                return
            loc = url_el.find("sm:loc", ns)
            lastmod = url_el.find("sm:lastmod", ns)
            entry: Dict[str, str] = {}
            if loc is not None and loc.text:
                entry["loc"] = loc.text.strip()
            if lastmod is not None and lastmod.text:
                entry["lastmod"] = lastmod.text.strip()
            if entry:
                urls.append(entry)

    _parse_urlset(root)

    if not urls:
        for sm_el in root.findall("sm:sitemap", ns):
            if len(urls) >= max_urls:
                break
            loc = sm_el.find("sm:loc", ns)
            if loc is not None and loc.text:
                try:
                    sub_root = ET.fromstring(_http_get_text(loc.text.strip()))
                    _parse_urlset(sub_root)
                except Exception:
                    continue

    return {"ok": True, "sitemap_url": url, "count": len(urls), "urls": urls}


# ======================================================================
# URL 工具
# ======================================================================

def _url_parse(url: str) -> Dict[str, Any]:
    """解析 URL 为各组成部分。"""
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    query_flat = {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}
    return {
        "ok": True,
        "scheme": parsed.scheme,
        "host": parsed.hostname or "",
        "port": parsed.port,
        "path": parsed.path,
        "query": query_flat,
        "query_string": parsed.query,
        "fragment": parsed.fragment,
        "username": parsed.username,
        "password": parsed.password,
    }


def _url_expand(url: str, timeout: float = _cfg.TIMEOUT_S) -> Dict[str, Any]:
    """跟踪重定向链，返回最终 URL 和中间跳转记录。"""
    chain: List[str] = [url]
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout, headers=_headers())
        for resp in r.history:
            loc = resp.headers.get("Location", "")
            if loc and loc not in chain:
                chain.append(loc)
        final = r.url
        if final not in chain:
            chain.append(final)
        return {"ok": True, "original": url, "final": final, "chain": chain, "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "original": url, "error": str(e)}


# ======================================================================
# 网络诊断
# ======================================================================

def _net_ping(host: str, count: int = 4, timeout: int = 5) -> Dict[str, Any]:
    """通过 TCP connect 探测主机连通性和延迟。"""
    results: List[Dict[str, Any]] = []
    success = 0
    for i in range(count):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            start = time.time()
            sock.connect((host, 80))
            elapsed = round((time.time() - start) * 1000, 2)
            sock.close()
            results.append({"seq": i + 1, "ok": True, "time_ms": elapsed})
            success += 1
        except Exception as e:
            results.append({"seq": i + 1, "ok": False, "error": str(e)})

    return {
        "ok": success > 0,
        "host": host,
        "sent": count,
        "received": success,
        "loss_pct": round((count - success) / count * 100, 1),
        "results": results,
    }


def _net_whois(domain: str) -> Dict[str, Any]:
    """对域名执行 WHOIS 查询，返回原始文本和关键字段。"""
    def _query(server: str, q: str) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((server, 43))
        sock.sendall((q + "\r\n").encode())
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        sock.close()
        return raw.decode("utf-8", errors="replace")

    try:
        text = _query("whois.iana.org", domain)
        refer = re.search(r"refer:\s*(\S+)", text, re.I)
        if refer:
            text = _query(refer.group(1), domain)

        parsed: Dict[str, str] = {}
        for key in (
            "Domain Name", "Registrar", "Creation Date",
            "Registry Expiry Date", "Updated Date",
            "Name Server", "Registrant Organization",
        ):
            m = re.search(rf"{key}:\s*(.+)", text, re.I)
            if m:
                parsed[key.lower().replace(" ", "_")] = m.group(1).strip()

        return {"ok": True, "domain": domain, "parsed": parsed, "raw": text[:5000]}
    except Exception as e:
        return {"ok": False, "domain": domain, "error": str(e)}


def _net_dns_lookup(host: str, record_type: str = "A") -> Dict[str, Any]:
    """DNS 解析，支持 A/AAAA（socket）及其它类型（nslookup）。"""
    record_type = record_type.upper()
    try:
        if record_type == "A":
            records = sorted({addr[4][0] for addr in socket.getaddrinfo(host, None, socket.AF_INET)})
            return {"ok": True, "host": host, "type": "A", "records": records}

        if record_type == "AAAA":
            records = sorted({addr[4][0] for addr in socket.getaddrinfo(host, None, socket.AF_INET6)})
            return {"ok": True, "host": host, "type": "AAAA", "records": records}

        proc = subprocess.run(
            ["nslookup", f"-type={record_type}", host],
            capture_output=True, text=True, timeout=10,
        )
        output = proc.stdout + proc.stderr
        records_found: List[str] = []
        for line in output.splitlines():
            line = line.strip()
            if "=" in line and record_type.lower() in line.lower():
                val = line.split("=", 1)[-1].strip()
                if val:
                    records_found.append(val)
            elif record_type == "TXT" and '"' in line:
                m = re.search(r'"(.+?)"', line)
                if m:
                    records_found.append(m.group(1))

        return {"ok": True, "host": host, "type": record_type, "records": records_found, "raw": output[:3000]}
    except Exception as e:
        return {"ok": False, "host": host, "type": record_type, "error": str(e)}


# ======================================================================
# Provider
# ======================================================================

class WebProvider(BaseProvider):
    """Web 网络工具集 Provider。"""

    @property
    def name(self) -> str:
        return "web"

    def is_available(self) -> bool:
        return True

    async def initialize(self) -> None:
        self.logger.local("info", "WebProvider 初始化完成")

    def register(self, mcp: FastMCP) -> None:

        @mcp.tool()
        async def web_search(
            query: str,
            num: int = 5,
            language: str = "zh",
        ) -> Dict[str, Any]:
            """搜索引擎检索（返回候选结果列表）"""
            return await _web_search_from_doubao(query, num=num, language=language)

        @mcp.tool()
        async def web_fetch(url: str) -> Dict[str, Any]:
            """抓取网页内容（HTML/文本），返回标题和正文"""
            return await _web_fetch(url)

        @mcp.tool()
        async def web_extract(url: str) -> Dict[str, Any]:
            """从网页中抽取结构化信息（标题/正文/链接/图片等）"""
            return await _web_extract(url)

        @mcp.tool()
        async def http_request(
            method: str,
            url: str,
            headers: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, Any]] = None,
            body: Optional[Any] = None,
            timeout: float = _cfg.TIMEOUT_S,
        ) -> Dict[str, Any]:
            """通用 HTTP 请求（GET/POST/PUT/DELETE/PATCH），body 为 dict 时以 JSON 发送"""
            return await _http_request(method, url, headers=headers, params=params, body=body, timeout=timeout)

        @mcp.tool()
        async def http_download(url: str, save_path: str, timeout: float = _cfg.TIMEOUT_S) -> Dict[str, Any]:
            """下载远程文件到本地路径（流式写入）"""
            return await _http_download(url, save_path, timeout=timeout)

        # @mcp.tool()
        # async def rss_fetch(url: str, max_items: int = 50) -> Dict[str, Any]:
        #     """拉取 RSS/Atom feed 并解析条目"""
        #     return _rss_fetch(url, max_items=max_items)

        # @mcp.tool()
        # async def sitemap_fetch(url: str, max_urls: int = 500) -> Dict[str, Any]:
        #     """拉取 sitemap 并解析站点 URL 列表（支持 sitemap index）"""
        #     return _sitemap_fetch(url, max_urls=max_urls)

        @mcp.tool()
        async def url_parse(url: str) -> Dict[str, Any]:
            """解析 URL（scheme/host/path/query）"""
            return _url_parse(url)

        @mcp.tool()
        async def url_expand(url: str, timeout: float = _cfg.TIMEOUT_S) -> Dict[str, Any]:
            """展开短链/重定向，返回最终 URL 和跳转链"""
            return _url_expand(url, timeout=timeout)

        @mcp.tool()
        async def net_ping(host: str, count: int = 4, timeout: int = 5) -> Dict[str, Any]:
            """网络连通性探测（TCP connect，返回延迟和丢包率）"""
            return _net_ping(host, count=count, timeout=timeout)

        @mcp.tool()
        async def net_whois(domain: str) -> Dict[str, Any]:
            """WHOIS 查询（域名注册信息）"""
            return _net_whois(domain)

        @mcp.tool()
        async def net_dns_lookup(host: str, record_type: str = "A") -> Dict[str, Any]:
            """DNS 解析（A/AAAA/CNAME/TXT 等记录类型）"""
            return _net_dns_lookup(host, record_type=record_type)
