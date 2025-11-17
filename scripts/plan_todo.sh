#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

cd "${REPO_ROOT}"

require_env ORIGINAL_NEEDS
copilot_login

python3 <<'PY'
import os
from pathlib import Path

needs = os.getenv("ORIGINAL_NEEDS", "").strip()
if not needs:
    raise SystemExit("ORIGINAL_NEEDS is required")

prompt = f"""
You are GitHub Copilot CLI acting as a technical program manager.
Take the ORIGINAL_NEEDS and output strict JSON with keys branch and todo_markdown.
branch must be a short kebab-case feature branch.
todo_markdown must be a Markdown todo list capturing concrete implementation steps.
Return ONLY the JSON string without commentary.

ORIGINAL_NEEDS:
{needs}
"""

Path("prompt.txt").write_text(prompt, encoding="utf-8")
PY

copilot -p "$(cat prompt.txt)" > plan_raw.txt

python3 <<'PY'
import json
import re
from pathlib import Path

raw = Path("plan_raw.txt").read_text(encoding="utf-8").strip()
if raw.startswith("```"):
    raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
    raw = raw.rsplit("```", 1)[0]

data = json.loads(raw)
branch = data.get("branch", "").strip()
todo = data.get("todo_markdown", "").strip()

if not branch:
    raise SystemExit("Copilot response missing branch")
if not todo:
    raise SystemExit("Copilot response missing todo_markdown")

if not todo.endswith("\n"):
    todo += "\n"
Path("todo.md").write_text(todo, encoding="utf-8")

with open("plan.env", "w", encoding="utf-8") as env_file:
    env_file.write(f"NEW_BRANCH_NAME={branch}\n")
    env_file.write("TODO_FILE=todo.md\n")
PY
PY
