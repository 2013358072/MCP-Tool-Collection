from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastmcp import FastMCP

from mcp_toolkit.core import config as _cfg
from mcp_toolkit.providers.base import BaseProvider

# ======================================================================
# 本模块仅处理 .pdf 文件
#   pdf_read_text      —— PyMuPDF (fitz)
#   pdf_extract_tables —— pdfplumber
# ======================================================================


def _mkparent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _resolve_pdf_path(path: str) -> Path:
    """将 PDF 路径限制在沙箱目录内。"""
    sandbox_root = Path(_cfg.FILESYSTEM_ROOT or Path.cwd()).resolve()
    p = Path(path)
    resolved = (sandbox_root / p).resolve() if not p.is_absolute() else p.resolve()
    try:
        resolved.relative_to(sandbox_root)
    except ValueError as e:
        raise PermissionError(
            f"路径越出沙箱: {resolved}（FILESYSTEM_ROOT={sandbox_root}）"
        ) from e
    return resolved


def _check_pdf(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": "NOT_FOUND", "path": str(p)}
    if p.suffix.lower() != ".pdf":
        return {"ok": False, "error": "NOT_PDF", "detail": f"仅支持 .pdf 格式，收到: {p.suffix}"}
    return None


def _parse_page_range(spec: str, total: int) -> List[int]:
    """将页码规格解析为 0-based 索引列表。
    支持格式: "1,3,5"、"1-5"、"1-3,7,9-11"（用户输入 1-based）
    """
    indices: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            indices.extend(range(lo - 1, hi))
        elif re.match(r"^\d+$", part):
            indices.append(int(part) - 1)
    # 去重、过滤越界、保持顺序
    seen = set()
    result = []
    for i in indices:
        if i not in seen and 0 <= i < total:
            seen.add(i)
            result.append(i)
    return result


# ---------------------------------------------------------------------- #
# pdf_read_text
# ---------------------------------------------------------------------- #

def _pdf_read_text(
    path: str,
    pages: Optional[List[int]] = None,
    page_range: Optional[str] = None,
    output_mode: str = "by_page",
    max_chars_per_page: Optional[int] = None,
) -> Dict[str, Any]:
    """使用 PyMuPDF 读取 PDF 文本。

    pages:              指定页码列表（1-based），优先于 page_range
    page_range:         页码范围字符串，如 "1-5" 或 "1,3,7-10"（1-based）
    output_mode:        "by_page" 返回每页独立结构；"full" 返回拼接全文
    max_chars_per_page: 每页最多返回的字符数（None 表示不限）
    """
    import fitz  # PyMuPDF

    try:
        p = _resolve_pdf_path(path)
    except PermissionError as e:
        return {"ok": False, "error": "PATH_OUTSIDE_SANDBOX", "detail": str(e)}
    if err := _check_pdf(p):
        return err
    try:
        doc = fitz.open(str(p))
        total_pages = doc.page_count

        # 确定需要读取的页码（0-based）
        if pages:
            target = [i - 1 for i in pages if 1 <= i <= total_pages]
        elif page_range:
            target = _parse_page_range(page_range, total_pages)
        else:
            target = list(range(total_pages))

        page_results: List[Dict[str, Any]] = []
        for idx in target:
            page = doc[idx]
            text = page.get_text("text")
            if max_chars_per_page is not None:
                text = text[:max_chars_per_page]
            page_results.append({
                "page": idx + 1,
                "char_count": len(text),
                "text": text,
            })

        doc.close()

        if output_mode == "full":
            full_text = "\n\n".join(r["text"] for r in page_results)
            return {
                "ok": True,
                "path": str(p),
                "total_pages": total_pages,
                "read_pages": len(page_results),
                "char_count": len(full_text),
                "text": full_text,
            }

        return {
            "ok": True,
            "path": str(p),
            "total_pages": total_pages,
            "read_pages": len(page_results),
            "pages": page_results,
        }
    except Exception as e:
        return {"ok": False, "error": "READ_FAILED", "path": str(p), "detail": str(e)}


# ---------------------------------------------------------------------- #
# pdf_extract_tables
# ---------------------------------------------------------------------- #

def _pdf_extract_tables(
    path: str,
    pages: Optional[List[int]] = None,
    page_range: Optional[str] = None,
    output_format: Literal["list", "dict"] = "dict",
    min_rows: int = 1,
    min_cols: int = 1,
) -> Dict[str, Any]:
    """使用 pdfplumber 从 PDF 中抽取表格为结构化数据。

    pages / page_range: 限制抽取范围（1-based，规则同 pdf_read_text）
    output_format:
        "list" — 每张表格为二维字符串数组（含表头行）
        "dict" — 首行作为字段名，其余行转为字典列表
    min_rows / min_cols: 过滤掉行数/列数不足的微小表格
    """
    import pdfplumber

    try:
        p = _resolve_pdf_path(path)
    except PermissionError as e:
        return {"ok": False, "error": "PATH_OUTSIDE_SANDBOX", "detail": str(e)}
    if err := _check_pdf(p):
        return err
    try:
        with pdfplumber.open(str(p)) as pdf:
            total_pages = len(pdf.pages)

            if pages:
                target = [i - 1 for i in pages if 1 <= i <= total_pages]
            elif page_range:
                target = _parse_page_range(page_range, total_pages)
            else:
                target = list(range(total_pages))

            all_tables: List[Dict[str, Any]] = []

            for idx in target:
                page = pdf.pages[idx]
                raw_tables = page.extract_tables()
                for t_idx, raw in enumerate(raw_tables):
                    if not raw:
                        continue
                    # 清洗：None → ""，去除全空行
                    cleaned = [
                        [cell if cell is not None else "" for cell in row]
                        for row in raw
                        if any(cell for cell in row if cell)
                    ]
                    if len(cleaned) < min_rows or (cleaned and len(cleaned[0]) < min_cols):
                        continue

                    entry: Dict[str, Any] = {
                        "page": idx + 1,
                        "table_index": t_idx,
                        "rows": len(cleaned),
                        "cols": len(cleaned[0]) if cleaned else 0,
                    }

                    if output_format == "dict" and len(cleaned) >= 2:
                        headers = cleaned[0]
                        entry["headers"] = headers
                        entry["data"] = [
                            {headers[c]: row[c] if c < len(row) else ""
                             for c in range(len(headers))}
                            for row in cleaned[1:]
                        ]
                    else:
                        entry["data"] = cleaned

                    all_tables.append(entry)

        return {
            "ok": True,
            "path": str(p),
            "total_pages": total_pages,
            "scanned_pages": len(target),
            "table_count": len(all_tables),
            "tables": all_tables,
        }
    except Exception as e:
        return {"ok": False, "error": "EXTRACT_FAILED", "path": str(p), "detail": str(e)}


# ======================================================================
# Provider
# ======================================================================

class PDFProvider(BaseProvider):
    """PDF 读取工具集 Provider（依赖 PyMuPDF 和 pdfplumber）。"""

    @property
    def name(self) -> str:
        return "pdf"

    def is_available(self) -> bool:
        return True

    async def initialize(self) -> None:
        self.logger.local("info", "PDFProvider 初始化完成")

    def register(self, mcp: FastMCP) -> None:

        @mcp.tool()
        async def pdf_read_text(
            path: str,
            pages: Optional[List[int]] = None,
            page_range: Optional[str] = None,
            output_mode: str = "by_page",
            max_chars_per_page: Optional[int] = None,
        ) -> Dict[str, Any]:
            """读取 PDF 文本内容。
            pages: 指定页码列表（1-based），如 [1, 3, 5]
            page_range: 页码范围字符串（1-based），如 "1-5" 或 "1,3,7-10"
            output_mode: "by_page"（每页独立，含页码）或 "full"（拼接全文）
            max_chars_per_page: 每页最多字符数，None 表示不限
            """
            return _pdf_read_text(
                path,
                pages=pages,
                page_range=page_range,
                output_mode=output_mode,
                max_chars_per_page=max_chars_per_page,
            )

        @mcp.tool()
        async def pdf_extract_tables(
            path: str,
            pages: Optional[List[int]] = None,
            page_range: Optional[str] = None,
            output_format: str = "dict",
            min_rows: int = 1,
            min_cols: int = 1,
        ) -> Dict[str, Any]:
            """从 PDF 中抽取表格为结构化数据。
            pages / page_range: 限制抽取范围（规则同 pdf_read_text）
            output_format: "dict"（首行为字段名，其余行转字典）或 "list"（原始二维数组）
            min_rows / min_cols: 过滤行/列数不足的微小表格
            """
            return _pdf_extract_tables(
                path,
                pages=pages,
                page_range=page_range,
                output_format=output_format,
                min_rows=min_rows,
                min_cols=min_cols,
            )
