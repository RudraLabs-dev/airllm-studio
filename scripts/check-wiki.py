#!/usr/bin/env python3
"""Check the wiki/ folder before it is published to the GitHub wiki.

    python3 scripts/check-wiki.py wiki

Checks: Home.md exists; page names are wiki-safe; every relative link, image and sidebar entry points at
a page or file that exists; section anchors (Page#section, #section) match a heading; code fences are closed.
"""
import re
import sys
from pathlib import Path

PAGE_NAME = re.compile(r"^_?[A-Za-z0-9][A-Za-z0-9-]*$")      # Getting-Started, _Sidebar
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
SPECIAL = {"_Sidebar", "_Footer", "_Header"}
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)


def slug(heading: str) -> str:
    """GitHub's heading anchor: markup dropped, lower-cased, punctuation removed, spaces become '-'."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)          # [text](url) -> text
    text = re.sub(r"[`*]", "", text).lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.strip().replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    """All heading anchors of a page, with GitHub's -1, -2 suffixes for repeated headings."""
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    seen: dict[str, int] = {}
    found: set[str] = set()
    for m in HEADING.finditer(body):
        base = slug(m.group(1))
        n = seen.get(base, 0)
        seen[base] = n + 1
        found.add(base if n == 0 else f"{base}-{n}")
    return found


def external(target: str) -> bool:
    return bool(re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", target, re.I))


def main(root: Path) -> int:
    errors: list[str] = []
    pages = {p.stem: p for p in root.glob("*.md")}
    if "Home" not in pages:
        errors.append("Home.md is missing (the wiki's landing page)")
    for name, path in pages.items():
        if not PAGE_NAME.match(name):
            errors.append(f"{path.name}: page names may only use letters, digits and '-' (GitHub shows '-' as a space)")
    for sub in root.iterdir():
        if sub.is_file() and sub.suffix != ".md" and sub.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".svg"}:
            errors.append(f"{sub.name}: only .md pages and images belong in the wiki folder")

    texts = {name: path.read_text(encoding="utf-8") for name, path in pages.items()}
    anchors = {name: anchors_of(text) for name, text in texts.items()}

    for name, path in sorted(pages.items()):
        text = texts[name]
        if text.count("```") % 2:
            errors.append(f"{path.name}: unclosed code fence")
        prose = re.sub(r"```.*?```", "", text, flags=re.S)           # links inside code are examples
        prose = re.sub(r"`[^`\n]*`", "", prose)
        targets = [(m.group(1), "link") for m in LINK.finditer(prose)]
        targets += [(m.group(1), "image") for m in IMAGE.finditer(prose)]
        for m in WIKILINK.finditer(prose):
            page = (m.group(2) or m.group(1)).strip().replace(" ", "-")
            if page not in pages:
                errors.append(f"{path.name}: [[{m.group(0)[2:-2]}]] points at a page that does not exist")
        for target, kind in targets:
            ref, _, fragment = target.partition("#")
            if kind == "link" and target.startswith("#"):
                if fragment and fragment.lower() not in anchors[name]:
                    errors.append(f"{path.name}: link '{target}' points at a heading that does not exist")
                continue
            if external(target):
                continue
            if not ref:
                continue
            if (kind == "link" and ref not in pages) and not (root / ref).is_file():
                errors.append(f"{path.name}: link '{target}' points at a page that does not exist")
            elif kind == "link" and fragment and ref in pages and fragment.lower() not in anchors[ref]:
                errors.append(f"{path.name}: link '{target}' points at a heading that does not exist in {ref}")
            if kind == "image" and not (root / ref).is_file():
                errors.append(f"{path.name}: image '{target}' does not exist")

    if "_Sidebar" in pages:
        linked = {m.group(1).split("#", 1)[0] for m in LINK.finditer(pages["_Sidebar"].read_text(encoding="utf-8"))}
        for name in sorted(set(pages) - SPECIAL - linked):
            errors.append(f"_Sidebar.md: page '{name}' is not linked from the sidebar")
    else:
        errors.append("_Sidebar.md is missing")

    for line in errors:
        print(f"::error::{line}" if len(sys.argv) > 2 else f"error: {line}")
    if errors:
        print(f"\n{len(errors)} problem(s) in {root}", file=sys.stderr)
        return 1
    print(f"wiki OK: {len(pages)} pages in {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "wiki")))
