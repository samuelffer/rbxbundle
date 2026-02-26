from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

LOG = logging.getLogger("rbxbundle")

INVALID_FS_CHARS = r'<>:"/\\|?*\\0'
_INVALID_FS_RE = re.compile(f"[{re.escape(INVALID_FS_CHARS)}]")

def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

def sanitize_filename(s: str) -> str:
    s = _INVALID_FS_RE.sub("_", s)
    s = s.strip().strip(".")
    return s or "_"

def ensure_dirs(input_dir: Path, output_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

def safe_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)

def safe_open_csv(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", newline="", encoding="utf-8")

def read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")

def wipe_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)

def local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag

def strip_junk_before_roblox(xml_text: str) -> str:
    idx = xml_text.find("<roblox")
    if idx > 0:
        return xml_text[idx:]
    return xml_text
