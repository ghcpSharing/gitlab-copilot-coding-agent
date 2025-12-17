#!/usr/bin/env bash
#
# 编排式MR审查脚本
# 支持大规模MR的智能拆分和并行审查
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"
# shellcheck source=scripts/load_prompt.sh
source "${SCRIPT_DIR}/load_prompt.sh"

cd "${REPO_ROOT}"

require_env GITLAB_TOKEN
require_env TARGET_REPO_URL
require_env TARGET_BRANCH
require_env SOURCE_BRANCH
require_env TARGET_MR_IID
require_env MR_TITLE
require_env MR_DESCRIPTION

echo "=========================================="
echo "  🤖 Orchestrated MR Code Review"
echo "========================================="
echo "[INFO] MR #${TARGET_MR_IID}: ${MR_TITLE}"
echo "[INFO] ${SOURCE_BRANCH} → ${TARGET_BRANCH}"
echo ""

# 发布开始审查的评论
echo "[INFO] Posting acknowledgment to MR..."
NOTE_BODY=$(load_prompt "review_ack")

if [ -n "${CI_PIPELINE_URL:-}" ]; then
  NOTE_BODY="${NOTE_BODY}

---
- [🔗 Review Session](${CI_PIPELINE_URL})"
fi

API="${UPSTREAM_GITLAB_BASE_URL}/api/v4/projects/${TARGET_PROJECT_ID}"

curl --fail --silent --show-error \
  --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data-urlencode "body=${NOTE_BODY}" \
  "${API}/merge_requests/${TARGET_MR_IID}/notes" > /dev/null || {
  echo "[WARN] Failed to post acknowledgment"
}

# 克隆仓库
echo "[INFO] Cloning repository..."
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

# 使用环境变量指定的目录名（默认 repo-b）
REPO_DIR="${REPO_DIR:-repo-b}"
echo "[INFO] Using repository directory: ${REPO_DIR}"

# 检查是否已有预克隆的仓库（来自项目理解预分析）
if [ -d "${REPO_DIR}" ] && [ "${SKIP_REPO_CLONE}" = "true" ]; then
  echo "[INFO] Using existing ${REPO_DIR} directory (project understanding enabled)"
else
  rm -rf "${REPO_DIR}"
  GIT_TERMINAL_PROMPT=0 git clone "${AUTHED_URL}" "${REPO_DIR}" >/dev/null 2>&1 || {
    echo "[ERROR] Failed to clone repository" >&2
    exit 1
  }
fi

cd "${REPO_DIR}"

echo "[INFO] Fetching branches..."
git fetch origin "${SOURCE_BRANCH}" "${TARGET_BRANCH}" >/dev/null 2>&1 || {
  echo "[ERROR] Failed to fetch branches" >&2
  exit 1
}

# 检出源分支
git checkout "${SOURCE_BRANCH}" >/dev/null 2>&1 || {
  echo "[ERROR] Failed to checkout ${SOURCE_BRANCH}" >&2
  exit 1
}

# ==========================================
# 加载项目理解上下文
# ==========================================
echo ""
echo "=== Loading Project Context ==="
echo ""

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
        echo "[INFO] ✓ Project context loaded from cache"
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

if [ -n "${PROJECT_CONTEXT_FILE}" ]; then
  echo "[INFO] Project context available at ${PROJECT_CONTEXT_FILE}"
  echo "[INFO] Context size: $(wc -c < "${PROJECT_CONTEXT_FILE}") bytes"
fi

cd "${REPO_DIR}"

echo ""
echo "[INFO] On branch: $(git branch --show-current)"
git fetch origin "${SOURCE_BRANCH}" "${TARGET_BRANCH}" >/dev/null 2>&1 || {
  echo "[ERROR] Failed to fetch branches" >&2
  exit 1
}

# 检出源分支
git checkout "${SOURCE_BRANCH}" >/dev/null 2>&1 || {
  echo "[ERROR] Failed to checkout ${SOURCE_BRANCH}" >&2
  exit 1
}

# ==========================================
# 第一阶段：生成任务计划
# ==========================================
echo ""
echo "=== Phase 1: Generating Task Plan ==="
echo ""

python3 "${SCRIPT_DIR}/mr_review_planner.py" \
  --mr-iid "${TARGET_MR_IID}" \
  --mr-title "${MR_TITLE}" \
  --base-branch "origin/${TARGET_BRANCH}" \
  --head-branch "origin/${SOURCE_BRANCH}" \
  --mr-description "${MR_DESCRIPTION}" \
  --output task_plan.json || {
  echo "[ERROR] Failed to generate task plan" >&2
  exit 1
}

if [ ! -f task_plan.json ]; then
  echo "[ERROR] task_plan.json not found" >&2
  exit 1
fi

echo "[INFO] Task plan generated successfully"
echo "[DEBUG] Task plan contents:"
cat task_plan.json | head -50

# 检查是否有任务需要执行
SUBTASK_COUNT=$(python3 -c "import json; print(len(json.load(open('task_plan.json'))['subtasks']))")
echo "[INFO] Total subtasks to execute: ${SUBTASK_COUNT}"

if [ "$SUBTASK_COUNT" -eq 0 ]; then
  echo "[WARN] No review tasks generated. Exiting."
  
  NO_TASK_BODY="## 🤖 代码审查结果

未生成审查任务。可能原因：
- 所有变更都在排除列表中（如 node_modules, vendor 等）
- 变更文件为空

**MR信息**：
- 源分支：${SOURCE_BRANCH}
- 目标分支：${TARGET_BRANCH}
"
  
  curl --silent --show-error --fail \
    --request POST \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --data-urlencode "body=${NO_TASK_BODY}" \
    "${API}/merge_requests/${TARGET_MR_IID}/notes" > /dev/null || true
  
  exit 0
fi

# ==========================================
# 第二阶段：执行任务
# ==========================================
echo ""
echo "=== Phase 2: Executing Review Tasks ==="
echo ""

python3 "${SCRIPT_DIR}/mr_review_executor.py" \
  --plan task_plan.json \
  --workspace "$(pwd)" \
  --output review_results.json \
  --summary-output review_summary.md || {
  
  EXIT_CODE=$?
  echo "[ERROR] Task execution failed with code ${EXIT_CODE}" >&2
  
  # 即使失败也尝试发布部分结果
  if [ -f review_summary.md ]; then
    echo "[INFO] Posting partial results..."
    
    PARTIAL_BODY="## ⚠️ 代码审查部分失败

审查过程中遇到错误，以下是部分结果：

$(cat review_summary.md)

---
请检查 CI/CD 日志获取详细错误信息。
"
    
    curl --silent --show-error --fail \
      --request POST \
      --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      --data-urlencode "body=${PARTIAL_BODY}" \
      "${API}/merge_requests/${TARGET_MR_IID}/notes" > /dev/null || true
  fi
  
  exit $EXIT_CODE
}

echo "[INFO] Review execution completed successfully"

# ==========================================
# 第三阶段：发布结果
# ==========================================
echo ""
echo "=== Phase 3: Publishing Results ==="
echo ""

if [ ! -f review_summary.md ]; then
  echo "[ERROR] review_summary.md not found" >&2
  exit 1
fi

echo "[INFO] Posting review summary to MR..."

# 只发布统计信息，不包含详细findings（已通过inline comments发布）
REVIEW_STATS=$(python3 <<'PYSTAT'
import json
from pathlib import Path

results = json.loads(Path('review_results.json').read_text())
review_data = results.get('results_by_type', {}).get('review', {})

stats = review_data.get('statistics', {})
print(f"""### 📊 审查统计

**总体建议**: **{review_data.get('recommendation', 'NEEDS_DISCUSSION')}**

**发现的问题**:
- 🔴 Critical: {stats.get('critical', 0)}
- 🟠 Major: {stats.get('major', 0)}
- 🟡 Minor: {stats.get('minor', 0)}
- 💡 Suggestions: {stats.get('suggestion', 0)}

**审查覆盖**:
- 📁 审查文件数: {review_data.get('files_reviewed', 0)}
- ✅ 完成的子任务: {review_data.get('subtasks_completed', 0)}
- ❌ 失败的子任务: {review_data.get('subtasks_failed', 0)}

> 💡 详细的审查发现已通过内联评论发布到相应代码行，或查看 CI artifacts 中的完整报告。
""")
PYSTAT
)

REVIEW_BODY="## 🤖 Copilot 代码审查报告

${REVIEW_STATS}"

if [ -n "${CI_PIPELINE_URL:-}" ]; then
  REVIEW_BODY="${REVIEW_BODY}

---
- [🔗 Review Session](${CI_PIPELINE_URL})"
fi

# 保存到临时文件以便处理特殊字符
echo "$REVIEW_BODY" > review_comment.txt

curl --silent --show-error --fail \
  --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data-urlencode "body@review_comment.txt" \
  "${API}/merge_requests/${TARGET_MR_IID}/notes" > /dev/null || {
  echo "[ERROR] Failed to post review comment" >&2
  exit 1
}

echo "[SUCCESS] Review comment posted successfully"

# ==========================================
# 第四阶段（可选）：发布inline comments
# ==========================================
if [ "${ENABLE_INLINE_REVIEW_COMMENTS:-false}" = "true" ] && [ -f review_results.json ]; then
  echo ""
  echo "=== Phase 4: Posting Inline Comments ==="
  echo ""
  
  # 生成完整的diff文件（用于提取代码上下文）
  git diff "origin/${TARGET_BRANCH}...origin/${SOURCE_BRANCH}" > full_diff.txt
  echo "[INFO] Generated full_diff.txt ($(wc -l < full_diff.txt) lines)"
  
  # 获取commit SHAs并导出环境变量供Python使用
  export BASE_SHA=$(git rev-parse "origin/${TARGET_BRANCH}")
  export HEAD_SHA=$(git rev-parse "origin/${SOURCE_BRANCH}")
  export START_SHA=$(git merge-base "origin/${TARGET_BRANCH}" "origin/${SOURCE_BRANCH}")
  export API="${API}"
  export GITLAB_TOKEN="${GITLAB_TOKEN}"
  export TARGET_MR_IID="${TARGET_MR_IID}"
  
  echo "[DEBUG] BASE_SHA=${BASE_SHA}"
  echo "[DEBUG] HEAD_SHA=${HEAD_SHA}"
  echo "[DEBUG] START_SHA=${START_SHA}"
  
  # 使用Python脚本发布inline comments
  python3 <<'PYSCRIPT'
import json
import os
import sys
import subprocess
from pathlib import Path

# 读取结果
results = json.loads(Path('review_results.json').read_text())
all_findings = []

# 提取所有findings
for task_type, type_results in results.get('results_by_type', {}).items():
    if 'findings' in type_results:
        all_findings.extend(type_results['findings'])

print(f"[INFO] Found {len(all_findings)} total findings")

# 环境变量
api_url = os.environ["API"]
token = os.environ["GITLAB_TOKEN"]
mr_iid = os.environ["TARGET_MR_IID"]
base_sha = os.environ["BASE_SHA"]
start_sha = os.environ["START_SHA"]
head_sha = os.environ["HEAD_SHA"]
lang = os.environ.get("COPILOT_LANGUAGE", "zh")

# 读取 diff 内容以获取代码上下文
with open('full_diff.txt', 'r', encoding='utf-8') as f:
    diff_text = f.read()

# 中英文模板
templates = {
    'zh': {
        'severity': {'critical': '🔴 **严重**', 'major': '🟠 **重要**'},
        'issue': '问题',
        'suggestion': '建议',
        'category': '分类',
        'code': '相关代码'
    },
    'en': {
        'severity': {'critical': '🔴 **CRITICAL**', 'major': '🟠 **MAJOR**'},
        'issue': 'Issue',
        'suggestion': 'Suggestion',
        'category': 'Category',
        'code': 'Code Context'
    }
}
t = templates.get(lang, templates['zh'])

# 只发布critical和major的inline comments
high_priority = [f for f in all_findings if f.get('severity') in ['critical', 'major']]
print(f"[INFO] Total findings: {len(all_findings)}")
print(f"[INFO] Critical: {len([f for f in all_findings if f.get('severity') == 'critical'])}")
print(f"[INFO] Major: {len([f for f in all_findings if f.get('severity') == 'major'])}")
print(f"[INFO] Minor: {len([f for f in all_findings if f.get('severity') == 'minor'])}")
print(f"[INFO] Suggestion: {len([f for f in all_findings if f.get('severity') == 'suggestion'])}")
print(f"[INFO] Posting {len(high_priority)} high-priority inline comments")

posted_count = 0
skipped_no_location = 0
for finding in high_priority[:50]:  # 最多50个inline comments
    file_path = finding.get('file', '')
    line = finding.get('line', 0)
    
    if not file_path or line <= 0:
        skipped_no_location += 1
        print(f"[DEBUG] Skipped finding (no location): {finding.get('title', '')[:50]}")
        continue
    
    severity = finding.get('severity', 'major')
    severity_label = t['severity'].get(severity, t['severity']['major'])
    
    # 提取代码上下文（目标行前后3行）
    code_context = finding.get('code_snippet', '')
    if not code_context:
        # 如果 finding 中没有代码，尝试从 diff 中提取
        for diff_line in diff_text.split('\n'):
            if f'diff --git a/{file_path}' in diff_line:
                # 简单提示，实际应该解析 diff 格式
                code_context = f"Line {line}"
                break
    
    comment_body = f"""{severity_label}: {finding.get('title', '')}

**{t['issue']}**: {finding.get('description', '')}

**{t['suggestion']}**: {finding.get('suggestion', '')}

```
{code_context}
```

---
_{t['category']}: {finding.get('category', 'general')}_
"""
    
    # 构建API请求
    discussions_url = f"{api_url}/merge_requests/{mr_iid}/discussions"
    cmd = [
        "curl", "--silent", "--show-error",
        "--request", "POST",
        "--header", f"PRIVATE-TOKEN: {token}",
        "--data-urlencode", f"body={comment_body}",
        "--data-urlencode", f"position[base_sha]={base_sha}",
        "--data-urlencode", f"position[start_sha]={start_sha}",
        "--data-urlencode", f"position[head_sha]={head_sha}",
        "--data-urlencode", "position[position_type]=text",
        "--data-urlencode", f"position[new_path]={file_path}",
        "--data-urlencode", f"position[new_line]={line}",
        discussions_url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0:
            posted_count += 1
            print(f"[INFO] Posted inline comment on {file_path}:{line}")
        else:
            print(f"[WARN] Failed to post on {file_path}:{line} - {result.stderr[:200] if result.stderr else result.stdout[:200]}")
    except Exception as e:
        print(f"[WARN] Error posting inline comment: {e}")

print(f"[INFO] Summary: Posted {posted_count}, Skipped (no location) {skipped_no_location}")
PYSCRIPT
  
  echo "[INFO] Inline comments posted"
fi

cd "${REPO_ROOT}"

echo ""
echo "=========================================="
echo "  ✅ Review Complete!"
echo "=========================================="
echo ""
