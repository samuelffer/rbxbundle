#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import csv
import logging
import re
import shutil
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


# ----------------- Config -----------------
INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
SUPPORTED_EXTS = {".rbxmx", ".rbxlx", ".xml", ".txt"}

SCRIPT_CLASSES = {"Script", "LocalScript", "ModuleScript"}

# Script source is usually a ProtectedString, sometimes "string" or SharedString depending on export/tooling.
SOURCE_PROP_NAME = "Source"
SOURCE_TAG_NAMES = {"ProtectedString", "string", "SharedString"}

# Name usually appears as <string name="Name">...</string>
NAME_PROP_TAGS = {"string"}

# Context objects (for CONTEXT.txt)
CONTEXT_CLASSES = {
    "RemoteEvent",
    "RemoteFunction",
    "BindableEvent",
    "BindableFunction",
    "StringValue",
    "NumberValue",
    "BoolValue",
    "IntValue",
    "ObjectValue",
    "Folder",
    "Configuration",
}

VALUE_OBJECT_CLASSES = {
    "StringValue",
    "NumberValue",
    "BoolValue",
    "IntValue",
    "ObjectValue",
}

INVALID_FS_CHARS = r'<>:"/\|?*\0'
INVALID_FS_RE = re.compile(f"[{re.escape(INVALID_FS_CHARS)}]")


# ----------------- Logging -----------------
LOG = logging.getLogger("rbxbundle")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )


# ----------------- Data -----------------
@dataclass
class ScriptRecord:
    class_name: str
    name: str
    full_path: str
    rel_file: str
    source_len: int


@dataclass
class ContextRecord:
    class_name: str
    name: str
    full_path: str
    details: Dict[str, str] = field(default_factory=dict)


@dataclass
class AttributeRecord:
    owner_class: str
    owner_name: str
    owner_path: str
    attr_name: str
    attr_type: str
    attr_value: str


# ----------------- Helpers -----------------
def hr() -> None:
    LOG.info("-" * 64)


def ensure_dirs() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(s: str) -> str:
    s = INVALID_FS_RE.sub("_", s)
    s = s.strip().strip(".")
    return s or "_"


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


def local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def strip_junk_before_roblox(xml_text: str) -> str:
    idx = xml_text.find("<roblox")
    if idx > 0:
        return xml_text[idx:]
    return xml_text


def list_candidates() -> List[Path]:
    files: List[Path] = []
    for p in sorted(INPUT_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            files.append(p)
    return files


def pick_file(files: List[Path]) -> Optional[Path]:
    hr()
    LOG.info("Select a file from ./input/")
    hr()
    for i, p in enumerate(files, start=1):
        size_kb = p.stat().st_size / 1024.0
        LOG.info("[%d] %s (%.1f KB)", i, p.name, size_kb)
    LOG.info("[0] Exit")

    while True:
        s = input("\nNumber: ").strip()
        if s.isdigit():
            n = int(s)
            if n == 0:
                return None
            if 1 <= n <= len(files):
                return files[n - 1]
        LOG.error("Invalid input.")


def ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    d = "Y/n" if default_yes else "y/N"
    while True:
        s = input(f"{prompt} [{d}]: ").strip().lower()
        if not s:
            return default_yes
        if s in ("y", "yes"):
            return True
        if s in ("n", "no"):
            return False
        LOG.error("Please answer Y or N.")


def get_properties_node(item: ET.Element) -> Optional[ET.Element]:
    for child in item:
        if local_tag(child.tag) == "Properties":
            return child
    return None


def get_name_from_properties(props: Optional[ET.Element]) -> Optional[str]:
    if props is None:
        return None
    for p in props:
        if local_tag(p.tag) in NAME_PROP_TAGS and p.attrib.get("name") == "Name":
            return p.text or ""
    return None


def get_source_from_properties(props: Optional[ET.Element]) -> Optional[str]:
    if props is None:
        return None
    for p in props:
        if p.attrib.get("name") == SOURCE_PROP_NAME and local_tag(p.tag) in SOURCE_TAG_NAMES:
            return p.text or ""
    return None


def get_value_from_properties(props: Optional[ET.Element]) -> Optional[str]:
    if props is None:
        return None
    for p in props:
        if p.attrib.get("name") == "Value":
            return (p.text or "").strip()
    return None


def iter_top_level_items(roblox_root: ET.Element) -> List[ET.Element]:
    direct_items = [c for c in list(roblox_root) if local_tag(c.tag) == "Item"]
    for it in direct_items:
        if it.attrib.get("class") == "DataModel":
            return [c for c in list(it) if local_tag(c.tag) == "Item"]
    return direct_items


# ----------------- Duplicate name handling (per-parent) -----------------
def unique_child_name(parent_used: Dict[str, int], base_safe: str, referent: str) -> str:
    if base_safe not in parent_used:
        parent_used[base_safe] = 1
        return base_safe
    parent_used[base_safe] += 1
    n = parent_used[base_safe]
    tail = sanitize_filename(referent[-8:]) if referent else ""
    return f"{base_safe}__{n}__{tail}" if tail else f"{base_safe}__{n}"


# ----------------- AttributesSerialize decoding -----------------
class BinReader:
    def __init__(self, data: bytes):
        self.data = data
        self.i = 0

    def remaining(self) -> int:
        return len(self.data) - self.i

    def read_u8(self) -> int:
        if self.remaining() < 1:
            raise ValueError("Unexpected EOF (u8)")
        v = self.data[self.i]
        self.i += 1
        return v

    def read_u32(self) -> int:
        if self.remaining() < 4:
            raise ValueError("Unexpected EOF (u32)")
        v = struct.unpack_from("<I", self.data, self.i)[0]
        self.i += 4
        return v

    def read_i32(self) -> int:
        if self.remaining() < 4:
            raise ValueError("Unexpected EOF (i32)")
        v = struct.unpack_from("<i", self.data, self.i)[0]
        self.i += 4
        return v

    def read_f32(self) -> float:
        if self.remaining() < 4:
            raise ValueError("Unexpected EOF (f32)")
        v = struct.unpack_from("<f", self.data, self.i)[0]
        self.i += 4
        return v

    def read_f64(self) -> float:
        if self.remaining() < 8:
            raise ValueError("Unexpected EOF (f64)")
        v = struct.unpack_from("<d", self.data, self.i)[0]
        self.i += 8
        return v

    def read_bytes(self, n: int) -> bytes:
        if self.remaining() < n:
            raise ValueError("Unexpected EOF (bytes)")
        v = self.data[self.i : self.i + n]
        self.i += n
        return v

    def read_string(self) -> str:
        # String = u32 size + bytes (UTF-8)
        n = self.read_u32()
        raw = self.read_bytes(n)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


def decode_attributes_serialize(blob: bytes) -> List[Tuple[str, str, str]]:
    """
    Decodes Instance.AttributesSerialize (binary dictionary).
    Supported value types:
      0x02 string
      0x03 bool
      0x05 float32 (number)
      0x06 float64 (number)  <-- typical for attributes of type "number"
    Other types are exported as "unknown(0x..)" with a short note.
    """
    r = BinReader(blob)
    out: List[Tuple[str, str, str]] = []

    size = r.read_u32()  # number of entries
    seen_keys: set[str] = set()

    for _ in range(size):
        key = r.read_string()
        vtype = r.read_u8()

        if key in seen_keys:
            # Spec: duplicate keys are discarded when decoding.
            # We'll still need to skip the value bytes.
            pass
        else:
            seen_keys.add(key)

        if vtype == 0x02:  # string
            val = r.read_string()
            if key in seen_keys:
                out.append((key, "string", val))
        elif vtype == 0x03:  # bool (u8)
            b = r.read_u8()
            val = "true" if b != 0 else "false"
            if key in seen_keys:
                out.append((key, "boolean", val))
        elif vtype == 0x05:  # float32
            f = r.read_f32()
            if key in seen_keys:
                out.append((key, "number", repr(f)))
        elif vtype == 0x06:  # float64 (double)
            f = r.read_f64()
            if key in seen_keys:
                out.append((key, "number", repr(f)))
        elif vtype == 0x09:  # UDim (8 bytes)
            scale = r.read_f32()
            offset = r.read_i32()
            if key in seen_keys:
                out.append((key, "UDim", f"{{Scale={scale}, Offset={offset}}}"))
        elif vtype == 0x0A:  # UDim2 (16 bytes)
            x_scale = r.read_f32()
            x_offset = r.read_i32()
            y_scale = r.read_f32()
            y_offset = r.read_i32()
            if key in seen_keys:
                out.append((key, "UDim2", f"{{X={{Scale={x_scale}, Offset={x_offset}}}, Y={{Scale={y_scale}, Offset={y_offset}}}}}"))
        elif vtype == 0x0E:  # BrickColor (u32)
            num = r.read_u32()
            if key in seen_keys:
                out.append((key, "BrickColor", str(num)))
        elif vtype == 0x0F:  # Color3 (3*f32)
            rr = r.read_f32()
            gg = r.read_f32()
            bb = r.read_f32()
            if key in seen_keys:
                out.append((key, "Color3", f"{{R={rr}, G={gg}, B={bb}}}"))
        elif vtype == 0x10:  # Vector2 (2*f32)
            xx = r.read_f32()
            yy = r.read_f32()
            if key in seen_keys:
                out.append((key, "Vector2", f"{{X={xx}, Y={yy}}}"))
        elif vtype == 0x11:  # Vector3 (3*f32)
            xx = r.read_f32()
            yy = r.read_f32()
            zz = r.read_f32()
            if key in seen_keys:
                out.append((key, "Vector3", f"{{X={xx}, Y={yy}, Z={zz}}}"))
        else:
            # For unsupported types, we cannot reliably skip without knowing size.
            # We'll stop decoding to avoid desync and export a warning.
            out.append((key, f"unknown(0x{vtype:02X})", "Unsupported attribute type; decoding stopped"))
            break

    return out


def parse_attributes(props: Optional[ET.Element]) -> List[Tuple[str, str, str]]:
    """
    Preferred: decode BinaryString property named "AttributesSerialize".
    Fallback: legacy-like <Attributes><Attribute .../> nodes (rare in modern exports).
    """
    if props is None:
        return []

    # 1) AttributesSerialize (BinaryString Base64)
    for p in props:
        if p.attrib.get("name") == "AttributesSerialize" and local_tag(p.tag) == "BinaryString":
            b64 = (p.text or "").strip()
            if not b64:
                return []
            try:
                blob = base64.b64decode(b64, validate=False)
            except Exception:
                # If Base64 is malformed, give up silently (still return fallback attributes if present).
                blob = b""
            if blob:
                try:
                    return decode_attributes_serialize(blob)
                except Exception:
                    # If decoding fails, continue to fallback parse.
                    pass

    # 2) Fallback: <Attributes><Attribute .../></Attributes>
    out: List[Tuple[str, str, str]] = []
    for node in props:
        if local_tag(node.tag) != "Attributes":
            continue
        for attr in list(node):
            if local_tag(attr.tag) != "Attribute":
                continue
            aname = (attr.attrib.get("name") or "").strip()
            atype = (attr.attrib.get("type") or "").strip() or "unknown"
            aval = attr.attrib.get("value")
            if aval is None:
                aval = (attr.text or "").strip()
            else:
                aval = str(aval).strip()
            if aname:
                out.append((aname, atype, aval))
    return out


# ----------------- Bundle builder -----------------
def build_bundle(in_path: Path, include_context: bool) -> Tuple[Path, Path, List[ScriptRecord]]:
    xml_text = strip_junk_before_roblox(read_text(in_path))

    try:
        root = ET.fromstring(xml_text)
        tree = ET.ElementTree(root)
    except ET.ParseError as e:
        pos = getattr(e, "position", None)
        where = f" (line {pos[0]}, col {pos[1]})" if pos else ""
        raise RuntimeError(f"XML parse error{where}: {e}") from e

    roblox_root = tree.getroot()
    top_items = iter_top_level_items(roblox_root)
    if not top_items:
        raise RuntimeError("No top-level <Item> found. Export may be incomplete/corrupted.")

    bundle_dir = OUTPUT_DIR / f"{in_path.stem}_bundle"

    # ✅ Fix: wipe old bundle dir to prevent mixed outputs (folders + loose files)
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)

    scripts_dir = bundle_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    scripts: List[ScriptRecord] = []
    contexts: List[ContextRecord] = []
    attributes: List[AttributeRecord] = []
    hierarchy_lines: List[str] = []

    used_names_by_parent: Dict[str, Dict[str, int]] = {}

    def walk(item: ET.Element, parent_path: str, depth: int) -> None:
        class_name = item.attrib.get("class", "UnknownClass")
        referent = item.attrib.get("referent", "")
        props = get_properties_node(item)

        name = get_name_from_properties(props)
        if name is None:
            name = referent or "Unnamed"

        base_safe = sanitize_filename(name)
        used = used_names_by_parent.setdefault(parent_path, {})
        safe_name = unique_child_name(used, base_safe, referent)

        full_path = f"{parent_path}/{safe_name}" if parent_path else safe_name
        indent = " " * depth
        hierarchy_lines.append(f"{indent}- {safe_name} ({class_name})")

        # Attributes (correct decoding from AttributesSerialize)
        for aname, atype, aval in parse_attributes(props):
            attributes.append(
                AttributeRecord(
                    owner_class=class_name,
                    owner_name=name,
                    owner_path=full_path,
                    attr_name=aname,
                    attr_type=atype,
                    attr_value=aval,
                )
            )

        # Context (detailed)
        if include_context and class_name in CONTEXT_CLASSES:
            detail: Dict[str, str] = {}
            if class_name in {"RemoteEvent", "RemoteFunction"}:
                detail["kind"] = "Remote"
            elif class_name in {"BindableEvent", "BindableFunction"}:
                detail["kind"] = "Bindable"
            elif class_name in VALUE_OBJECT_CLASSES:
                detail["kind"] = "ValueObject"
                v = get_value_from_properties(props)
                if v is not None:
                    detail["initial_value"] = v
            else:
                detail["kind"] = "Context"
            contexts.append(ContextRecord(class_name=class_name, name=name, full_path=full_path, details=detail))

        # Scripts
        if class_name in SCRIPT_CLASSES:
            src = get_source_from_properties(props) or ""
            suffix = (
                ".server.lua" if class_name == "Script"
                else ".client.lua" if class_name == "LocalScript"
                else ".lua"
            )

            # ✅ Fix: NO loose scripts. Always export inside the hierarchy folder structure.
            parts = [sanitize_filename(p) for p in full_path.split("/")]
            # File name is the leaf object name; parent directories are the rest.
            dir_parts = parts[:-1]
            file_base = parts[-1]
            rel = Path(*dir_parts) / f"{file_base}{suffix}"
            out_file = scripts_dir / rel
            out_file.parent.mkdir(parents=True, exist_ok=True)

            header = (
                f"-- Extracted from RBXMX\n"
                f"-- Class: {class_name}\n"
                f"-- Name: {name}\n"
                f"-- Path: {full_path}\n\n"
            )
            safe_write_text(out_file, header + src, encoding="utf-8")

            scripts.append(
                ScriptRecord(
                    class_name=class_name,
                    name=name,
                    full_path=full_path,
                    rel_file=str(Path("scripts") / rel),
                    source_len=len(src),
                )
            )

        for child in item:
            if local_tag(child.tag) == "Item":
                walk(child, full_path, depth + 1)

    for it in top_items:
        walk(it, parent_path="", depth=0)

    # HIERARCHY
    safe_write_text(bundle_dir / "HIERARCHY.txt", "\n".join(hierarchy_lines), encoding="utf-8")

    # INDEX
    with safe_open_csv(bundle_dir / "INDEX.csv") as f:
        w = csv.writer(f)
        w.writerow(["class", "name", "path", "file", "source_len"])
        for s in scripts:
            w.writerow([s.class_name, s.name, s.full_path, s.rel_file, s.source_len])

    # ATTRIBUTES
    with safe_open_csv(bundle_dir / "ATTRIBUTES.csv") as f:
        w = csv.writer(f)
        w.writerow(["owner_class", "owner_name", "owner_path", "attr_name", "attr_type", "attr_value"])
        for a in attributes:
            w.writerow([a.owner_class, a.owner_name, a.owner_path, a.attr_name, a.attr_type, a.attr_value])

    if attributes:
        lines = ["# Attributes extracted", ""]
        for a in attributes:
            lines.append(f"- {a.owner_path} ({a.owner_class}) :: {a.attr_name} [{a.attr_type}] = {a.attr_value}")
        safe_write_text(bundle_dir / "ATTRIBUTES.txt", "\n".join(lines), encoding="utf-8")
    else:
        safe_write_text(bundle_dir / "ATTRIBUTES.txt", "# Attributes extracted\n\n(none)\n", encoding="utf-8")

    # CONTEXT
    if include_context:
        remotes = [c for c in contexts if c.details.get("kind") == "Remote"]
        bindables = [c for c in contexts if c.details.get("kind") == "Bindable"]
        values = [c for c in contexts if c.details.get("kind") == "ValueObject"]
        others = [c for c in contexts if c.details.get("kind") not in {"Remote", "Bindable", "ValueObject"}]

        lines = ["# Context objects (detailed)", ""]
        if remotes:
            lines += ["## Remotes", ""]
            for c in remotes:
                lines.append(f"- {c.full_path} ({c.class_name})")
            lines.append("")
        if bindables:
            lines += ["## Bindables", ""]
            for c in bindables:
                lines.append(f"- {c.full_path} ({c.class_name})")
            lines.append("")
        if values:
            lines += ["## ValueObjects", ""]
            for c in values:
                iv = c.details.get("initial_value", "")
                lines.append(f"- {c.full_path} ({c.class_name})" + (f" = {iv}" if iv != "" else ""))
            lines.append("")
        if others:
            lines += ["## Other context", ""]
            for c in others:
                lines.append(f"- {c.full_path} ({c.class_name})")
            lines.append("")

        safe_write_text(bundle_dir / "CONTEXT.txt", "\n".join(lines), encoding="utf-8")

    # ZIP
    zip_path = OUTPUT_DIR / f"{in_path.stem}_bundle.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # scripts/
        for p in sorted((bundle_dir / "scripts").rglob("*")):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(bundle_dir)))

        for fname in ["HIERARCHY.txt", "INDEX.csv", "ATTRIBUTES.csv", "ATTRIBUTES.txt"]:
            p = bundle_dir / fname
            if p.exists():
                z.write(p, arcname=p.name)

        if include_context:
            p = bundle_dir / "CONTEXT.txt"
            if p.exists():
                z.write(p, arcname=p.name)

    return bundle_dir, zip_path, scripts


# ----------------- Main -----------------
def main() -> None:
    setup_logging()
    ensure_dirs()

    hr()
    LOG.info("RBXBundle (RBXMX/RBXLX Extractor) ✅")
    hr()
    LOG.info("input/:  %s", INPUT_DIR.resolve())
    LOG.info("output/: %s", OUTPUT_DIR.resolve())

    files = list_candidates()
    if not files:
        LOG.info("No files found in input/. Put a .rbxmx/.rbxlx/.xml there and run again.")
        return

    chosen = pick_file(files)
    if chosen is None:
        return

    include_context = ask_yes_no("Include CONTEXT.txt (remotes/values/folders)?", default_yes=True)

    try:
        bundle_dir, zip_path, scripts = build_bundle(chosen, include_context=include_context)
    except Exception as e:
        LOG.error("❌ Failed: %s", e)
        return

    nonempty = sum(1 for s in scripts if s.source_len > 0)
    empty = len(scripts) - nonempty

    hr()
    LOG.info("✅ Done!")
    LOG.info("File: %s", chosen.name)
    LOG.info("Scripts found: %d", len(scripts))
    LOG.info(" - non-empty Source: %d", nonempty)
    LOG.info(" - empty Source: %d", empty)
    LOG.info("Bundle dir: %s", bundle_dir)
    LOG.info("ZIP: %s", zip_path)
    hr()
    LOG.info("Tip: send the ZIP to an AI assistant for full project context.")


if __name__ == "__main__":
    main()