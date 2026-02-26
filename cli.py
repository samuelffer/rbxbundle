from __future__ import annotations

from pathlib import Path
import logging

from rbxbundle.utils import ensure_dirs, setup_logging
from rbxbundle.generator import create_bundle

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
SUPPORTED_EXTS = {".rbxmx", ".rbxlx", ".xml", ".txt"}

LOG = logging.getLogger("rbxbundle")

def list_candidates():
    files = []
    for p in sorted(INPUT_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            files.append(p)
    return files

def pick_file(files):
    LOG.info("-" * 64)
    LOG.info("Select a file from ./input/")
    LOG.info("-" * 64)
    for i, p in enumerate(files, start=1):
        try:
            size_kb = p.stat().st_size / 1024.0
        except OSError:
            size_kb = 0.0
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

def main() -> None:
    setup_logging()
    ensure_dirs(INPUT_DIR, OUTPUT_DIR)

    LOG.info("-" * 64)
    LOG.info("RBXBundle (RBXMX/RBXLX Extractor) ✅")
    LOG.info("-" * 64)
    LOG.info("input/:  %s", INPUT_DIR.resolve())
    LOG.info("output/: %s", OUTPUT_DIR.resolve())

    files = list_candidates()
    if not files:
        LOG.info("No files found in input/. Put a .rbxmx/.rbxlx/.xml there and run again.")
        return

    chosen = pick_file(files)
    if chosen is None:
        return

    include_context = ask_yes_no("Include CONTEXT.txt (detailed)?", default_yes=True)

    try:
        bundle_dir, zip_path, scripts = create_bundle(chosen, output_dir=OUTPUT_DIR, include_context=include_context)
    except Exception as e:
        LOG.error("❌ Failed: %s", e)
        return

    nonempty = sum(1 for s in scripts if s.source_len > 0)
    empty = len(scripts) - nonempty

    LOG.info("-" * 64)
    LOG.info("✅ Done!")
    LOG.info("File: %s", chosen.name)
    LOG.info("Scripts found: %d", len(scripts))
    LOG.info(" - non-empty Source: %d", nonempty)
    LOG.info(" - empty Source: %d", empty)
    LOG.info("Bundle dir: %s", bundle_dir)
    LOG.info("ZIP: %s", zip_path)
    LOG.info("-" * 64)

if __name__ == "__main__":
    main()
