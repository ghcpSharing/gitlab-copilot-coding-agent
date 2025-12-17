#!/usr/bin/env bash
#
# 编排式 Issue 处理脚本
# 支持项目理解上下文和多步骤任务执行
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
require_env ORIGINAL_NEEDS
require_env ISSUE_TITLE
require_env TARGET_PROJECT_PATH
require_env TARGET_REPO_URL
require_env TARGET_BRANCH

echo "=========================================="
echo "  🤖 Orchestrated Issue Workflow"
echo "=========================================="
echo "[INFO] Issue #${TARGET_ISSUE_IID}: ${ISSUE_TITLE}"
echo "[INFO] Project: ${TARGET_PROJECT_PATH}"
echo ""

API="${UPSTREAM_GITLAB_BASE_URL}/api/v4/projects/${TARGET_PROJECT_ID}"

# ============================================================================
# Step 1: 发布确认消息
# ============================================================================
echo "=== Phase 1: Post Acknowledgment ==="

NOTE_BODY=$(load_prompt "issue_ack")

if [ -n "${CI_PIPELINE_URL:-}" ]; then
  NOTE_BODY="${NOTE_BODY}

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL})"
fi

curl --fail --silent --show-error \
  --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data-urlencode "body=${NOTE_BODY}" \
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
# Step 3: 加载/生成项目理解上下文
# ============================================================================
echo ""
echo "=== Phase 3: Project Understanding Context ==="

# 设置 CI Context Manager 需要的环境变量
export PROJECT_ID="${TARGET_PROJECT_ID}"
export BRANCH="${TARGET_BRANCH}"
export CURRENT_COMMIT=$(git rev-parse HEAD)
export PARENT_COMMIT=$(git rev-parse HEAD~1 2>/dev/null || echo "${CURRENT_COMMIT}")
export AZURE_CONNECTION="${AZURE_STORAGE_CONNECTION_STRING:-}"

PROJECT_CONTEXT_AVAILABLE=false

if [ "${ENABLE_PROJECT_UNDERSTANDING:-true}" = "true" ]; then
  echo "[INFO] Project understanding enabled, loading context..."
  
  # 尝试从 Azure Blob 缓存加载
  if [ -n "${AZURE_CONNECTION}" ]; then
    echo "[INFO] Attempting to load cached project context..."
    cd "${REPO_ROOT}"
    
    # 使用 ci_context_manager 加载上下文
    if bash scripts/ci_context_manager.sh 2>&1 | tee context_manager.log; then
      if [ -d "${REPO_DIR}/.copilot" ] && [ -f "${REPO_DIR}/.copilot/project_context.md" ]; then
        echo "[INFO] ✓ Project context loaded from cache"
        PROJECT_CONTEXT_AVAILABLE=true
      fi
    else
      echo "[WARN] Context manager failed, will run full analysis if needed"
    fi
    
    cd "${REPO_DIR}"
  fi
  
  # 如果没有缓存，运行完整分析
  if [ "${PROJECT_CONTEXT_AVAILABLE}" = "false" ]; then
    echo "[INFO] No cached context, running project analysis..."
    
    cd "${REPO_ROOT}"
    export PYTHONPATH="${PWD}/index_repo/src:${PYTHONPATH:-}"
    
    if python3 -m project_understanding.cli \
        "${REPO_DIR}" \
        --output-dir ".copilot" \
        --output-file project_context.md \
        --no-cache \
        --timeout 1800 \
        -v 2>&1 | tee project_analysis.log; then
      
      if [ -f "${REPO_DIR}/.copilot/project_context.md" ]; then
        echo "[INFO] ✓ Project analysis completed"
        PROJECT_CONTEXT_AVAILABLE=true
      fi
    else
      echo "[WARN] Project analysis failed, continuing without context"
    fi
    
    cd "${REPO_DIR}"
  fi
else
  echo "[INFO] Project understanding disabled"
fi

# ============================================================================
# Step 4: 生成执行计划
# ============================================================================
echo ""
echo "=== Phase 4: Generate Execution Plan ==="

cd "${REPO_ROOT}"

# 获取仓库结构
find "${REPO_DIR}" -type f -not -path '*/.git/*' -not -path '*/node_modules/*' | head -100 > repo_structure.txt

# 生成任务计划
echo "[INFO] Generating issue execution plan..."

python3 scripts/issue_planner.py \
  --issue-id "${TARGET_ISSUE_IID}" \
  --issue-title "${ISSUE_TITLE}" \
  --issue-description "${ORIGINAL_NEEDS}" \
  --repo-structure repo_structure.txt \
  ${PROJECT_CONTEXT_AVAILABLE:+--project-context "${REPO_DIR}/.copilot/project_context.md"} \
  --output issue_plan.json

if [ ! -f issue_plan.json ]; then
  echo "[ERROR] Failed to generate issue plan" >&2
  exit 1
fi

echo "[INFO] Plan generated:"
python3 -c "import json; p=json.load(open('issue_plan.json')); print(f'  Subtasks: {p[\"total_subtasks\"]}'); print(f'  Est. time: {p[\"estimated_total_time_seconds\"]}s')"

# ============================================================================
# Step 5: 创建分支和 MR
# ============================================================================
echo ""
echo "=== Phase 5: Create Branch and MR ==="

cd "${REPO_DIR}"

# 生成分支名
NEW_BRANCH_NAME="copilot/issue-${TARGET_ISSUE_IID}"

echo "[INFO] Creating branch ${NEW_BRANCH_NAME}..."

# 尝试创建远程分支
curl --silent --show-error --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data "branch=${NEW_BRANCH_NAME}" \
  --data "ref=${TARGET_BRANCH}" \
  --request POST "${API}/repository/branches" > /dev/null 2>&1 || {
  echo "[INFO] Branch may already exist"
}

# 切换到新分支
git fetch origin "${NEW_BRANCH_NAME}" >/dev/null 2>&1 || true
git checkout -B "${NEW_BRANCH_NAME}" "origin/${NEW_BRANCH_NAME}" 2>/dev/null || git checkout -b "${NEW_BRANCH_NAME}" "${TARGET_BRANCH}"

# 创建 MR
MR_TITLE="${ISSUE_TITLE}"
if [ -n "${TARGET_ISSUE_IID:-}" ]; then
  MR_TITLE="${MR_TITLE} (#${TARGET_ISSUE_IID})"
fi

MR_DESC="## 🤖 Copilot Orchestrated Implementation

This MR was created by Copilot using orchestrated multi-step workflow.

**Original Issue**: ${ISSUE_URL:-#${TARGET_ISSUE_IID}}

### Execution Plan
\`\`\`json
$(cat ../issue_plan.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'subtasks': len(d['subtasks']), 'estimated_time': d['estimated_total_time_seconds']}, indent=2))")
\`\`\`

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL:-})"

cat <<EOF > ../mr_description.txt
${MR_DESC}
EOF

echo "[INFO] Creating merge request..."
HTTP_CODE=$(curl --silent --show-error --write-out "%{http_code}" --output ../mr.json \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data-urlencode "source_branch=${NEW_BRANCH_NAME}" \
  --data-urlencode "target_branch=${TARGET_BRANCH}" \
  --data-urlencode "title=${MR_TITLE}" \
  --data-urlencode description@../mr_description.txt \
  "${API}/merge_requests")

if [ "$HTTP_CODE" = "409" ]; then
  echo "[INFO] MR already exists, finding existing..."
  curl --silent --show-error \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "${API}/merge_requests?source_branch=${NEW_BRANCH_NAME}&state=opened" > ../existing_mr.json
  
  NEW_MR_IID=$(python3 -c "import json; d=json.load(open('../existing_mr.json')); print(d[0]['iid'] if d else '')")
  NEW_MR_URL=$(python3 -c "import json; d=json.load(open('../existing_mr.json')); print(d[0]['web_url'] if d else '')")
elif [ "$HTTP_CODE" != "201" ]; then
  echo "[ERROR] Failed to create MR (HTTP ${HTTP_CODE})" >&2
  cat ../mr.json >&2
  exit 1
else
  NEW_MR_IID=$(python3 -c "import json; print(json.load(open('../mr.json')).get('iid', ''))")
  NEW_MR_URL=$(python3 -c "import json; print(json.load(open('../mr.json')).get('web_url', ''))")
fi

echo "[INFO] MR created: ${NEW_MR_URL}"

# ============================================================================
# Step 6: 执行任务计划
# ============================================================================
echo ""
echo "=== Phase 6: Execute Implementation Plan ==="

cd "${REPO_ROOT}"

echo "[INFO] Executing orchestrated implementation..."

python3 scripts/issue_executor.py \
  --plan issue_plan.json \
  --workspace "${REPO_DIR}" \
  --issue-title "${ISSUE_TITLE}" \
  --issue-description "${ORIGINAL_NEEDS}" \
  --output execution_results.json

echo "[INFO] Execution completed"

# ============================================================================
# Step 7: 提交和推送更改
# ============================================================================
echo ""
echo "=== Phase 7: Commit and Push Changes ==="

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

UNTRACKED_FILES=$(git ls-files --others --exclude-standard | grep -v -E '(\.log$|\.txt$|\.json$|__pycache__|\.pyc$|\.copilot_tasks)' || true)

if [ -n "$UNTRACKED_FILES" ]; then
  HAS_CHANGES=true
fi

if [ "$HAS_CHANGES" = true ]; then
  echo "[INFO] Changes detected, staging files..."
  
  git add -u || true
  
  if [ -n "$UNTRACKED_FILES" ]; then
    echo "$UNTRACKED_FILES" | xargs -r git add || true
  fi
  
  echo "[DEBUG] Staged changes:"
  git diff --cached --stat
  
  # 生成提交消息
  COMMIT_MSG="feat: implement issue #${TARGET_ISSUE_IID} via copilot orchestration

${ISSUE_TITLE}

Implemented using multi-step orchestrated workflow with project understanding context."
  
  echo "[INFO] Committing changes..."
  if git commit -m "$COMMIT_MSG"; then
    echo "[INFO] Pushing to ${NEW_BRANCH_NAME}..."
    
    PUSH_RETRY=0
    PUSH_SUCCESS=false
    
    while [ $PUSH_RETRY -lt 3 ]; do
      if git push --set-upstream origin "${NEW_BRANCH_NAME}" 2>&1; then
        PUSH_SUCCESS=true
        break
      fi
      PUSH_RETRY=$((PUSH_RETRY + 1))
      sleep 5
    done
    
    if [ "$PUSH_SUCCESS" = false ]; then
      echo "[ERROR] Failed to push after 3 attempts" >&2
      exit 1
    fi
  else
    echo "[WARN] Nothing to commit"
  fi
else
  echo "[WARN] No changes were generated"
fi

# ============================================================================
# Step 8: Upload Updated Project Context
# ============================================================================
echo ""
echo "=== Phase 8: Upload Updated Context ==="

cd "${REPO_ROOT}"

if [ "${PUSH_SUCCESS:-false}" = "true" ] && [ -n "${AZURE_STORAGE_CONNECTION_STRING:-}" ]; then
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
# Step 9: Finalize - Update MR and Issue
# ============================================================================
echo ""
echo "=== Phase 9: Finalize ==="

cd "${REPO_ROOT}"

# 更新 MR 描述
FINAL_MR_DESC="## 🤖 Copilot Orchestrated Implementation

This MR was created by Copilot using orchestrated multi-step workflow.

**Original Issue**: ${ISSUE_URL:-#${TARGET_ISSUE_IID}}

### Execution Results
\`\`\`json
$(cat execution_results.json 2>/dev/null || echo '{"status": "unknown"}')
\`\`\`

---
- [🔗 Copilot Coding Session](${CI_PIPELINE_URL:-})"

cat <<EOF > final_description.txt
${FINAL_MR_DESC}
EOF

curl --silent --show-error --fail \
  --request PUT \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data-urlencode description@final_description.txt \
  "${API}/merge_requests/${NEW_MR_IID}" > /dev/null || {
  echo "[WARN] Failed to update MR description"
}

# 发布完成消息到 Issue
COMPLETION_BODY=$(load_prompt "mr_completion" "mr_url=${NEW_MR_URL}")

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
echo "  MR URL: ${NEW_MR_URL}"
echo "  Issue: ${ISSUE_URL:-#${TARGET_ISSUE_IID}}"
echo "=========================================="
