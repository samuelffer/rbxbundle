#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET

# ----------------- Config -----------------
INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
SUPPORTED_EXTS = {".rbxmx", ".xml", ".txt"}

SCRIPT_CLASSES = {"Script", "LocalScript", "ModuleScript"}
SOURCE_PROP_NAME = "Source"  # Alguns exports usam ProtectedString; outros podem variar.
SOURCE_TAG_NAMES = {"ProtectedString", "string", "SharedString"}
NAME_PROP_TAGS = {"string"}

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

INVALID_FS_CHARS = r'<>:"/\|?*\0'
INVALID_FS_RE = re.compile(f"[{re.escape(INVALID_FS_CHARS)}]")


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


# ----------------- Helpers (robust I/O) -----------------
def ensure_dirs() -> None:
    """Cria diretórios padrões (input/output) com tratamento de erro."""
    try:
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"Falha ao criar diretórios '{INPUT_DIR}'/'{OUTPUT_DIR}'. "
            f"Verifique permissões e o filesystem. Detalhe: {e}"
        ) from e


def safe_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Escrita robusta com mensagem de erro útil."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
    except OSError as e:
        raise RuntimeError(
            f"Falha ao escrever arquivo '{path}'. "
            f"Verifique permissões/espaço em disco. Detalhe: {e}"
        ) from e


def safe_open_csv(path: Path):
    """Abre CSV para escrita com tratamento de erro (retorna file handle)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("w", newline="", encoding="utf-8")
    except OSError as e:
        raise RuntimeError(
            f"Falha ao abrir '{path}' para escrita. Verifique permissões. Detalhe: {e}"
        ) from e


def hr() -> None:
    print("-" * 64)


def sanitize_filename(s: str) -> str:
    s = INVALID_FS_RE.sub("_", s)
    s = s.strip().strip(".")
    return s or "_"


def read_text(path: Path) -> str:
    """Leitura robusta com fallback de encoding e tratamento de erro."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise RuntimeError(
            f"Falha ao ler '{path}'. Verifique se o arquivo existe e permissões. Detalhe: {e}"
        ) from e

    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def list_candidates() -> List[Path]:
    files: List[Path] = []
    try:
        for p in sorted(INPUT_DIR.iterdir()):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                files.append(p)
    except OSError as e:
        raise RuntimeError(
            f"Falha ao listar diretório '{INPUT_DIR}'. Verifique permissões. Detalhe: {e}"
        ) from e
    return files


def pick_file(files: List[Path]) -> Optional[Path]:
    hr()
    print("Selecione um arquivo em ./input/")
    hr()
    for i, p in enumerate(files, start=1):
        try:
            size_kb = p.stat().st_size / 1024.0
        except OSError:
            size_kb = 0.0
        print(f"[{i}] {p.name} ({size_kb:.1f} KB)")
    print("[0] Sair")

    while True:
        s = input("\nNúmero: ").strip()
        if s.isdigit():
            n = int(s)
            if n == 0:
                return None
            if 1 <= n <= len(files):
                return files[n - 1]
        print("Entrada inválida.")


def ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    d = "S/n" if default_yes else "s/N"
    while True:
        s = input(f"{prompt} [{d}]: ").strip().lower()
        if not s:
            return default_yes
        if s in ("s", "sim", "y", "yes"):
            return True
        if s in ("n", "nao", "não", "no"):
            return False
        print("Responda com S ou N.")


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


def iter_top_level_items(roblox_root: ET.Element) -> List[ET.Element]:
    """
    Retorna todas as raízes relevantes para caminhar.
    Caso exista um DataModel no topo, caminhamos dentro dele.
    Caso contrário, caminhamos por todos os <Item> diretamente sob <roblox>.
    """
    direct_items = [c for c in list(roblox_root) if local_tag(c.tag) == "Item"]
    for it in direct_items:
        if it.attrib.get("class") == "DataModel":
            return [c for c in list(it) if local_tag(c.tag) == "Item"]
    return direct_items


def strip_junk_before_roblox(xml_text: str) -> str:
    """
    Alguns exports podem conter lixo/bytes antes de <roblox>.
    Faz um corte heurístico para o primeiro '<roblox' se existir.
    """
    idx = xml_text.find("<roblox")
    if idx > 0:
        return xml_text[idx:]
    return xml_text


def build_bundle(in_path: Path, include_context: bool) -> Tuple[Path, Path, List[ScriptRecord]]:
    xml_text = read_text(in_path)
    xml_text = strip_junk_before_roblox(xml_text)

    # 1.1 - Tratamento de erros de parsing XML
    try:
        root = ET.fromstring(xml_text)
        tree = ET.ElementTree(root)
    except ET.ParseError as e:
        # ParseError tem .position em muitas versões; se não existir, cai no str(e)
        pos = getattr(e, "position", None)
        where = f" (linha {pos[0]}, coluna {pos[1]})" if pos else ""
        raise RuntimeError(
            f"Erro ao parsear XML{where}: {e}. "
            f"Verifique se o arquivo está íntegro (export completo, sem truncamento)."
        ) from e

    roblox_root = tree.getroot()
    if local_tag(roblox_root.tag).lower() != "roblox":
        # Ainda pode funcionar, mas avisamos em runtime (sem quebrar)
        print("⚠️ Aviso: raiz do XML não é <roblox>. Tentando continuar mesmo assim...")

    top_items = iter_top_level_items(roblox_root)
    if not top_items:
        raise RuntimeError(
            "Não encontrei <Item> de topo no XML. Export pode estar incompleto/corrompido."
        )

    bundle_dir = OUTPUT_DIR / f"{in_path.stem}_bundle"
    scripts_dir = bundle_dir / "scripts"

    # 1.2 - Validação de caminhos/permissões (mkdir robusto)
    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        scripts_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"Falha ao criar diretórios de bundle em '{bundle_dir}'. "
            f"Verifique permissões/espaço. Detalhe: {e}"
        ) from e

    scripts: List[ScriptRecord] = []
    contexts: List[ContextRecord] = []
    hierarchy_lines: List[str] = []

    def walk(item: ET.Element, parent_path: str, depth: int) -> None:
        class_name = item.attrib.get("class", "UnknownClass")
        props = get_properties_node(item)

        name = get_name_from_properties(props)
        if name is None:
            name = item.attrib.get("referent", "Unnamed")

        safe_name = sanitize_filename(name)
        full_path = f"{parent_path}/{safe_name}" if parent_path else safe_name

        indent = " " * depth
        hierarchy_lines.append(f"{indent}- {safe_name} ({class_name})")

        if include_context and class_name in CONTEXT_CLASSES:
            contexts.append(ContextRecord(class_name=class_name, name=name, full_path=full_path))

        if class_name in SCRIPT_CLASSES:
            src = get_source_from_properties(props) or ""
            suffix = (
                ".server.lua" if class_name == "Script"
                else ".client.lua" if class_name == "LocalScript"
                else ".lua"
            )

            rel = Path(*(sanitize_filename(p) for p in full_path.split("/"))).with_suffix(suffix)
            out_file = scripts_dir / rel

            header = (
                f"-- Extracted from RBXMX\n"
                f"-- Class: {class_name}\n"
                f"-- Name: {name}\n"
                f"-- Path: {full_path}\n\n"
            )

            # 1.2 - Escrita robusta de scripts
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

    # HIERARCHY (robusto)
    safe_write_text(bundle_dir / "HIERARCHY.txt", "\n".join(hierarchy_lines), encoding="utf-8")

    # INDEX.csv (robusto)
    with safe_open_csv(bundle_dir / "INDEX.csv") as f:
        w = csv.writer(f)
        w.writerow(["class", "name", "path", "file", "source_len"])
        for s in scripts:
            w.writerow([s.class_name, s.name, s.full_path, s.rel_file, s.source_len])

    # CONTEXT.txt (optional, robusto)
    if include_context:
        lines = ["# Context objects (minimal)"]
        for c in contexts:
            lines.append(f"- {c.full_path} ({c.class_name})")
        safe_write_text(bundle_dir / "CONTEXT.txt", "\n".join(lines), encoding="utf-8")

    # ZIP (robusto)
    zip_path = OUTPUT_DIR / f"{in_path.stem}_bundle.zip"
    try:
        if zip_path.exists():
            zip_path.unlink()
    except OSError as e:
        raise RuntimeError(
            f"Falha ao remover ZIP existente '{zip_path}'. Verifique permissões. Detalhe: {e}"
        ) from e

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            # scripts/
            for p in sorted((bundle_dir / "scripts").rglob("*")):
                if p.is_file():
                    z.write(p, arcname=str(p.relative_to(bundle_dir)))

            # always
            for fname in ["HIERARCHY.txt", "INDEX.csv"]:
                p = bundle_dir / fname
                if p.exists():
                    z.write(p, arcname=p.name)

            if include_context:
                p = bundle_dir / "CONTEXT.txt"
                if p.exists():
                    z.write(p, arcname=p.name)
    except (OSError, zipfile.BadZipFile, RuntimeError) as e:
        # zipfile pode propagar erros de I/O e/ou erros do próprio módulo
        raise RuntimeError(
            f"Falha ao criar ZIP '{zip_path}'. Verifique permissões/espaço e integridade dos arquivos. "
            f"Detalhe: {e}"
        ) from e

    return bundle_dir, zip_path, scripts


# ----------------- Main (UI) -----------------
def main() -> None:
    try:
        ensure_dirs()
    except Exception as e:
        print("\n❌ Falhou:", e)
        return

    hr()
    print("Roblox Bundle Extractor (bundle-only) ✅")
    hr()
    print(f" input/: {INPUT_DIR.resolve()}")
    print(f" output/: {OUTPUT_DIR.resolve()}")

    try:
        files = list_candidates()
    except Exception as e:
        print("\n❌ Falhou:", e)
        return

    if not files:
        print("\nNenhum arquivo em input/. Coloque um .rbxmx/.xml/.txt lá e rode novamente.")
        return

    chosen = pick_file(files)
    if chosen is None:
        return

    include_context = ask_yes_no(
        "Incluir CONTEXT.txt (remotes/values/folders úteis)?",
        default_yes=True
    )

    try:
        bundle_dir, zip_path, scripts = build_bundle(chosen, include_context=include_context)
    except Exception as e:
        print("\n❌ Falhou:", e)
        return

    nonempty = sum(1 for s in scripts if s.source_len > 0)
    empty = len(scripts) - nonempty

    hr()
    print("✅ Concluído!")
    print(f"Arquivo: {chosen.name}")
    print(f"Scripts detectados: {len(scripts)}")
    print(f" - com Source não-vazio: {nonempty}")
    print(f" - com Source vazio: {empty} (pode ser export do Studio / scripts vazios / protegidos)")
    print(f"Bundle dir: {bundle_dir}")
    print(f"ZIP: {zip_path}")
    hr()
    print("➡️ Envie o ZIP aqui no chat e diga: 'Analise o bundle'.")


if __name__ == "__main__":
    main()