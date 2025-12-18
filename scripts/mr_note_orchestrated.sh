#!/usr/bin/env bash
#
# MR Note Orchestrated Workflow
# 处理 MR 评论中 @copilot 的 mention（多阶段执行）
#
# 流程：
# 1. 发布确认消息
# 2. 克隆仓库并切换到 source branch
# 3. 加载/更新项目理解上下文
# 4. 生成任务计划（分析复杂度）
# 5. 多阶段执行任务
# 6. 提交并推送更改
# 7. 更新 MR 评论
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"
# shellcheck source=scripts/load_prompt.sh
source "${SCRIPT_DIR}/load_prompt.sh"

cd "${REPO_ROOT}"

# ============================================================================
# 环境变量检查
# ============================================================================
require_env GITLAB_TOKEN
require_env TARGET_PROJECT_ID
require_env TARGET_MR_IID
require_env MR_NOTE_INSTRUCTION
require_env TARGET_REPO_URL
require_env SOURCE_BRANCH
require_env TARGET_BRANCH

echo "=========================================="
echo "  🤖 MR Note Orchestrated Workflow"
echo "=========================================="
echo "[INFO] MR !${TARGET_MR_IID}: ${MR_TITLE:-}"
echo "[INFO] Instruction: ${MR_NOTE_INSTRUCTION}"
echo "[INFO] Source Branch: ${SOURCE_BRANCH}"
echo "[INFO] Target Branch: ${TARGET_BRANCH}"
echo ""

API="${UPSTREAM_GITLAB_BASE_URL}/api/v4/projects/${TARGET_PROJECT_ID}"

# ============================================================================
# Phase 1: 发布确认消息
# ============================================================================
echo "=== Phase 1: Post Acknowledgment ==="

ACK_BODY="👋 Hi @${NOTE_AUTHOR_USERNAME:-there}!

I received your request and I'm starting to work on it now.

**Task**: ${MR_NOTE_INSTRUCTION}

**Branch**: \`${SOURCE_BRANCH}\`

I'll update this MR once I'm done. Using multi-stage execution for better results. 🚀

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL:-})"

curl --fail --silent --show-error \
  --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data-urlencode "body=${ACK_BODY}" \
  "${API}/merge_requests/${TARGET_MR_IID}/notes" > /dev/null || {
  echo "[WARN] Failed to post acknowledgment"
}

echo "[INFO] Acknowledgment posted"

# ============================================================================
# Phase 2: 克隆仓库
# ============================================================================
echo ""
echo "=== Phase 2: Clone Repository ==="

python3 <<'PY' > authed_repo_url.txt
import os
from urllib.parse import quote, urlparse, urlunparse

token = os.environ["GITLAB_TOKEN"]
repo = os.environ["TARGET_REPO_URL"]
parsed = urlparse(repo)
netloc = f"oauth2:{quote(token, safe='')}@{parsed.netloc}"
authed = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
print(authed)
PY

AUTHED_URL="$(cat authed_repo_url.txt)"
REPO_DIR="${REPO_DIR:-repo-${TARGET_PROJECT_ID}}"

echo "[INFO] Cloning to ${REPO_DIR}..."

rm -rf "${REPO_DIR}"
GIT_TERMINAL_PROMPT=0 git clone "${AUTHED_URL}" "${REPO_DIR}" >/dev/null 2>&1 || {
  echo "[ERROR] Failed to clone repository" >&2
  exit 1
}

cd "${REPO_DIR}"

echo "[INFO] Checking out source branch ${SOURCE_BRANCH}..."
# Fetch all branches first
git fetch origin --prune >/dev/null 2>&1 || true

# Use robust checkout function from common.sh
if ! robust_checkout "${SOURCE_BRANCH}" "."; then
  echo "[ERROR] Failed to checkout source branch ${SOURCE_BRANCH}" >&2
  exit 1
fi

echo "[INFO] Repository cloned, on branch: $(git branch --show-current 2>/dev/null || echo 'detached HEAD')"

# ============================================================================
# Phase 3: 加载/更新项目理解上下文
# ============================================================================
echo ""
echo "=== Phase 3: Load/Update Project Context ==="

cd "${REPO_ROOT}"

PROJECT_CONTEXT_FILE=""

if [ "${ENABLE_PROJECT_UNDERSTANDING:-true}" = "true" ]; then
  echo "[INFO] Loading project understanding context..."
  
  # 设置上下文管理器需要的变量
  export PROJECT_ID="${TARGET_PROJECT_ID}"
  export BRANCH="${SOURCE_BRANCH}"
  export CI_COMMIT_SHA=$(cd "${REPO_DIR}" && git rev-parse HEAD)
  export CI_COMMIT_BEFORE_SHA=$(cd "${REPO_DIR}" && git rev-parse HEAD~1 2>/dev/null || echo "${CI_COMMIT_SHA}")
  export CURRENT_COMMIT="${CI_COMMIT_SHA}"
  export PARENT_COMMIT="${CI_COMMIT_BEFORE_SHA}"
  export AZURE_CONNECTION="${AZURE_STORAGE_CONNECTION_STRING:-}"
  
  if [ -n "${AZURE_CONNECTION}" ]; then
    echo "[INFO] Running CI Context Manager..."
    if bash scripts/ci_context_manager.sh 2>&1 | tee context_manager.log; then
      if [ -f "${REPO_DIR}/.copilot/project_context.md" ]; then
        PROJECT_CONTEXT_FILE="${REPO_DIR}/.copilot/project_context.md"
        echo "[INFO] ✓ Project context loaded/updated"
      fi
    else
      echo "[WARN] Context manager had issues, continuing without cached context"
    fi
  fi
  
  # 如果没有缓存，运行完整分析
  if [ -z "${PROJECT_CONTEXT_FILE}" ]; then
    echo "[INFO] Running project analysis..."
    export PYTHONPATH="${PWD}/index_repo/src:${PYTHONPATH:-}"
    
    if python3 -m project_understanding.cli \
        "${REPO_DIR}" \
        --output-dir ".copilot" \
        --output-file project_context.md \
        --no-cache \
        --timeout 1800 \
        -v 2>&1 | tee project_analysis.log; then
      
      if [ -f "${REPO_DIR}/.copilot/project_context.md" ]; then
        PROJECT_CONTEXT_FILE="${REPO_DIR}/.copilot/project_context.md"
        echo "[INFO] ✓ Project analysis completed"
      fi
    else
      echo "[WARN] Project analysis failed, continuing without context"
    fi
  fi
else
  echo "[INFO] Project understanding disabled"
fi

# ============================================================================
# Phase 4: 生成任务计划
# ============================================================================
echo ""
echo "=== Phase 4: Generate Task Plan ==="

cd "${REPO_ROOT}"

# 获取 MR 的 diff 信息作为额外上下文
echo "[INFO] Fetching MR diff context..."
MR_DIFF_CONTEXT=""
if MR_INFO=$(curl --silent --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "${API}/merge_requests/${TARGET_MR_IID}/changes" 2>/dev/null); then
  MR_DIFF_CONTEXT=$(echo "${MR_INFO}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    changes = data.get('changes', [])
    files = [c.get('new_path', '') for c in changes[:20]]
    print('Changed files in MR: ' + ', '.join(files))
except:
    pass
" 2>/dev/null || true)
fi

# 获取 MR 的讨论/评论历史（包括 review comments）
echo "[INFO] Fetching MR discussions (review comments)..."
MR_DISCUSSIONS=""
if DISCUSSIONS_JSON=$(curl --silent --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "${API}/merge_requests/${TARGET_MR_IID}/discussions" 2>/dev/null); then
  MR_DISCUSSIONS=$(echo "${DISCUSSIONS_JSON}" | python3 -c "
import json, sys
try:
    discussions = json.load(sys.stdin)
    output_lines = []
    for disc in discussions:
        notes = disc.get('notes', [])
        for note in notes:
            author = note.get('author', {}).get('username', 'unknown')
            body = note.get('body', '').strip()
            note_type = note.get('type', '')
            position = note.get('position', {})
            
            # Skip system notes and empty notes
            if note.get('system', False) or not body:
                continue
            
            # Format the note
            if position and position.get('new_path'):
                # This is a diff/inline comment (review comment)
                file_path = position.get('new_path', '')
                line = position.get('new_line') or position.get('old_line', '')
                output_lines.append(f'### Review Comment by @{author}')
                output_lines.append(f'**File**: \`{file_path}\` (line {line})')
                output_lines.append(f'{body}')
                output_lines.append('')
            else:
                # Regular comment
                output_lines.append(f'### Comment by @{author}')
                output_lines.append(f'{body}')
                output_lines.append('')
    
    if output_lines:
        print('\\n'.join(output_lines[-100:]))  # Last 100 lines to avoid too much context
except Exception as e:
    print(f'Error parsing discussions: {e}', file=sys.stderr)
" 2>/dev/null || true)
fi

if [ -n "${MR_DISCUSSIONS}" ]; then
  echo "[INFO] ✓ Found MR discussions/review comments"
  echo "[DEBUG] Discussions preview (first 500 chars):"
  echo "${MR_DISCUSSIONS}" | head -c 500
  echo "..."
else
  echo "[INFO] No discussions found or failed to fetch"
fi

# 调用 planner 生成计划
echo "[INFO] Generating task plan..."

# 构建 Issue description，包含 MR 上下文和讨论历史
PLAN_DESCRIPTION="## MR Context

**MR Title**: ${MR_TITLE:-MR !${TARGET_MR_IID}}
**Source Branch**: ${SOURCE_BRANCH}
**Target Branch**: ${TARGET_BRANCH}
${MR_DIFF_CONTEXT}

## Previous Review Comments and Discussions

${MR_DISCUSSIONS:-No previous discussions found.}

## User Request

${MR_NOTE_INSTRUCTION}"

python3 scripts/issue_planner.py \
  --issue-id "mr-${TARGET_MR_IID}" \
  --issue-title "${MR_NOTE_INSTRUCTION:0:100}" \
  --issue-description "${PLAN_DESCRIPTION}" \
  --output mr_task_plan.json 2>&1 | tee planner.log || {
  echo "[WARN] Planner failed, using simple single-task plan"
  # 创建简单的单任务计划
  cat > mr_task_plan.json <<EOF
{
  "issue_id": "mr-${TARGET_MR_IID}",
  "issue_title": "${MR_NOTE_INSTRUCTION:0:100}",
  "complexity": {"scope": "small"},
  "subtasks": [
    {
      "id": "task_1",
      "task_type": "implementation",
      "title": "Execute Request",
      "description": "${MR_NOTE_INSTRUCTION}",
      "estimated_time_seconds": 600,
      "priority": 1,
      "dependencies": []
    }
  ],
  "max_concurrent_tasks": 1
}
EOF
}

echo "[INFO] Task plan generated:"
cat mr_task_plan.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  Complexity: {d.get(\"complexity\",{}).get(\"scope\",\"unknown\")}'); print(f'  Subtasks: {len(d.get(\"subtasks\",[]))}')"

# ============================================================================
# Phase 5: 执行任务计划
# ============================================================================
echo ""
echo "=== Phase 5: Execute Task Plan ==="

cd "${REPO_ROOT}"

python3 scripts/issue_executor.py \
  --plan mr_task_plan.json \
  --workspace "${REPO_DIR}" \
  --issue-title "${MR_NOTE_INSTRUCTION:0:100}" \
  --issue-description "${PLAN_DESCRIPTION}" \
  --output mr_execution_results.json 2>&1 | tee executor.log || {
  echo "[WARN] Executor encountered issues"
}

echo "[INFO] Execution results:"
if [ -f mr_execution_results.json ]; then
  cat mr_execution_results.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  Status: {d.get(\"status\")}'); print(f'  Success: {d.get(\"success_count\",0)}'); print(f'  Failed: {d.get(\"failed_count\",0)}')"
fi

# ============================================================================
# Phase 6: 提交和推送
# ============================================================================
echo ""
echo "=== Phase 6: Commit and Push ==="

cd "${REPO_DIR}"

GIT_USER_NAME="${COPILOT_AGENT_USERNAME:-Copilot}"
GIT_USER_EMAIL="${COPILOT_AGENT_COMMIT_EMAIL:-copilot@github.com}"

git config user.name "${GIT_USER_NAME}"
git config user.email "${GIT_USER_EMAIL}"

# 检查是否有更改
HAS_CHANGES=false

if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
  HAS_CHANGES=true
fi

# Use safe untracked files function to exclude large/unwanted files
UNTRACKED_FILES=$(get_safe_untracked_files "." 2>/dev/null || git ls-files --others --exclude-standard | grep -v -E '(\.log$|\.txt$|\.json$|__pycache__|\.pyc$|\.copilot)' || true)

if [ -n "$UNTRACKED_FILES" ]; then
  HAS_CHANGES=true
fi

CHANGES_PUSHED=false

if [ "$HAS_CHANGES" = true ]; then
  echo "[INFO] Changes detected, staging files..."
  
  git add -u || true
  
  if [ -n "$UNTRACKED_FILES" ]; then
    echo "$UNTRACKED_FILES" | xargs -r git add || true
  fi
  
  # Run pre-commit cleanup to exclude large/unwanted files
  pre_commit_cleanup "."
  
  echo "[DEBUG] Staged changes:"
  git diff --cached --stat
  
  # 生成 commit message
  CHANGES_STAT=$(git diff --cached --stat 2>/dev/null | tail -5)
  COMMIT_MSG="feat: ${MR_NOTE_INSTRUCTION:0:50}

Requested by @${NOTE_AUTHOR_USERNAME:-user} in MR !${TARGET_MR_IID}

Changes:
${CHANGES_STAT}

Co-authored-by: ${NOTE_AUTHOR_USERNAME:-user} <${NOTE_AUTHOR_USERNAME:-user}@users.noreply.gitlab.com>"
  
  echo "[INFO] Committing changes..."
  if git commit -m "$COMMIT_MSG"; then
    echo "[INFO] Pushing to ${SOURCE_BRANCH}..."
    
    PUSH_SUCCESS=false
    for i in 1 2 3; do
      if git push origin "${SOURCE_BRANCH}" 2>&1; then
        PUSH_SUCCESS=true
        break
      fi
      echo "[WARN] Push attempt $i failed, retrying..."
      sleep 5
    done
    
    if [ "$PUSH_SUCCESS" = true ]; then
      CHANGES_PUSHED=true
      NEW_COMMIT=$(git rev-parse HEAD)
      echo "[INFO] ✓ Changes pushed (commit: ${NEW_COMMIT:0:8})"
    else
      echo "[ERROR] Failed to push after 3 attempts" >&2
    fi
  else
    echo "[WARN] Nothing to commit"
  fi
else
  echo "[WARN] No changes were generated"
fi

# ============================================================================
# Phase 7: 上传更新后的上下文
# ============================================================================
echo ""
echo "=== Phase 7: Upload Updated Context ==="

cd "${REPO_ROOT}"

if [ "${CHANGES_PUSHED}" = "true" ] && [ -n "${AZURE_STORAGE_CONNECTION_STRING:-}" ]; then
  echo "[INFO] Uploading updated project context..."
  
  NEW_COMMIT=$(cd "${REPO_DIR}" && git rev-parse HEAD)
  PREV_COMMIT=$(cd "${REPO_DIR}" && git rev-parse HEAD~1 2>/dev/null || echo "${NEW_COMMIT}")
  
  python3 scripts/blob_cache.py upload \
    --connection-string "${AZURE_STORAGE_CONNECTION_STRING}" \
    --project-id "${TARGET_PROJECT_ID}" \
    --branch "${SOURCE_BRANCH}" \
    --commit "${NEW_COMMIT}" \
    --parent-commit "${PREV_COMMIT}" \
    --local-dir "${REPO_DIR}/.copilot" 2>&1 || {
    echo "[WARN] Failed to upload context cache"
  }
  
  echo "[INFO] ✓ Context cache updated"
else
  echo "[INFO] Skipping context upload (no changes or no Azure connection)"
fi

# ============================================================================
# Phase 8: 更新 MR 评论
# ============================================================================
echo ""
echo "=== Phase 8: Post Completion Comment ==="

cd "${REPO_ROOT}"

# 读取执行结果
EXEC_STATUS="unknown"
EXEC_SUCCESS=0
EXEC_FAILED=0
if [ -f mr_execution_results.json ]; then
  EXEC_STATUS=$(python3 -c "import json; print(json.load(open('mr_execution_results.json')).get('status','unknown'))")
  EXEC_SUCCESS=$(python3 -c "import json; print(json.load(open('mr_execution_results.json')).get('success_count',0))")
  EXEC_FAILED=$(python3 -c "import json; print(json.load(open('mr_execution_results.json')).get('failed_count',0))")
fi

if [ "${CHANGES_PUSHED}" = "true" ]; then
  NEW_COMMIT=$(cd "${REPO_DIR}" && git rev-parse HEAD)
  
  COMPLETION_BODY="✅ **Task Completed!**

I've finished working on your request:

> ${MR_NOTE_INSTRUCTION}

**Execution Summary**:
- Status: ${EXEC_STATUS}
- Successful tasks: ${EXEC_SUCCESS}
- Failed tasks: ${EXEC_FAILED}

**New Commit**: \`${NEW_COMMIT:0:8}\`

Please review the changes. Let me know if you need any adjustments! 🎉

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL:-})"
else
  COMPLETION_BODY="⚠️ **Task Attempted**

I tried to work on your request:

> ${MR_NOTE_INSTRUCTION}

**Execution Summary**:
- Status: ${EXEC_STATUS}
- Successful tasks: ${EXEC_SUCCESS}
- Failed tasks: ${EXEC_FAILED}

However, I wasn't able to generate any code changes. This might be because:
- The request was unclear
- No code changes were needed
- There was an error during execution

Please check the [pipeline logs](${CI_PIPELINE_URL:-}) for more details.

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL:-})"
fi

curl --silent --show-error --fail \
  --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data-urlencode "body=${COMPLETION_BODY}" \
  "${API}/merge_requests/${TARGET_MR_IID}/notes" > /dev/null || {
  echo "[WARN] Failed to post completion comment"
}

echo ""
echo "=========================================="
echo "  ✅ WORKFLOW COMPLETED"
echo "=========================================="
echo "  MR: !${TARGET_MR_IID}"
echo "  Status: ${EXEC_STATUS}"
echo "  Tasks: ${EXEC_SUCCESS} success, ${EXEC_FAILED} failed"
if [ "${CHANGES_PUSHED}" = "true" ]; then
  echo "  Commit: ${NEW_COMMIT:0:8}"
fi
echo "=========================================="
