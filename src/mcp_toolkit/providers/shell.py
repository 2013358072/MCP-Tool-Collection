from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from mcp_toolkit.core import config as _cfg
from mcp_toolkit.providers.base import BaseProvider

# ======================================================================
# Shell / Python 执行工具集
# 所有命令在独立子进程中运行，主进程不受影响。
# ======================================================================


# ---------------------------------------------------------------------- #
# 内部辅助
# ---------------------------------------------------------------------- #

async def _run_subprocess(
    *args: str,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: float = _cfg.SHELL_EXEC_TIMEOUT,
    stdin_data: Optional[bytes] = None,
) -> Dict[str, Any]:
    """异步运行子进程，返回 stdout / stderr / exit_code / elapsed_ms。"""
    merged_env = {**os.environ}
    if env:
        merged_env.update(env)

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or None,
            env=merged_env,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "ok": False,
                "error": "TIMEOUT",
                "elapsed_ms": round((time.monotonic() - start) * 1000),
            }
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
            "elapsed_ms": elapsed_ms,
        }
    except FileNotFoundError as e:
        return {"ok": False, "error": "NOT_FOUND", "detail": str(e)}
    except Exception as e:
        return {"ok": False, "error": "EXEC_FAILED", "detail": str(e)}


async def _run_shell(
    command: str,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: float = _cfg.SHELL_EXEC_TIMEOUT,
) -> Dict[str, Any]:
    """通过 shell 运行命令字符串（支持管道、重定向等 shell 语法）。"""
    merged_env = {**os.environ}
    if env:
        merged_env.update(env)

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or None,
            env=merged_env,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "ok": False,
                "error": "TIMEOUT",
                "command": command,
                "elapsed_ms": round((time.monotonic() - start) * 1000),
            }
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
            "elapsed_ms": elapsed_ms,
        }
    except Exception as e:
        return {"ok": False, "error": "EXEC_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# shell_exec
# ---------------------------------------------------------------------- #

async def _shell_exec(
    command: str,
    cwd: Optional[str] = None,
    env_extra: Optional[Dict[str, str]] = None,
    timeout: float = _cfg.SHELL_EXEC_TIMEOUT,
    use_shell: bool = True,
) -> Dict[str, Any]:
    """执行 shell 命令，返回 stdout / stderr / exit_code / elapsed_ms。

    use_shell=True（默认）支持管道、通配符等 shell 语法；
    use_shell=False 则将 command 按空格拆分后直接 exec，更安全。
    """
    if use_shell:
        result = await _run_shell(command, cwd=cwd, env=env_extra, timeout=timeout)
    else:
        parts = command.split()
        result = await _run_subprocess(*parts, cwd=cwd, env=env_extra, timeout=timeout)

    return {"command": command, **result}


# ---------------------------------------------------------------------- #
# shell_which
# ---------------------------------------------------------------------- #

def _shell_which(name: str) -> Dict[str, Any]:
    """查找可执行文件路径，跨平台（Windows / Linux / macOS）。"""
    path = shutil.which(name)
    if path:
        p = Path(path)
        return {
            "ok": True,
            "name": name,
            "path": str(p),
            "exists": p.exists(),
            "is_file": p.is_file(),
        }
    return {"ok": False, "name": name, "path": None, "detail": f"'{name}' 不在 PATH 中"}


# ---------------------------------------------------------------------- #
# shell_env_get
# ---------------------------------------------------------------------- #

def _shell_env_get(
    keys: List[str],
    allow_missing: bool = True,
) -> Dict[str, Any]:
    """读取指定环境变量，遵循配置白名单。

    SHELL_ENV_WHITELIST 为空时不限制；非空时只允许读取白名单内的 key。
    """
    whitelist = _cfg.SHELL_ENV_WHITELIST
    blocked: List[str] = []
    result: Dict[str, Optional[str]] = {}

    for key in keys:
        if whitelist and key not in whitelist:
            blocked.append(key)
            continue
        value = os.environ.get(key)
        if value is None and not allow_missing:
            return {
                "ok": False,
                "error": "KEY_MISSING",
                "key": key,
            }
        result[key] = value

    return {
        "ok": True,
        "values": result,
        "missing": [k for k, v in result.items() if v is None],
        "blocked": blocked,
    }


# ---------------------------------------------------------------------- #
# python_exec
# ---------------------------------------------------------------------- #

async def _python_exec(
    code: str,
    timeout: float = _cfg.PYTHON_EXEC_TIMEOUT,
    vars_in: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """在独立子进程中执行 Python 代码片段。

    vars_in 中的变量以 JSON 方式序列化后注入为局部变量（仅支持 JSON 可序列化类型）。
    最终 _result 变量的值会被捕获并返回到 result 字段。
    stdout / stderr 完整返回。
    """
    import json

    # 构造完整脚本：注入变量 + 用户代码 + 捕获 _result
    injected = ""
    if vars_in:
        injected = "import json as _json\n"
        for k, v in vars_in.items():
            injected += f"{k} = _json.loads({json.dumps(json.dumps(v))})\n"

    wrapper = (
        f"{injected}\n"
        f"_result = None\n"
        f"try:\n"
        + "\n".join(f"    {line}" for line in code.splitlines())
        + "\nexcept Exception as _exc:\n"
        + "    import sys as _sys\n"
        + "    print(f'[ERROR] {type(_exc).__name__}: {_exc}', file=_sys.stderr)\n"
        + "\nimport json as _json_out, sys as _sys_out\n"
        + "try:\n"
        + "    print(_json_out.dumps(_result), file=_sys_out.stderr, end='\\x00RESULT\\x00')\n"
        + "except Exception:\n"
        + "    pass\n"
    )

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", encoding="utf-8", delete=False
    )
    try:
        tmp.write(wrapper)
        tmp.close()

        result = await _run_subprocess(
            sys.executable, tmp.name,
            cwd=cwd,
            timeout=timeout,
        )

        # 从 stderr 中分离 _result 标记
        stderr_raw: str = result.get("stderr", "")
        captured_result: Any = None
        marker = "\x00RESULT\x00"
        if marker in stderr_raw:
            parts = stderr_raw.split(marker, 1)
            stderr_clean = parts[0]
            try:
                import json
                captured_result = json.loads(parts[1]) if len(parts) > 1 and parts[1] else None
            except Exception:
                captured_result = None
        else:
            stderr_clean = stderr_raw

        result["stderr"] = stderr_clean
        result["result"] = captured_result
        return result

    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# ======================================================================
# Provider
# ======================================================================

class ShellProvider(BaseProvider):
    """Shell / Python 执行工具集 Provider。"""

    @property
    def name(self) -> str:
        return "shell"

    def is_available(self) -> bool:
        return True

    async def initialize(self) -> None:
        self.logger.local("info", "ShellProvider 初始化完成")

    def register(self, mcp: FastMCP) -> None:

        @mcp.tool()
        async def shell_exec(
            command: str,
            cwd: Optional[str] = None,
            env_extra: Optional[Dict[str, str]] = None,
            timeout: float = _cfg.SHELL_EXEC_TIMEOUT,
            use_shell: bool = True,
        ) -> Dict[str, Any]:
            """执行 shell 命令，返回 stdout / stderr / exit_code / elapsed_ms。
            cwd: 工作目录（绝对路径）
            env_extra: 追加到当前环境的额外变量
            use_shell: True（默认）支持管道/通配符；False 直接 exec 更安全
            timeout: 超时秒数，超时后强制终止进程
            """
            return await _shell_exec(
                command, cwd=cwd, env_extra=env_extra,
                timeout=timeout, use_shell=use_shell,
            )

        @mcp.tool()
        async def shell_which(name: str) -> Dict[str, Any]:
            """查找可执行文件的完整路径（跨平台 which/where）"""
            return _shell_which(name)

        @mcp.tool()
        async def shell_env_get(
            keys: List[str],
            allow_missing: bool = True,
        ) -> Dict[str, Any]:
            """读取指定的环境变量（白名单保护，只返回显式请求的 key）。
            keys: 要读取的变量名列表
            allow_missing: False 时若变量不存在则返回错误
            白名单由 SHELL_ENV_WHITELIST 环境变量配置（逗号分隔），空表示不限制
            """
            return _shell_env_get(keys, allow_missing=allow_missing)

        @mcp.tool()
        async def python_exec(
            code: str,
            timeout: float = _cfg.PYTHON_EXEC_TIMEOUT,
            vars_in: Optional[Dict[str, Any]] = None,
            cwd: Optional[str] = None,
        ) -> Dict[str, Any]:
            """在独立子进程中执行 Python 代码片段，返回 stdout / stderr / result / elapsed_ms。
            code: 要执行的 Python 代码，最后赋值给 _result 的内容会被捕获到 result 字段
            vars_in: 注入代码的变量字典（仅支持 JSON 可序列化类型）
            cwd: 工作目录
            timeout: 超时秒数

            示例:
              code = "data = [1,2,3]; _result = sum(data)"
              → result = 6
            """
            return await _python_exec(
                code, timeout=timeout, vars_in=vars_in, cwd=cwd,
            )
