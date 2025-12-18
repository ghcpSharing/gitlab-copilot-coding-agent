#!/usr/bin/env bash
#
# Issue Note Mention Workflow
# 处理 Issue 评论中 @copilot 的 mention
#
# 流程：
# 1. 发布确认消息
# 2. 克隆仓库并创建 copilot/ 前缀分支
# 3. 加载项目理解上下文
# 4. 执行实现任务
# 5. 提交并推送更改
# 6. 创建 MR
# 7. 更新 Issue 评论
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
require_env TARGET_ISSUE_IID
require_env ISSUE_NOTE_INSTRUCTION
require_env TARGET_REPO_URL
require_env TARGET_BRANCH
require_env NEW_BRANCH_NAME

echo "=========================================="
echo "  🤖 Issue Note Mention Workflow"
echo "=========================================="
echo "[INFO] Issue #${TARGET_ISSUE_IID}: ${ISSUE_TITLE:-}"
echo "[INFO] Instruction: ${ISSUE_NOTE_INSTRUCTION}"
echo "[INFO] Branch: ${NEW_BRANCH_NAME}"
echo ""

API="${UPSTREAM_GITLAB_BASE_URL}/api/v4/projects/${TARGET_PROJECT_ID}"

# ============================================================================
# Step 1: 发布确认消息
# ============================================================================
echo "=== Phase 1: Post Acknowledgment ==="

ACK_BODY="👋 Hi @${NOTE_AUTHOR_USERNAME:-there}!

I received your request and I'm starting to work on it now.

**Task**: ${ISSUE_NOTE_INSTRUCTION}

**Branch**: \`${NEW_BRANCH_NAME}\`

I'll create a Merge Request once I'm done. Stay tuned! 🚀

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL:-})"

curl --fail --silent --show-error \
  --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data-urlencode "body=${ACK_BODY}" \
  "${API}/issues/${TARGET_ISSUE_IID}/notes" > /dev/null || {
  echo "[WARN] Failed to post acknowledgment"
}

echo "[INFO] Acknowledgment posted"

# ============================================================================
# Step 2: 克隆仓库
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
echo "[INFO] Repository cloned successfully"

# ============================================================================
# Step 3: 创建分支
# ============================================================================
echo ""
echo "=== Phase 3: Create Branch ==="

# 尝试创建远程分支
echo "[INFO] Creating branch ${NEW_BRANCH_NAME}..."
curl --silent --show-error --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data "branch=${NEW_BRANCH_NAME}" \
  --data "ref=${TARGET_BRANCH}" \
  --request POST "${API}/repository/branches" > /dev/null 2>&1 || {
  echo "[INFO] Branch may already exist"
}

# 切换到新分支
git fetch origin "${NEW_BRANCH_NAME}" >/dev/null 2>&1 || true
git checkout -B "${NEW_BRANCH_NAME}" "origin/${NEW_BRANCH_NAME}" 2>/dev/null || git checkout -b "${NEW_BRANCH_NAME}" "origin/${TARGET_BRANCH}"

echo "[INFO] Now on branch: $(git branch --show-current)"

# ============================================================================
# Step 4: 加载项目理解上下文
# ============================================================================
echo ""
echo "=== Phase 4: Load Project Context ==="

cd "${REPO_ROOT}"

PROJECT_CONTEXT_FILE=""

if [ "${ENABLE_PROJECT_UNDERSTANDING:-true}" = "true" ]; then
  echo "[INFO] Loading project understanding context..."
  
  # 设置上下文管理器需要的变量
  export PROJECT_ID="${TARGET_PROJECT_ID}"
  export BRANCH="${TARGET_BRANCH}"
  export CURRENT_COMMIT=$(cd "${REPO_DIR}" && git rev-parse HEAD)
  export PARENT_COMMIT=$(cd "${REPO_DIR}" && git rev-parse HEAD~1 2>/dev/null || echo "${CURRENT_COMMIT}")
  export AZURE_CONNECTION="${AZURE_STORAGE_CONNECTION_STRING:-}"
  
  if [ -n "${AZURE_CONNECTION}" ]; then
    # 尝试从缓存加载
    echo "[INFO] Attempting to load cached context..."
    if bash scripts/ci_context_manager.sh 2>&1 | tee context_manager.log; then
      if [ -f "${REPO_DIR}/.copilot/project_context.md" ]; then
        PROJECT_CONTEXT_FILE="${REPO_DIR}/.copilot/project_context.md"
        echo "[INFO] ✓ Project context loaded"
      fi
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
# Step 5: 执行实现任务
# ============================================================================
echo ""
echo "=== Phase 5: Execute Implementation ==="

cd "${REPO_DIR}"

# 构建 prompt
PROMPT="## Task Request

You are working in a git repository. A user has requested the following task via an Issue comment:

**Issue**: #${TARGET_ISSUE_IID} - ${ISSUE_TITLE:-}

**Original Issue Description**:
${ISSUE_DESCRIPTION:-No description provided}

**User Request**:
${ISSUE_NOTE_INSTRUCTION}

**Working Branch**: ${NEW_BRANCH_NAME}
**Target Branch**: ${TARGET_BRANCH}

---
"

# 如果有项目上下文，添加到 prompt
if [ -n "${PROJECT_CONTEXT_FILE}" ] && [ -f "${PROJECT_CONTEXT_FILE}" ]; then
  CONTEXT_CONTENT=$(cat "${PROJECT_CONTEXT_FILE}" | head -c 10000)
  PROMPT="${PROMPT}
## Project Context (AI Generated)

${CONTEXT_CONTENT}

---
"
fi

PROMPT="${PROMPT}
## Instructions

1. Analyze the request and understand what needs to be done
2. Make the necessary code changes to fulfill the request
3. Create or modify files as needed
4. Follow the project's existing code style and conventions
5. Test your changes if possible

**Important**:
- You are working in directory: $(pwd)
- Commit your changes when done
- Provide a brief summary of what you did

Begin implementation:
"

echo "[INFO] Prompt size: ${#PROMPT} chars"

# 保存 prompt
echo "${PROMPT}" > implementation_prompt.txt

# 调用 Copilot
echo "[INFO] Invoking Copilot for implementation..."
if timeout 3600 copilot -p "$PROMPT" --allow-all-tools --allow-all-paths > copilot_output.log 2>&1; then
  echo "[INFO] Copilot execution completed"
else
  EXIT_CODE=$?
  echo "[WARN] Copilot exited with code ${EXIT_CODE}"
  cat copilot_output.log
fi

# ============================================================================
# Step 6: 提交和推送
# ============================================================================
echo ""
echo "=== Phase 6: Commit and Push ==="

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
UNTRACKED_FILES=$(get_safe_untracked_files "." 2>/dev/null || git ls-files --others --exclude-standard | grep -v -E '(\.log$|\.txt$|__pycache__|\.pyc$|\.copilot)' || true)

if [ -n "$UNTRACKED_FILES" ]; then
  HAS_CHANGES=true
fi

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
  
  # 提交消息
  COMMIT_MSG="feat: ${ISSUE_NOTE_INSTRUCTION}

Requested by @${NOTE_AUTHOR_USERNAME:-user} in Issue #${TARGET_ISSUE_IID}

Co-authored-by: ${NOTE_AUTHOR_USERNAME:-user} <${NOTE_AUTHOR_USERNAME:-user}@users.noreply.gitlab.com>"
  
  echo "[INFO] Committing changes..."
  if git commit -m "$COMMIT_MSG"; then
    echo "[INFO] Pushing to ${NEW_BRANCH_NAME}..."
    
    PUSH_SUCCESS=false
    for i in 1 2 3; do
      if git push --set-upstream origin "${NEW_BRANCH_NAME}" 2>&1; then
        PUSH_SUCCESS=true
        break
      fi
      echo "[WARN] Push attempt $i failed, retrying..."
      sleep 5
    done
    
    if [ "$PUSH_SUCCESS" = false ]; then
      echo "[ERROR] Failed to push after 3 attempts" >&2
      exit 1
    fi
    
    CHANGES_PUSHED=true
  else
    echo "[WARN] Nothing to commit"
    CHANGES_PUSHED=false
  fi
else
  echo "[WARN] No changes were generated"
  CHANGES_PUSHED=false
fi

# ============================================================================
# Step 7: 创建 MR
# ============================================================================
echo ""
echo "=== Phase 7: Create Merge Request ==="

if [ "${CHANGES_PUSHED:-false}" = "true" ]; then
  cd "${REPO_ROOT}"
  
  MR_TITLE="feat: ${ISSUE_NOTE_INSTRUCTION}"
  if [ ${#MR_TITLE} -gt 100 ]; then
    MR_TITLE="${MR_TITLE:0:97}..."
  fi
  
  MR_DESC="## 🤖 Copilot Implementation

This MR was created by Copilot in response to a mention in Issue #${TARGET_ISSUE_IID}.

**Original Request**: ${ISSUE_NOTE_INSTRUCTION}

**Requested by**: @${NOTE_AUTHOR_USERNAME:-user}

**Related Issue**: ${ISSUE_URL:-#${TARGET_ISSUE_IID}}

---
Closes #${TARGET_ISSUE_IID}

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL:-})"
  
  cat <<EOF > mr_description.txt
${MR_DESC}
EOF
  
  echo "[INFO] Creating merge request..."
  HTTP_CODE=$(curl --silent --show-error --write-out "%{http_code}" --output mr.json \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --data-urlencode "source_branch=${NEW_BRANCH_NAME}" \
    --data-urlencode "target_branch=${TARGET_BRANCH}" \
    --data-urlencode "title=${MR_TITLE}" \
    --data-urlencode description@mr_description.txt \
    --data "remove_source_branch=true" \
    "${API}/merge_requests")
  
  if [ "$HTTP_CODE" = "409" ]; then
    echo "[INFO] MR already exists"
    curl --silent --show-error \
      --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      "${API}/merge_requests?source_branch=${NEW_BRANCH_NAME}&state=opened" > existing_mr.json
    
    NEW_MR_URL=$(python3 -c "import json; d=json.load(open('existing_mr.json')); print(d[0]['web_url'] if d else '')")
  elif [ "$HTTP_CODE" != "201" ]; then
    echo "[ERROR] Failed to create MR (HTTP ${HTTP_CODE})" >&2
    cat mr.json >&2
    NEW_MR_URL=""
  else
    NEW_MR_URL=$(python3 -c "import json; print(json.load(open('mr.json')).get('web_url', ''))")
    echo "[INFO] MR created: ${NEW_MR_URL}"
  fi
else
  echo "[WARN] No changes to create MR for"
  NEW_MR_URL=""
fi

# ============================================================================
# Step 8: Upload Updated Project Context
# ============================================================================
echo ""
echo "=== Phase 8: Upload Updated Context ==="

cd "${REPO_ROOT}"

if [ "${CHANGES_PUSHED:-false}" = "true" ] && [ -n "${AZURE_STORAGE_CONNECTION_STRING:-}" ]; then
  echo "[INFO] Uploading updated project context to cache..."
  
  NEW_COMMIT=$(cd "${REPO_DIR}" && git rev-parse HEAD)
  PREV_COMMIT=$(cd "${REPO_DIR}" && git rev-parse HEAD~1 2>/dev/null || echo "${NEW_COMMIT}")
  
  python3 scripts/blob_cache.py upload \
    --connection-string "${AZURE_STORAGE_CONNECTION_STRING}" \
    --project-id "${TARGET_PROJECT_ID}" \
    --branch "${NEW_BRANCH_NAME}" \
    --commit "${NEW_COMMIT}" \
    --parent-commit "${PREV_COMMIT}" \
    --local-dir "${REPO_DIR}/.copilot" 2>&1 || {
    echo "[WARN] Failed to upload context cache"
  }
  
  echo "[INFO] ✓ Context cache updated for commit ${NEW_COMMIT:0:8}"
else
  echo "[INFO] Skipping context upload (no changes pushed or no Azure connection)"
fi

# ============================================================================
# Step 9: Post Completion to Issue
# ============================================================================
echo ""
echo "=== Phase 9: Post Completion ==="

if [ -n "${NEW_MR_URL}" ]; then
  COMPLETION_BODY="✅ **Task Completed!**

I've finished working on your request:

> ${ISSUE_NOTE_INSTRUCTION}

**Merge Request**: ${NEW_MR_URL}

Please review the changes and let me know if you need any adjustments. 🎉

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL:-})"
else
  COMPLETION_BODY="⚠️ **Task Attempted**

I tried to work on your request:

> ${ISSUE_NOTE_INSTRUCTION}

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
  "${API}/issues/${TARGET_ISSUE_IID}/notes" > /dev/null || {
  echo "[WARN] Failed to post completion comment"
}

echo ""
echo "=========================================="
echo "  ✅ WORKFLOW COMPLETED"
echo "=========================================="
if [ -n "${NEW_MR_URL}" ]; then
  echo "  MR URL: ${NEW_MR_URL}"
fi
echo "  Issue: ${ISSUE_URL:-#${TARGET_ISSUE_IID}}"
echo "=========================================="
