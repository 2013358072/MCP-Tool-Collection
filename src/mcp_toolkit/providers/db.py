from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastmcp import FastMCP

from mcp_toolkit.core import config as _cfg
from mcp_toolkit.providers.base import BaseProvider

# ======================================================================
# 本模块处理 SQLite 数据库操作（标准库 sqlite3）
# ======================================================================


def _connect(db_path: str) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------- #
# db_sqlite_query
# ---------------------------------------------------------------------- #

def _db_sqlite_query(
    db_path: Optional[str],
    sql: str,
    params: Optional[List[Any]] = None,
    mode: Literal["read", "write", "transaction"] = "read",
    transaction_sqls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """执行 SQLite 查询。

    mode:
      "read"        — 执行单条 SELECT，返回 rows
      "write"       — 执行单条 INSERT/UPDATE/DELETE/CREATE 等，返回 rowcount
      "transaction" — 执行 transaction_sqls 中的多条语句（原子提交）

    transaction_sqls 格式（mode="transaction" 时使用）:
      [{"sql": "INSERT ...", "params": [...]}, ...]

    params: sql 中 ? 占位符对应的参数列表
    """
    try:
        db_path = db_path or _cfg.SQLITE_DB_PATH
        conn = _connect(db_path)

        if mode == "transaction":
            if not transaction_sqls:
                return {"ok": False, "error": "EMPTY_TRANSACTION"}
            try:
                with conn:
                    total_rows = 0
                    for item in transaction_sqls:
                        cur = conn.execute(
                            item["sql"],
                            item.get("params") or [],
                        )
                        total_rows += cur.rowcount
                return {
                    "ok": True,
                    "db_path": db_path,
                    "mode": "transaction",
                    "statement_count": len(transaction_sqls),
                    "total_rowcount": total_rows,
                }
            except Exception as e:
                return {"ok": False, "error": "TRANSACTION_FAILED", "detail": str(e)}

        cur = conn.cursor()
        cur.execute(sql, params or [])

        if mode == "read":
            rows = _rows_to_dicts(cur.fetchall())
            conn.close()
            return {
                "ok": True,
                "db_path": db_path,
                "mode": "read",
                "row_count": len(rows),
                "rows": rows,
            }

        # write
        conn.commit()
        rowcount = cur.rowcount
        lastrowid = cur.lastrowid
        conn.close()
        return {
            "ok": True,
            "db_path": db_path,
            "mode": "write",
            "rowcount": rowcount,
            "lastrowid": lastrowid,
        }

    except sqlite3.Error as e:
        return {"ok": False, "error": "SQLITE_ERROR", "detail": str(e)}
    except Exception as e:
        return {"ok": False, "error": "FAILED", "detail": str(e)}


# ======================================================================
# Provider
# ======================================================================

class DBProvider(BaseProvider):
    """SQLite 数据库工具集 Provider（标准库，无需额外依赖）。"""

    @property
    def name(self) -> str:
        return "db"

    def is_available(self) -> bool:
        return True

    async def initialize(self) -> None:
        self.logger.local("info", "DBProvider 初始化完成")

    def register(self, mcp: FastMCP) -> None:

        @mcp.tool()
        async def db_sqlite_query(
            db_path: Optional[str] = None,
            sql: str = "",
            params: Optional[List[Any]] = None,
            mode: str = "read",
            transaction_sqls: Optional[List[Dict[str, Any]]] = None,
        ) -> Dict[str, Any]:
            """执行 SQLite 查询（读 / 写 / 事务）。
            db_path: 数据库文件路径；不传时使用 config.SQLITE_DB_PATH（不存在时自动创建）
            sql: SQL 语句，用 ? 作参数占位符
            params: ? 对应的参数列表
            mode: "read"（SELECT）/ "write"（INSERT/UPDATE/DELETE/DDL）/ "transaction"（多语句原子提交）
            transaction_sqls: mode="transaction" 时使用，格式 [{"sql": "...", "params": [...]}]
            """
            return _db_sqlite_query(
                db_path, sql, params=params,
                mode=mode, transaction_sqls=transaction_sqls,
            )
