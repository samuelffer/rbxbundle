"""RBXBundle CLI — command-line interface for the rbxbundle tool."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rbxbundle.utils import ensure_dirs, setup_logging
from rbxbundle.generator import create_bundle

LOG = logging.getLogger("rbxbundle")

SUPPORTED_EXTS = {".rbxmx", ".rbxlx", ".xml", ".txt"}
DEFAULT_INPUT_DIR = Path("input")
DEFAULT_OUTPUT_DIR = Path("output")


# ---------------------------------------------------------------------------
# Sub-command: build
# ---------------------------------------------------------------------------

def cmd_build(args: argparse.Namespace) -> int:
    in_path = Path(args.file)

    if not in_path.exists():
        LOG.error("File not found: %s", in_path)
        return 1

    if in_path.suffix.lower() not in SUPPORTED_EXTS:
        LOG.warning(
            "Unsupported extension '%s'. Supported: %s",
            in_path.suffix,
            ", ".join(sorted(SUPPORTED_EXTS)),
        )

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    include_context = not args.no_context

    LOG.info("=" * 64)
    LOG.info("rbxbundle build")
    LOG.info("  Input  : %s", in_path.resolve())
    LOG.info("  Output : %s", out_dir.resolve())
    LOG.info("  Context: %s", "yes" if include_context else "no")
    LOG.info("=" * 64)

    try:
        bundle_dir, zip_path, scripts = create_bundle(
            in_path, output_dir=out_dir, include_context=include_context
        )
    except Exception as exc:
        LOG.error("Build failed: %s", exc)
        return 1

    nonempty = sum(1 for s in scripts if s.source_len > 0)
    empty = len(scripts) - nonempty

    LOG.info("Done.")
    LOG.info("  Scripts   : %d total (%d non-empty, %d empty)", len(scripts), nonempty, empty)
    LOG.info("  Bundle dir: %s", bundle_dir)
    LOG.info("  ZIP       : %s", zip_path)
    LOG.info("=" * 64)
    return 0


# ---------------------------------------------------------------------------
# Sub-command: inspect
# ---------------------------------------------------------------------------

def cmd_inspect(args: argparse.Namespace) -> int:
    in_path = Path(args.file)

    if not in_path.exists():
        LOG.error("File not found: %s", in_path)
        return 1

    import xml.etree.ElementTree as ET
    from rbxbundle.utils import read_text, strip_junk_before_roblox
    from rbxbundle.parser import iter_top_level_items
    from rbxbundle.generator import SCRIPT_CLASSES, CONTEXT_CLASSES

    xml_text = strip_junk_before_roblox(read_text(in_path))
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        LOG.error("XML parse error: %s", exc)
        return 1

    top_items = iter_top_level_items(root)
    if not top_items:
        LOG.error("No top-level <Item> found. File may be corrupt.")
        return 1

    script_count = 0
    context_count = 0
    total_count = 0

    def walk(item: ET.Element) -> None:
        nonlocal script_count, context_count, total_count
        cls = item.attrib.get("class", "")
        total_count += 1
        if cls in SCRIPT_CLASSES:
            script_count += 1
        if cls in CONTEXT_CLASSES:
            context_count += 1
        for child in item:
            if child.tag.split("}")[-1] == "Item":
                walk(child)

    for it in top_items:
        walk(it)

    size_kb = in_path.stat().st_size / 1024.0

    print(f"\nFile     : {in_path.name}")
    print(f"Size     : {size_kb:.1f} KB")
    print(f"Instances: {total_count}")
    print(f"Scripts  : {script_count}  (Script / LocalScript / ModuleScript)")
    print(f"Context  : {context_count}  (RemoteEvent, Folder, ValueObject, ...)")
    print()
    return 0


# ---------------------------------------------------------------------------
# Sub-command: list
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    in_dir = Path(args.dir)
    if not in_dir.exists():
        LOG.error("Directory not found: %s", in_dir)
        return 1

    files = sorted(
        p for p in in_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )

    if not files:
        print(f"No supported files found in {in_dir}/")
        print(f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTS))}")
        return 0

    print(f"\nFiles in {in_dir}/\n")
    for p in files:
        size_kb = p.stat().st_size / 1024.0
        print(f"  {p.name:<40}  {size_kb:>8.1f} KB")
    print()
    return 0


# ---------------------------------------------------------------------------
# Interactive fallback (legacy UX)
# ---------------------------------------------------------------------------

def _interactive() -> int:
    ensure_dirs(DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR)

    LOG.info("=" * 64)
    LOG.info("RBXBundle -- interactive mode")
    LOG.info("(Tip: use  rbxbundle build <file>  to skip prompts)")
    LOG.info("=" * 64)
    LOG.info("input/ : %s", DEFAULT_INPUT_DIR.resolve())
    LOG.info("output/: %s", DEFAULT_OUTPUT_DIR.resolve())

    files = sorted(
        p for p in DEFAULT_INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )

    if not files:
        LOG.info("No files found in input/. Add a .rbxmx/.rbxlx/.xml and run again.")
        return 0

    LOG.info("-" * 64)
    for i, p in enumerate(files, 1):
        size_kb = p.stat().st_size / 1024.0
        LOG.info("[%d] %s  (%.1f KB)", i, p.name, size_kb)
    LOG.info("[0] Exit")

    while True:
        s = input("\nNumber: ").strip()
        if s.isdigit():
            n = int(s)
            if n == 0:
                return 0
            if 1 <= n <= len(files):
                chosen = files[n - 1]
                break
        LOG.error("Invalid input.")

    while True:
        s = input("Include CONTEXT.txt? [Y/n]: ").strip().lower()
        if s in ("", "y", "yes"):
            include_context = True
            break
        if s in ("n", "no"):
            include_context = False
            break
        LOG.error("Please answer Y or N.")

    try:
        bundle_dir, zip_path, scripts = create_bundle(
            chosen, output_dir=DEFAULT_OUTPUT_DIR, include_context=include_context
        )
    except Exception as exc:
        LOG.error("Failed: %s", exc)
        return 1

    nonempty = sum(1 for s in scripts if s.source_len > 0)
    empty = len(scripts) - nonempty

    LOG.info("=" * 64)
    LOG.info("Done!")
    LOG.info("  File   : %s", chosen.name)
    LOG.info("  Scripts: %d (%d non-empty, %d empty)", len(scripts), nonempty, empty)
    LOG.info("  Dir    : %s", bundle_dir)
    LOG.info("  ZIP    : %s", zip_path)
    LOG.info("=" * 64)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rbxbundle",
        description="rbxbundle -- Roblox model extractor and AI context bundler.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  rbxbundle build MyModel.rbxmx
  rbxbundle build MyModel.rbxmx --output ./bundles
  rbxbundle build MyModel.rbxmx --no-context
  rbxbundle inspect MyModel.rbxmx
  rbxbundle list
  rbxbundle list --dir ./models
""",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug-level logging.",
    )

    sub = parser.add_subparsers(dest="command")

    # build
    p_build = sub.add_parser(
        "build",
        help="Parse a Roblox file and generate the bundle.",
        description="Parse a .rbxmx/.rbxlx file and write scripts, hierarchy, context, dependency graph, and a ZIP to the output directory.",
    )
    p_build.add_argument("file", help="Path to the .rbxmx / .rbxlx / .xml file.")
    p_build.add_argument(
        "--output", "-o",
        default=str(DEFAULT_OUTPUT_DIR),
        metavar="DIR",
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    p_build.add_argument(
        "--no-context",
        action="store_true",
        help="Skip generation of CONTEXT.txt (RemoteEvents, ValueObjects, etc.).",
    )

    # inspect
    p_inspect = sub.add_parser(
        "inspect",
        help="Show a quick summary of a file without extracting.",
        description="Print instance counts and file size without writing any output.",
    )
    p_inspect.add_argument("file", help="Path to the .rbxmx / .rbxlx / .xml file.")

    # list
    p_list = sub.add_parser(
        "list",
        help="List supported files in a directory.",
        description="List all .rbxmx / .rbxlx / .xml files in a directory.",
    )
    p_list.add_argument(
        "--dir", "-d",
        default=str(DEFAULT_INPUT_DIR),
        metavar="DIR",
        help=f"Directory to scan (default: {DEFAULT_INPUT_DIR}).",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    setup_logging(level)

    if not args.command:
        sys.exit(_interactive())

    dispatch = {
        "build": cmd_build,
        "inspect": cmd_inspect,
        "list": cmd_list,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
