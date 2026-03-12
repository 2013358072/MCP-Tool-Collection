from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastmcp import FastMCP

from mcp_toolkit.providers.base import BaseProvider

# ======================================================================
# 沙箱根目录
# 优先读取环境变量 FILESYSTEM_ROOT；未设置时回退到 ACCESS_PATH_LIST 首项；
# 最终兜底为当前工作目录。
# ======================================================================

def _build_root() -> Path:
    from mcp_toolkit.core.config import ACCESS_PATH_LIST, FILESYSTEM_ROOT
    if FILESYSTEM_ROOT:
        return Path(FILESYSTEM_ROOT).resolve()
    if ACCESS_PATH_LIST:
        return Path(ACCESS_PATH_LIST.split(",")[0].strip()).resolve()
    return Path.cwd()

ROOT: Path = _build_root()


class FSAccessError(PermissionError):
    """路径越出沙箱根目录时抛出。"""


# ======================================================================
# 内部工具函数
# ======================================================================

def _resolve(p: Union[str, Path]) -> Path:
    """将路径解析为绝对路径，并强制其保持在 ROOT 内部。"""
    p = Path(p)
    abs_p = (ROOT / p).resolve() if not p.is_absolute() else p.resolve()
    try:
        abs_p.relative_to(ROOT)
    except ValueError:
        raise FSAccessError(f"路径越出沙箱: {abs_p}（ROOT={ROOT}）")
    return abs_p


def _mkparent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------- #
# 文件元信息
# ---------------------------------------------------------------------- #

@dataclass
class _FileInfo:
    path: str
    name: str
    is_file: bool
    is_dir: bool
    size_bytes: int
    suffix: str
    modified_time: float
    created_time: float


def _stat(path: Union[str, Path]) -> Dict[str, Any]:
    p = _resolve(path)
    if not p.exists():
        return {"ok": False, "error": "NOT_FOUND", "path": str(p)}
    st = p.stat()
    info = _FileInfo(
        path=str(p),
        name=p.name,
        is_file=p.is_file(),
        is_dir=p.is_dir(),
        size_bytes=st.st_size if p.is_file() else 0,
        suffix=p.suffix.lower(),
        modified_time=st.st_mtime,
        created_time=st.st_ctime,
    )
    return {"ok": True, "data": asdict(info)}


# ---------------------------------------------------------------------- #
# 读写
# ---------------------------------------------------------------------- #

def _read_file(
    path: Union[str, Path],
    encoding: str = "utf-8",
    max_chars: Optional[int] = None,
) -> Dict[str, Any]:
    p = _resolve(path)
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": "NOT_FOUND", "path": str(p)}
    try:
        text = p.read_text(encoding=encoding, errors="replace")
        if max_chars is not None:
            text = text[:max_chars]
        return {"ok": True, "path": str(p), "content": text, "size_bytes": p.stat().st_size}
    except Exception as e:
        return {"ok": False, "error": "READ_FAILED", "path": str(p), "detail": str(e)}


def _write_text(
    path: Union[str, Path],
    content: str,
    encoding: str = "utf-8",
    overwrite: bool = True,
) -> Dict[str, Any]:
    p = _resolve(path)
    if p.exists() and not overwrite:
        return {"ok": False, "error": "ALREADY_EXISTS", "path": str(p)}
    try:
        _mkparent(p)
        p.write_text(content, encoding=encoding)
        return {"ok": True, "path": str(p), "bytes_written": p.stat().st_size}
    except Exception as e:
        return {"ok": False, "error": "WRITE_FAILED", "path": str(p), "detail": str(e)}


def _write_json(
    path: Union[str, Path],
    data: Any,
    indent: int = 2,
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    try:
        content = json.dumps(data, ensure_ascii=False, indent=indent)
    except Exception as e:
        return {"ok": False, "error": "SERIALIZE_FAILED", "detail": str(e)}
    return _write_text(path, content, encoding=encoding)


# ---------------------------------------------------------------------- #
# 目录操作
# ---------------------------------------------------------------------- #

def _list_dir(
    path: Union[str, Path],
    include_hidden: bool = False,
) -> Dict[str, Any]:
    p = _resolve(path)
    if not p.exists() or not p.is_dir():
        return {"ok": False, "error": "NOT_FOUND", "path": str(p)}
    items: List[Dict[str, Any]] = []
    for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if not include_hidden and child.name.startswith("."):
            continue
        result = _stat(child)
        if result["ok"]:
            items.append(result["data"])
    return {"ok": True, "path": str(p), "count": len(items), "items": items}


def _glob(
    path: Union[str, Path],
    pattern: str,
    max_results: int = 200,
    include_hidden: bool = False,
) -> Dict[str, Any]:
    """在 path 目录下按 pattern 做 glob 匹配，返回命中文件列表。"""
    base = _resolve(path)
    if not base.exists() or not base.is_dir():
        return {"ok": False, "error": "NOT_FOUND", "path": str(base)}
    results: List[Dict[str, Any]] = []
    try:
        for hit in base.glob(pattern):
            if len(results) >= max_results:
                break
            if not include_hidden and any(part.startswith(".") for part in hit.parts):
                continue
            if not hit.is_file():
                continue
            st = hit.stat()
            results.append({
                "path": str(hit),
                "name": hit.name,
                "size_bytes": st.st_size,
                "modified_time": st.st_mtime,
            })
        return {"ok": True, "base": str(base), "pattern": pattern, "count": len(results), "results": results}
    except Exception as e:
        return {"ok": False, "error": "GLOB_FAILED", "detail": str(e)}


def _mkdir(path: Union[str, Path], exist_ok: bool = True) -> Dict[str, Any]:
    p = _resolve(path)
    try:
        p.mkdir(parents=True, exist_ok=exist_ok)
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"ok": False, "error": "MKDIR_FAILED", "path": str(p), "detail": str(e)}


def _remove(path: Union[str, Path], recursive: bool = True) -> Dict[str, Any]:
    p = _resolve(path)
    if not p.exists():
        return {"ok": False, "error": "NOT_FOUND", "path": str(p)}
    try:
        if p.is_file():
            p.unlink()
        elif recursive:
            shutil.rmtree(p)
        else:
            p.rmdir()
        return {"ok": True, "deleted": str(p)}
    except Exception as e:
        return {"ok": False, "error": "DELETE_FAILED", "detail": str(e)}


def _move(src: Union[str, Path], dst: Union[str, Path], overwrite: bool = True) -> Dict[str, Any]:
    s, d = _resolve(src), _resolve(dst)
    if not s.exists():
        return {"ok": False, "error": "SRC_NOT_FOUND", "src": str(s)}
    if d.exists() and not overwrite:
        return {"ok": False, "error": "DST_EXISTS", "dst": str(d)}
    try:
        _mkparent(d)
        if d.exists():
            shutil.rmtree(d) if d.is_dir() else d.unlink()
        shutil.move(str(s), str(d))
        return {"ok": True, "src": str(s), "dst": str(d)}
    except Exception as e:
        return {"ok": False, "error": "MOVE_FAILED", "detail": str(e)}


def _copy(src: Union[str, Path], dst: Union[str, Path], overwrite: bool = True) -> Dict[str, Any]:
    s, d = _resolve(src), _resolve(dst)
    if not s.exists():
        return {"ok": False, "error": "SRC_NOT_FOUND", "src": str(s)}
    if d.exists() and not overwrite:
        return {"ok": False, "error": "DST_EXISTS", "dst": str(d)}
    try:
        _mkparent(d)
        if d.exists():
            shutil.rmtree(d) if d.is_dir() else d.unlink()

        if s.is_dir():
            shutil.copytree(s, d)
        elif s.is_file():
            shutil.copy2(s, d)
        else:
            return {"ok": False, "error": "SRC_UNSUPPORTED", "src": str(s)}
        return {"ok": True, "src": str(s), "dst": str(d)}
    except Exception as e:
        return {"ok": False, "error": "COPY_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# 存在性 / hash
# ---------------------------------------------------------------------- #

def _exists(path: Union[str, Path]) -> Dict[str, Any]:
    p = _resolve(path)
    ex = p.exists()
    return {
        "ok": True,
        "path": str(p),
        "exists": ex,
        "is_file": p.is_file() if ex else False,
        "is_dir": p.is_dir() if ex else False,
    }


def _compute_hash(path: Union[str, Path], algo: str = "sha256") -> Dict[str, Any]:
    p = _resolve(path)
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": "NOT_FOUND", "path": str(p)}
    algo = algo.lower()
    if algo not in ("sha256", "md5"):
        return {"ok": False, "error": "UNSUPPORTED_ALGO", "detail": "支持 sha256 / md5"}
    h = hashlib.sha256() if algo == "sha256" else hashlib.md5()
    try:
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return {"ok": True, "path": str(p), "algo": algo, "hash": h.hexdigest()}
    except Exception as e:
        return {"ok": False, "error": "HASH_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# 文本搜索
# ---------------------------------------------------------------------- #

def _search_text(
    base_dir: Union[str, Path],
    keyword: str,
    pattern: str = "**/*",
    max_hits: int = 200,
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    base = _resolve(base_dir)
    if not base.exists() or not base.is_dir():
        return {"ok": False, "error": "NOT_FOUND", "path": str(base)}
    if not keyword:
        return {"ok": False, "error": "INVALID_INPUT", "detail": "keyword 不能为空"}
    hits: List[Dict[str, Any]] = []
    for p in base.glob(pattern):
        if len(hits) >= max_hits:
            break
        if not p.is_file():
            continue
        try:
            content = p.read_text(encoding=encoding, errors="ignore")
            idx = content.find(keyword)
            if idx != -1:
                start, end = max(0, idx - 40), min(len(content), idx + len(keyword) + 40)
                snippet = content[start:end].replace("\n", "\\n")
                hits.append({"path": str(p), "snippet": snippet})
        except Exception:
            continue
    return {"ok": True, "base_dir": str(base), "keyword": keyword, "count": len(hits), "hits": hits}


# ---------------------------------------------------------------------- #
# 压缩 / 解压
# ---------------------------------------------------------------------- #

def _zip_create(src_dir: Union[str, Path], zip_file: Union[str, Path]) -> Dict[str, Any]:
    src = _resolve(src_dir)
    out = _resolve(zip_file)
    if not src.exists() or not src.is_dir():
        return {"ok": False, "error": "SRC_NOT_FOUND", "src": str(src)}
    try:
        _mkparent(out)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in src.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(src).as_posix())
        return {"ok": True, "src_dir": str(src), "zip_path": str(out)}
    except Exception as e:
        return {"ok": False, "error": "ZIP_FAILED", "detail": str(e)}


def _zip_extract(zip_file: Union[str, Path], extract_path: Union[str, Path]) -> Dict[str, Any]:
    z = _resolve(zip_file)
    dst = _resolve(extract_path)
    if not z.exists() or not z.is_file():
        return {"ok": False, "error": "ZIP_NOT_FOUND", "zip": str(z)}
    try:
        dst.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z, "r") as zf:
            zf.extractall(dst)
        return {"ok": True, "zip_path": str(z), "dst_dir": str(dst)}
    except Exception as e:
        return {"ok": False, "error": "UNZIP_FAILED", "detail": str(e)}


# ======================================================================
# Provider
# ======================================================================

class FilesystemProvider(BaseProvider):
    """文件系统工具集 Provider。"""

    @property
    def name(self) -> str:
        return "filesystem"

    def is_available(self) -> bool:
        return ROOT.exists() and ROOT.is_dir()

    async def initialize(self) -> None:
        self.logger.local("info", f"FilesystemProvider 初始化完成，根目录: {ROOT}")

    def register(self, mcp: FastMCP) -> None:

        @mcp.tool(
            name="fs_read_file",
            description="读取文件",
        )
        async def fs_read_file(path: str) -> Dict[str, Any]:
            return _read_file(path)

        @mcp.tool()
        async def fs_write_text(path: str, content: str) -> Dict[str, Any]:
            """写入文本文件（覆盖/创建）"""
            return _write_text(path, content)

        @mcp.tool()
        async def fs_write_json(path: str, content: dict) -> Dict[str, Any]:
            """写入对象为 JSON 文件（可带缩进/排序）"""
            return _write_json(path, content)

        @mcp.tool()
        async def fs_list_dir(path: str) -> Dict[str, Any]:
            """列出目录下文件/子目录"""
            return _list_dir(path)

        @mcp.tool()
        async def fs_glob(path: str, pattern: str = "**/*") -> Dict[str, Any]:
            """通配符匹配文件（如 **/*.log），path 为搜索根目录，pattern 为 glob 模式"""
            return _glob(path, pattern)

        @mcp.tool()
        async def fs_mkdir(path: str) -> Dict[str, Any]:
            """创建目录（支持递归）"""
            return _mkdir(path)

        @mcp.tool()
        async def fs_remove(path: str) -> Dict[str, Any]:
            """删除文件或目录"""
            return _remove(path)

        @mcp.tool()
        async def fs_move(path: str, new_path: str) -> Dict[str, Any]:
            """移动/重命名文件或目录"""
            return _move(path, new_path)

        @mcp.tool()
        async def fs_copy(path: str, new_path: str) -> Dict[str, Any]:
            """复制文件或目录"""
            return _copy(path, new_path)

        @mcp.tool()
        async def fs_stat(path: str) -> Dict[str, Any]:
            """获取文件元信息（大小、mtime、权限等）"""
            return _stat(path)

        @mcp.tool()
        async def fs_exists(path: str) -> Dict[str, Any]:
            """判断路径是否存在"""
            return _exists(path)

        @mcp.tool()
        async def fs_compute_hash(path: str, hash_type: str = "sha256") -> Dict[str, Any]:
            """计算文件 hash（sha256 / md5）"""
            return _compute_hash(path, algo=hash_type)

        @mcp.tool()
        async def fs_search_text(path: str, keyword: str) -> Dict[str, Any]:
            """在目录内搜索包含关键字的文件，返回匹配片段"""
            return _search_text(base_dir=path, keyword=keyword)

        @mcp.tool()
        async def fs_zip_create(path: str, zip_file: str) -> Dict[str, Any]:
            """将目录打包为 zip 文件"""
            return _zip_create(src_dir=path, zip_file=zip_file)

        @mcp.tool()
        async def fs_zip_extract(zip_file: str, extract_path: str) -> Dict[str, Any]:
            """解压 zip 文件到指定目录"""
            return _zip_extract(zip_file=zip_file, extract_path=extract_path)
