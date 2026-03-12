from __future__ import annotations

import imaplib
import smtplib
import uuid
from contextlib import contextmanager
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from fastmcp import FastMCP

from mcp_toolkit.core import config as _cfg
from mcp_toolkit.providers.base import BaseProvider

# ======================================================================
# 本模块通过 SMTP（发送）和 IMAP（读取/搜索/草稿）操作 QQ 邮箱
# ======================================================================


def _require_config() -> Optional[Dict[str, Any]]:
    if not _cfg.QQ_MAIL_SMTP_USER or not _cfg.QQ_MAIL_SMTP_PASSWORD_KEY:
        return {
            "ok": False,
            "error": "CONFIG_MISSING",
            "detail": "QQ_MAIL_SMTP_USER 和 QQ_MAIL_SMTP_PASSWORD_KEY 未配置",
        }
    return None


# ---------------------------------------------------------------------- #
# 连接上下文管理器
# ---------------------------------------------------------------------- #

@contextmanager
def _smtp() -> Generator[smtplib.SMTP_SSL | smtplib.SMTP, None, None]:
    """根据端口自动选择 SSL（465）或 STARTTLS（587）连接。"""
    port = _cfg.QQ_MAIL_SMTP_PORT
    if port == 465:
        conn: smtplib.SMTP_SSL | smtplib.SMTP = smtplib.SMTP_SSL(
            _cfg.QQ_MAIL_SMTP_SERVER, port
        )
    else:
        conn = smtplib.SMTP(_cfg.QQ_MAIL_SMTP_SERVER, port)
        conn.starttls()
    conn.login(_cfg.QQ_MAIL_SMTP_USER, _cfg.QQ_MAIL_SMTP_PASSWORD_KEY)
    try:
        yield conn
    finally:
        try:
            conn.quit()
        except Exception:
            pass


@contextmanager
def _imap() -> Generator[imaplib.IMAP4_SSL, None, None]:
    conn = imaplib.IMAP4_SSL(_cfg.QQ_MAIL_IMAP_SERVER, _cfg.QQ_MAIL_IMAP_PORT)
    conn.login(_cfg.QQ_MAIL_SMTP_USER, _cfg.QQ_MAIL_SMTP_PASSWORD_KEY)
    try:
        yield conn
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ---------------------------------------------------------------------- #
# 辅助函数
# ---------------------------------------------------------------------- #

def _decode_header_str(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _build_message(
    subject: str,
    body: str,
    to: List[str],
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    attachments: Optional[List[str]] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    body_html: Optional[str] = None,
) -> MIMEMultipart:
    """构建 MIME 邮件对象。"""
    msg = MIMEMultipart("mixed")
    msg["From"]    = formataddr(("", _cfg.QQ_MAIL_SMTP_USER))
    msg["To"]      = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"]    = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = references or in_reply_to

    # 正文
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body, "plain", "utf-8"))
    if body_html:
        body_part.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(body_part)

    # 附件
    for att_path in (attachments or []):
        p = Path(att_path)
        if not p.exists():
            continue
        with p.open("rb") as f:
            part = MIMEApplication(f.read(), Name=p.name)
        part["Content-Disposition"] = f'attachment; filename="{p.name}"'
        msg.attach(part)

    return msg


def _parse_envelope(uid: bytes, raw: bytes) -> Dict[str, Any]:
    """将 IMAP FETCH 的原始字节解析为可读字典。"""
    msg = message_from_bytes(raw)
    return {
        "uid":     uid.decode(),
        "from":    _decode_header_str(msg.get("From")),
        "to":      _decode_header_str(msg.get("To")),
        "subject": _decode_header_str(msg.get("Subject")),
        "date":    msg.get("Date", ""),
        "message_id": msg.get("Message-ID", ""),
    }


def _parse_full_message(uid: bytes, raw: bytes) -> Dict[str, Any]:
    """解析完整邮件，包含正文和附件列表。"""
    msg = message_from_bytes(raw)
    envelope = _parse_envelope(uid, raw)

    body_plain = ""
    body_html  = ""
    attachments: List[Dict[str, Any]] = []

    for part in msg.walk():
        ctype    = part.get_content_type()
        disp     = str(part.get("Content-Disposition") or "")
        filename = part.get_filename()

        if "attachment" in disp or filename:
            attachments.append({
                "filename": _decode_header_str(filename),
                "content_type": ctype,
                "size_bytes": len(part.get_payload(decode=True) or b""),
            })
        elif ctype == "text/plain" and not body_plain:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            body_plain = (payload or b"").decode(charset, errors="replace")
        elif ctype == "text/html" and not body_html:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            body_html = (payload or b"").decode(charset, errors="replace")

    return {
        **envelope,
        "body_plain": body_plain,
        "body_html":  body_html,
        "attachments": attachments,
        "attachment_count": len(attachments),
    }


def _imap_folder_name(raw: bytes) -> str:
    """从 IMAP LIST 响应中提取文件夹名。"""
    parts = raw.decode("utf-8", errors="replace").rsplit('"', 1)
    name = parts[-1].strip().strip('"')
    try:
        return name.encode("ascii").decode("utf-7")
    except Exception:
        return name


# ---------------------------------------------------------------------- #
# email_send
# ---------------------------------------------------------------------- #

def _email_send(
    to: List[str],
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    attachments: Optional[List[str]] = None,
    body_html: Optional[str] = None,
) -> Dict[str, Any]:
    if err := _require_config():
        return err
    try:
        msg = _build_message(
            subject=subject, body=body, to=to,
            cc=cc, bcc=bcc, attachments=attachments, body_html=body_html,
        )
        all_recipients = to + (cc or []) + (bcc or [])
        with _smtp() as conn:
            conn.sendmail(_cfg.QQ_MAIL_SMTP_USER, all_recipients, msg.as_bytes())
        return {
            "ok": True,
            "message_id": msg["Message-ID"],
            "to": to,
            "subject": subject,
        }
    except Exception as e:
        return {"ok": False, "error": "SEND_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# email_draft
# ---------------------------------------------------------------------- #

def _email_draft(
    to: List[str],
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    attachments: Optional[List[str]] = None,
    body_html: Optional[str] = None,
) -> Dict[str, Any]:
    """通过 IMAP APPEND 将邮件保存到草稿箱，返回 draft_id（IMAP UID）。"""
    if err := _require_config():
        return err
    try:
        msg = _build_message(
            subject=subject, body=body, to=to,
            cc=cc, attachments=attachments, body_html=body_html,
        )
        raw = msg.as_bytes()

        with _imap() as conn:
            # 尝试常见草稿箱名称
            for folder in ("Drafts", "草稿箱", "[Gmail]/Drafts", "Draft"):
                try:
                    result = conn.append(
                        folder, r"\Draft", imaplib.Time2Internaldate(datetime.now()), raw
                    )
                    if result[0] == "OK":
                        # APPENDUID 响应: OK [APPENDUID uidvalidity uid]
                        resp_str = result[1][0].decode() if result[1] else ""
                        uid = resp_str.split()[-1].rstrip("]") if "APPENDUID" in resp_str else str(uuid.uuid4())
                        return {
                            "ok": True,
                            "draft_id": uid,
                            "folder": folder,
                            "subject": subject,
                            "to": to,
                        }
                except Exception:
                    continue

        return {"ok": False, "error": "DRAFT_FAILED", "detail": "无法找到草稿箱文件夹"}
    except Exception as e:
        return {"ok": False, "error": "DRAFT_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# email_reply
# ---------------------------------------------------------------------- #

def _email_reply(
    folder: str,
    uid: str,
    body: str,
    reply_all: bool = False,
    attachments: Optional[List[str]] = None,
    body_html: Optional[str] = None,
) -> Dict[str, Any]:
    """回复指定邮件。reply_all=True 时同时回复所有收件人。"""
    if err := _require_config():
        return err
    try:
        with _imap() as conn:
            conn.select(folder)
            typ, data = conn.uid("fetch", uid.encode(), "(RFC822)")
            if typ != "OK" or not data or not data[0]:
                return {"ok": False, "error": "MESSAGE_NOT_FOUND", "uid": uid}
            raw = data[0][1]

        orig = message_from_bytes(raw)
        orig_from    = _decode_header_str(orig.get("From", ""))
        orig_subject = _decode_header_str(orig.get("Subject", ""))
        orig_msg_id  = orig.get("Message-ID", "")
        orig_to      = _decode_header_str(orig.get("To", ""))
        orig_cc      = _decode_header_str(orig.get("Cc", ""))

        reply_subject = f"Re: {orig_subject}" if not orig_subject.startswith("Re:") else orig_subject
        reply_to = [orig_from]
        reply_cc = None
        if reply_all:
            all_addrs = [a.strip() for a in (orig_to + ", " + orig_cc).split(",") if a.strip()]
            reply_cc = [a for a in all_addrs if _cfg.QQ_MAIL_SMTP_USER not in a]

        msg = _build_message(
            subject=reply_subject, body=body, to=reply_to, cc=reply_cc,
            attachments=attachments, body_html=body_html,
            in_reply_to=orig_msg_id,
        )
        all_recipients = reply_to + (reply_cc or [])
        with _smtp() as conn:
            conn.sendmail(_cfg.QQ_MAIL_SMTP_USER, all_recipients, msg.as_bytes())
        return {
            "ok": True,
            "message_id": msg["Message-ID"],
            "in_reply_to": orig_msg_id,
            "to": reply_to,
            "subject": reply_subject,
        }
    except Exception as e:
        return {"ok": False, "error": "REPLY_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# email_forward
# ---------------------------------------------------------------------- #

def _email_forward(
    folder: str,
    uid: str,
    to: List[str],
    note: str = "",
    cc: Optional[List[str]] = None,
    attachments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """转发指定邮件，可在正文前添加附言 note。"""
    if err := _require_config():
        return err
    try:
        with _imap() as conn:
            conn.select(folder)
            typ, data = conn.uid("fetch", uid.encode(), "(RFC822)")
            if typ != "OK" or not data or not data[0]:
                return {"ok": False, "error": "MESSAGE_NOT_FOUND", "uid": uid}
            raw = data[0][1]

        orig = message_from_bytes(raw)
        orig_subject = _decode_header_str(orig.get("Subject", ""))
        orig_from    = _decode_header_str(orig.get("From", ""))
        orig_date    = orig.get("Date", "")
        orig_body    = ""
        for part in orig.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                orig_body = (payload or b"").decode(charset, errors="replace")
                break

        fwd_subject = f"Fwd: {orig_subject}" if not orig_subject.startswith("Fwd:") else orig_subject
        fwd_body = (
            f"{note}\n\n"
            f"---------- Forwarded message ----------\n"
            f"From: {orig_from}\n"
            f"Date: {orig_date}\n"
            f"Subject: {orig_subject}\n\n"
            f"{orig_body}"
        )

        msg = _build_message(
            subject=fwd_subject, body=fwd_body, to=to, cc=cc, attachments=attachments,
        )
        all_recipients = to + (cc or [])
        with _smtp() as conn:
            conn.sendmail(_cfg.QQ_MAIL_SMTP_USER, all_recipients, msg.as_bytes())
        return {
            "ok": True,
            "message_id": msg["Message-ID"],
            "to": to,
            "subject": fwd_subject,
        }
    except Exception as e:
        return {"ok": False, "error": "FORWARD_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# email_search
# ---------------------------------------------------------------------- #

def _email_search(
    query: Optional[str] = None,
    folder: str = "INBOX",
    from_addr: Optional[str] = None,
    subject_keyword: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    unread_only: bool = False,
    max_results: int = 20,
) -> Dict[str, Any]:
    """搜索邮件，返回匹配的邮件摘要列表。

    query:            正文/主题关键词（TEXT 搜索）
    date_from/date_to: 格式 "DD-Mon-YYYY"，如 "01-Jan-2025"
    """
    if err := _require_config():
        return err
    try:
        criteria: List[str] = []
        if unread_only:
            criteria.append("UNSEEN")
        if from_addr:
            criteria.append(f'FROM "{from_addr}"')
        if subject_keyword:
            criteria.append(f'SUBJECT "{subject_keyword}"')
        if query:
            criteria.append(f'TEXT "{query}"')
        if date_from:
            criteria.append(f"SINCE {date_from}")
        if date_to:
            criteria.append(f"BEFORE {date_to}")
        if not criteria:
            criteria.append("ALL")

        search_str = " ".join(criteria)

        with _imap() as conn:
            conn.select(folder, readonly=True)
            typ, data = conn.uid("search", None, f"({search_str})")
            if typ != "OK":
                return {"ok": False, "error": "SEARCH_FAILED", "detail": str(data)}

            uids = data[0].split()
            # 取最近 max_results 封（倒序）
            target_uids = uids[-(max_results):][::-1]

            messages: List[Dict[str, Any]] = []
            for uid in target_uids:
                typ2, msg_data = conn.uid("fetch", uid, "(RFC822.HEADER)")
                if typ2 == "OK" and msg_data and msg_data[0]:
                    messages.append(_parse_envelope(uid, msg_data[0][1]))

        return {
            "ok": True,
            "folder": folder,
            "total_matched": len(uids),
            "returned": len(messages),
            "messages": messages,
        }
    except Exception as e:
        return {"ok": False, "error": "SEARCH_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# email_read
# ---------------------------------------------------------------------- #

def _email_read(
    uid: str,
    folder: str = "INBOX",
) -> Dict[str, Any]:
    """读取指定邮件的完整内容（正文 + 附件列表）。"""
    if err := _require_config():
        return err
    try:
        with _imap() as conn:
            conn.select(folder, readonly=True)
            typ, data = conn.uid("fetch", uid.encode(), "(RFC822)")
            if typ != "OK" or not data or not data[0]:
                return {"ok": False, "error": "MESSAGE_NOT_FOUND", "uid": uid}
            return {"ok": True, **_parse_full_message(uid.encode(), data[0][1])}
    except Exception as e:
        return {"ok": False, "error": "READ_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# email_list_folders
# ---------------------------------------------------------------------- #

def _email_list_folders() -> Dict[str, Any]:
    """列出邮箱中所有文件夹/标签。"""
    if err := _require_config():
        return err
    try:
        with _imap() as conn:
            typ, data = conn.list()
            if typ != "OK":
                return {"ok": False, "error": "LIST_FAILED"}

            folders: List[str] = []
            for item in data:
                if isinstance(item, bytes):
                    name = _imap_folder_name(item)
                    if name:
                        folders.append(name)

        return {"ok": True, "count": len(folders), "folders": folders}
    except Exception as e:
        return {"ok": False, "error": "LIST_FAILED", "detail": str(e)}


# ---------------------------------------------------------------------- #
# email_create_label
# ---------------------------------------------------------------------- #

def _email_create_label(
    folder_name: str,
    parent_folder: Optional[str] = None,
) -> Dict[str, Any]:
    """在邮箱中创建文件夹/标签。parent_folder 非空时创建子文件夹。"""
    if err := _require_config():
        return err
    try:
        full_name = f"{parent_folder}/{folder_name}" if parent_folder else folder_name
        with _imap() as conn:
            typ, data = conn.create(full_name)
            if typ != "OK":
                return {
                    "ok": False,
                    "error": "CREATE_FAILED",
                    "detail": data[0].decode() if data else "",
                }
        return {"ok": True, "folder": full_name}
    except Exception as e:
        return {"ok": False, "error": "CREATE_FAILED", "detail": str(e)}


# ======================================================================
# Provider
# ======================================================================

class EmailProvider(BaseProvider):
    """QQ 邮件工具集 Provider（SMTP 发送 + IMAP 读取）。"""

    @property
    def name(self) -> str:
        return "email"

    def is_available(self) -> bool:
        return bool(_cfg.QQ_MAIL_SMTP_USER and _cfg.QQ_MAIL_SMTP_PASSWORD_KEY)

    async def initialize(self) -> None:
        self.logger.local("info", "EmailProvider 初始化完成")

    def register(self, mcp: FastMCP) -> None:

        @mcp.tool()
        async def email_send(
            to: List[str],
            subject: str,
            body: str,
            cc: Optional[List[str]] = None,
            bcc: Optional[List[str]] = None,
            attachments: Optional[List[str]] = None,
            body_html: Optional[str] = None,
        ) -> Dict[str, Any]:
            """发送邮件。
            to / cc / bcc: 收件人列表
            attachments: 本地文件路径列表
            body_html: HTML 格式正文（可选，与纯文本 body 共存）
            """
            return _email_send(
                to=to, subject=subject, body=body,
                cc=cc, bcc=bcc, attachments=attachments, body_html=body_html,
            )

        @mcp.tool()
        async def email_draft(
            to: List[str],
            subject: str,
            body: str,
            cc: Optional[List[str]] = None,
            attachments: Optional[List[str]] = None,
            body_html: Optional[str] = None,
        ) -> Dict[str, Any]:
            """将邮件保存到草稿箱，返回 draft_id（IMAP UID）"""
            return _email_draft(
                to=to, subject=subject, body=body,
                cc=cc, attachments=attachments, body_html=body_html,
            )

        @mcp.tool()
        async def email_reply(
            folder: str,
            uid: str,
            body: str,
            reply_all: bool = False,
            attachments: Optional[List[str]] = None,
            body_html: Optional[str] = None,
        ) -> Dict[str, Any]:
            """回复指定邮件。uid 为 email_search 或 email_read 返回的 IMAP UID。
            reply_all=True 时同时回复所有原始收件人
            """
            return _email_reply(
                folder=folder, uid=uid, body=body,
                reply_all=reply_all, attachments=attachments, body_html=body_html,
            )

        @mcp.tool()
        async def email_forward(
            folder: str,
            uid: str,
            to: List[str],
            note: str = "",
            cc: Optional[List[str]] = None,
            attachments: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """转发指定邮件。note 为在原邮件前添加的附言。"""
            return _email_forward(
                folder=folder, uid=uid, to=to,
                note=note, cc=cc, attachments=attachments,
            )

        @mcp.tool()
        async def email_search(
            query: Optional[str] = None,
            folder: str = "INBOX",
            from_addr: Optional[str] = None,
            subject_keyword: Optional[str] = None,
            date_from: Optional[str] = None,
            date_to: Optional[str] = None,
            unread_only: bool = False,
            max_results: int = 20,
        ) -> Dict[str, Any]:
            """搜索邮件，返回摘要列表。
            date_from / date_to: 格式 "DD-Mon-YYYY"，如 "01-Jan-2025"
            query: 正文/主题关键词
            unread_only: 仅搜索未读邮件
            """
            return _email_search(
                query=query, folder=folder,
                from_addr=from_addr, subject_keyword=subject_keyword,
                date_from=date_from, date_to=date_to,
                unread_only=unread_only, max_results=max_results,
            )

        @mcp.tool()
        async def email_read(
            uid: str,
            folder: str = "INBOX",
        ) -> Dict[str, Any]:
            """读取指定邮件的完整正文和附件列表。uid 来自 email_search 的返回值。"""
            return _email_read(uid=uid, folder=folder)

        @mcp.tool()
        async def email_list_folders() -> Dict[str, Any]:
            """列出邮箱中所有文件夹/标签"""
            return _email_list_folders()

        @mcp.tool()
        async def email_create_label(
            folder_name: str,
            parent_folder: Optional[str] = None,
        ) -> Dict[str, Any]:
            """创建邮箱文件夹/标签。parent_folder 非空时创建子文件夹。"""
            return _email_create_label(folder_name=folder_name, parent_folder=parent_folder)
