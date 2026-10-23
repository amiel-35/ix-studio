#!/usr/bin/env python3
"""check_public.py: nothing private leaves in the public repository (R14, criterion C10).

Two checks over the files git would publish:
  1. no brand dossier other than the fictional example (a brand.json, evidence.json or sources/ folder outside
     examples/);
  2. none of the private names listed in local.md, under a "## Private names" heading (one per line), appears in
     any file. local.md is ignored by git: the list of what must not leak does not leak either.

Usage: python3 scripts/check_public.py   (exit 1 on any finding)
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = "examples/"


def published_files():
    r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        return [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and ".git/" not in p.as_posix()]
    return [l for l in r.stdout.splitlines() if l]


def private_names():
    local = ROOT / "local.md"
    if not local.exists():
        return []
    names, on = [], False
    for line in local.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            on = line.strip().lower() == "## private names"
            continue
        if on:
            n = line.strip().lstrip("-* ").strip()
            if n and not n.startswith(("<!--", "#")):
                names.append(n)
    return names


def main():
    problems = []
    files = published_files()
    for f in files:
        name = Path(f).name
        if (name in ("brand.json", "evidence.json", "decisions.json") or "/sources/" in f) and not f.startswith(EXAMPLE):
            problems.append(f"{f}: a brand dossier outside examples/")
    names = private_names()
    if names:
        rx = re.compile("|".join(re.escape(n) for n in names), re.IGNORECASE)
        for f in files:
            p = ROOT / f
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                m = rx.search(line)
                if m:
                    problems.append(f"{f}:{i}: private name {m.group(0)!r}")
    for p in problems:
        print(p)
    print(f"check_public: {len(files)} files, {len(names)} private names, {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
