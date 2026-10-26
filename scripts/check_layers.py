#!/usr/bin/env python3
"""check_layers.py: the agents of the studio live in scripts/agents, not in the interface (AGENTS.md, "Les agents").

A file of app/ fails if it calls `claude` itself (its program or its flags in an argument list) or holds the text of an agent's prompt. The app
runs the commands of scripts/agents and nothing else. EXCEPTIONS names the files still allowed to, with the reason: it is empty, every agent
has its command.

Usage: python3 scripts/check_layers.py   (exit 1 on any finding)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCEPTIONS = {}  # {"app/file.py": "why"}

CALL = re.compile(r"""\[\s*["']claude["']|["']-p["']|--no-session-persistence|--restricted|--permission-mode|--permission-prompts|["']--model["']|\bclaude\s+-p\b""")
PROMPT = re.compile(r"Return ONLY|no prose, no code fence|You are (the judge|one of|not a critic)|You (prepare|imagine|propose|name) (the|names|a brand)|Write ONE file|^\s*f?[\"']=== ")


def main(root=ROOT):
    problems, files = [], sorted((root / "app").rglob("*.py"))
    for f in files:
        rel = f.relative_to(root).as_posix()
        if rel in EXCEPTIONS:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if CALL.search(line):
                problems.append(f"{rel}:{i}: a direct call to claude (it is a command of scripts/agents)")
            elif PROMPT.search(line):
                problems.append(f"{rel}:{i}: the text of an agent's prompt (it lives in scripts/agents)")
    for p in problems:
        print(p)
    print(f"check_layers: {len(files)} files, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
