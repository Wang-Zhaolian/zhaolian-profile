"""Local attachment validation and ChatGPT Responses multimodal input."""

from __future__ import annotations

import base64
import io
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_NOTE_FILES_BYTES = 200 * 1024 * 1024
MAX_AI_FILES_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_NOTE = 10
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx", ".txt", ".md", ".xlsx", ".pptx"}
_OFFICE = {".docx", ".xlsx", ".pptx"}


def safe_display_name(filename: str) -> str:
    name = str(filename or "").replace("\\", "/").split("/")[-1]
    name = "".join(char for char in name if char.isprintable() and char not in "<>:\"|?*").strip(" .")
    return name[:150] or "未命名附件"


def _validate_bytes(name: str, data: bytes) -> tuple[str, str]:
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED:
        raise ValueError("仅支持 PNG、JPG、WEBP、PDF、DOCX、TXT、Markdown、XLSX 和 PPTX 文件。")
    if not data:
        raise ValueError(f"{name} 是空文件。")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{name} 超过单文件 50 MB 限制，请压缩或拆分后重新上传。")
    signatures = {
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".jpeg": data.startswith(b"\xff\xd8\xff"),
        ".webp": len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        ".pdf": data.startswith(b"%PDF-"),
    }
    if suffix in signatures and not signatures[suffix]:
        raise ValueError(f"{name} 的文件内容与扩展名不匹配。")
    if suffix in _OFFICE:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist()) > 5000 or sum(entry.file_size for entry in archive.infolist()) > MAX_NOTE_FILES_BYTES:
                    raise ValueError(f"{name} 的内部内容过大，已拒绝打开。")
                expected = {
                    ".docx": "word/document.xml",
                    ".xlsx": "xl/workbook.xml",
                    ".pptx": "ppt/presentation.xml",
                }[suffix]
                if expected not in archive.namelist():
                    raise ValueError(f"{name} 不是有效的 Office 文档。")
        except zipfile.BadZipFile:
            raise ValueError(f"{name} 不是有效的 Office 文档。") from None
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if suffix == ".md":
        mime = "text/markdown"
    return suffix, mime


def save_attachments(home: Path, note_id: str, uploads: Iterable[tuple[str, bytes]]) -> list[dict[str, Any]]:
    items = list(uploads)
    if len(items) > MAX_FILES_PER_NOTE:
        raise ValueError(f"一条素材最多可添加 {MAX_FILES_PER_NOTE} 个文件。")
    if sum(len(data) for _, data in items) > MAX_NOTE_FILES_BYTES:
        raise ValueError("本条素材附件总量超过 200 MB，请分成多条素材保存。")
    directory = Path(home) / "private" / "ai_notes" / "attachments" / note_id
    directory.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    try:
        for original_name, data in items:
            name = safe_display_name(original_name)
            suffix, mime = _validate_bytes(name, data)
            attachment_id = uuid.uuid4().hex
            stored_name = attachment_id + suffix
            target = directory / stored_name
            with target.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            saved.append({
                "id": attachment_id,
                "name": name,
                "size": len(data),
                "mime_type": mime,
                "extension": suffix,
                "stored_name": stored_name,
            })
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return saved


def attachment_path(home: Path, note_id: str, attachment: dict[str, Any]) -> Path:
    attachment_id = str(attachment.get("id", ""))
    stored_name = str(attachment.get("stored_name", ""))
    if not _ID_RE.fullmatch(note_id) or not _ID_RE.fullmatch(attachment_id):
        raise ValueError("附件编号无效。")
    if Path(stored_name).name != stored_name or not stored_name.startswith(attachment_id + "."):
        raise ValueError("附件路径无效。")
    path = Path(home) / "private" / "ai_notes" / "attachments" / note_id / stored_name
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _office_script() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "scripts" / "office_to_pdf.ps1"
    return Path(__file__).resolve().parents[2] / "scripts" / "office_to_pdf.ps1"


def _office_to_pdf(source: Path, output: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    script = _office_script()
    if not powershell or not script.is_file():
        raise ValueError("无法启动本机 Office 转 PDF。请手动将文档另存为 PDF 后再上传。")
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-InputPath", str(source), "-OutputPath", str(output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise ValueError("本机 Office 转 PDF 超时。请关闭占用 Office 的窗口，或手动另存为 PDF 后上传。") from None
    except OSError:
        raise ValueError("无法启动本机 Office。请手动另存为 PDF 后上传。") from None
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise ValueError("本机 Office 转 PDF 失败。请检查文件能否在 Office 打开，或手动另存为 PDF 后上传。")
    if output.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("转换后的 PDF 超过 50 MB。请拆分文件后分批上传。")


def build_attachment_content(
    home: Path,
    note: dict[str, Any],
    attachment_ids: list[str],
) -> list[dict[str, Any]]:
    metadata = note.get("attachments", [])
    available = {str(item.get("id")): item for item in metadata if isinstance(item, dict)}
    if any(attachment_id not in available for attachment_id in attachment_ids):
        raise ValueError("所选附件与这条素材不匹配，请刷新页面后重试。")
    selected = [available[attachment_id] for attachment_id in attachment_ids]
    if not selected:
        return []
    raw_size = sum(int(item.get("size", 0)) for item in selected)
    if raw_size > MAX_AI_FILES_BYTES:
        raise ValueError("所选附件总量超过 ChatGPT 单次 50 MB 限制。请取消部分附件，或拆分文件后分批整理。")

    content: list[dict[str, Any]] = []
    outgoing_size = 0
    with tempfile.TemporaryDirectory(prefix="zhaolian-office-") as temporary_root:
        for item in selected:
            original = attachment_path(home, str(note["id"]), item)
            suffix = str(item.get("extension") or original.suffix).lower()
            mime = str(item.get("mime_type") or "application/octet-stream")
            source = original
            filename = str(item.get("name") or original.name)
            if suffix in _OFFICE:
                source = Path(temporary_root) / (str(item["id"]) + ".pdf")
                _office_to_pdf(original, source)
                filename = Path(filename).stem + ".pdf"
                mime = "application/pdf"
                suffix = ".pdf"
            data = source.read_bytes()
            outgoing_size += len(data)
            if outgoing_size > MAX_AI_FILES_BYTES:
                raise ValueError("所选附件经 Office 转换后超过 ChatGPT 单次 50 MB 限制。请取消部分附件或分批整理。")
            encoded = base64.b64encode(data).decode("ascii")
            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                content.append({"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "high"})
            else:
                content.append({"type": "input_file", "filename": filename, "file_data": f"data:{mime};base64,{encoded}", "detail": "high"})
    return content
