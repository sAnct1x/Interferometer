"""One-off: shorten verbose module docstrings to a single summary line."""

from __future__ import annotations

from pathlib import Path

SKIP = {".venv", "__pycache__"}


def shorten(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if not text.startswith('"""'):
        return False
    end = text.find('"""', 3)
    if end < 0:
        return False
    body = text[3:end]
    summary = ""
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Key ") or line.startswith("``"):
            break
        summary = line
        break
    if not summary:
        return False
    if len(summary) > 100:
        summary = summary[:97] + "..."
    new = f'"""{summary}"""'
    if new == f'"""{body}"""':
        return False
    path.write_text(new + text[end + 3:], encoding="utf-8")
    return True


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    changed = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "shorten_docstrings.py":
            continue
        if any(part in SKIP for part in path.parts):
            continue
        if shorten(path):
            changed.append(path.relative_to(root))
    print(f"shortened {len(changed)} files")
    for rel in changed:
        print(rel)


if __name__ == "__main__":
    main()
