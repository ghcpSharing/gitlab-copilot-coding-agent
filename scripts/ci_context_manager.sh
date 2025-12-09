#!/bin/bash
# CI Context Manager - 智能缓存管理和增量更新
# 集成 Phase 6 的所有功能：分支检测、智能缓存查找、增量更新

set -e

# ============= 配置 =============
REPO_DIR="${REPO_DIR:-repo-${TARGET_PROJECT_ID}}"
PROJECT_ID="${TARGET_PROJECT_ID}"
BRANCH="${TARGET_BRANCH:-main}"
CURRENT_COMMIT="${CI_COMMIT_SHA}"
PARENT_COMMIT="${CI_COMMIT_BEFORE_SHA}"
AZURE_CONNECTION="${AZURE_STORAGE_CONNECTION_STRING}"

# ============= 函数定义 =============

log_info() {
    echo "[INFO] $1"
}

log_warn() {
    echo "[WARN] $1"
}

log_error() {
    echo "[ERROR] $1"
}

# Task 6.1: 检测新分支并记录派生关系
detect_new_branch() {
    log_info "Detecting if this is a new branch..."
    
    cd "${REPO_DIR}"
    
    # 检查远程分支是否存在（除了当前 pipeline 刚推送的）
    # 使用 git ls-remote 检查远程是否有历史记录
    REMOTE_BRANCH_COUNT=$(git ls-remote origin "refs/heads/${BRANCH}" | wc -l)
    
    if [ "${REMOTE_BRANCH_COUNT}" -eq 0 ] || [ "${CI_COMMIT_BEFORE_SHA}" = "0000000000000000000000000000000000000000" ]; then
        log_info "✓ New branch detected: ${BRANCH}"
        export IS_NEW_BRANCH=true
        
        # 找到基准分支（通常是 main 或 master）
        BASE_BRANCH=$(git for-each-ref --format='%(refname:short)' refs/remotes/origin/ | grep -E '^origin/(main|master|develop)$' | head -n1 | sed 's|^origin/||')
        
        if [ -z "${BASE_BRANCH}" ]; then
            BASE_BRANCH="main"
            log_warn "Could not auto-detect base branch, using: ${BASE_BRANCH}"
        else
            log_info "Detected base branch: ${BASE_BRANCH}"
        fi
        
        # 找到 merge-base
        BASE_COMMIT=$(git merge-base HEAD "origin/${BASE_BRANCH}" 2>/dev/null || echo "")
        
        if [ -z "${BASE_COMMIT}" ]; then
            log_warn "Could not find merge-base, using first commit"
            BASE_COMMIT=$(git rev-list --max-parents=0 HEAD)
        fi
        
        log_info "Base commit: ${BASE_COMMIT:0:8}"
        
        # 记录分支派生关系
        if [ -n "${AZURE_CONNECTION}" ]; then
            log_info "Recording branch fork relationship..."
            cd ..
            python3 scripts/blob_cache.py record-fork \
                --connection-string "${AZURE_CONNECTION}" \
                --project-id "${PROJECT_ID}" \
                --branch "${BRANCH}" \
                --base-branch "${BASE_BRANCH}" \
                --base-commit "${BASE_COMMIT}" \
                --fork-type "branch" \
                --created-by "${GITLAB_USER_LOGIN:-unknown}" || log_warn "Failed to record fork"
            cd "${REPO_DIR}"
        fi
        
        export BASE_BRANCH
        export BASE_COMMIT
    else
        log_info "✓ Existing branch: ${BRANCH}"
        export IS_NEW_BRANCH=false
    fi
    
    cd ..
}

# Task 6.2: 智能缓存查找（5 级策略）
find_best_cache() {
    log_info "Searching for best cache using 5-level strategy..."
    
    if [ -z "${AZURE_CONNECTION}" ]; then
        log_warn "Azure connection not configured, skipping cache lookup"
        export CACHE_STRATEGY="full_analysis"
        return 1
    fi
    
    # 调用 find-best 命令
    CACHE_RESULT=$(python3 scripts/blob_cache.py find-best \
        --connection-string "${AZURE_CONNECTION}" \
        --project-id "${PROJECT_ID}" \
        --branch "${BRANCH}" \
        --commit "${CURRENT_COMMIT}" \
        --parent-commit "${PARENT_COMMIT}" 2>/dev/null || echo '{"found": false}')
    
    log_info "Cache lookup result: ${CACHE_RESULT}"
    
    # 解析 JSON 结果
    CACHE_FOUND=$(echo "${CACHE_RESULT}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('found', False))")
    
    if [ "${CACHE_FOUND}" = "True" ]; then
        export CACHE_STRATEGY=$(echo "${CACHE_RESULT}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('reuse_strategy', 'full_analysis'))")
        export CACHE_COMMIT=$(echo "${CACHE_RESULT}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('commit_sha', ''))")
        export CACHE_BASE_BRANCH=$(echo "${CACHE_RESULT}" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('base_branch', ''))")
        
        log_info "✓ Cache found! Strategy: ${CACHE_STRATEGY}"
        log_info "  Cache commit: ${CACHE_COMMIT:0:8}"
        [ -n "${CACHE_BASE_BRANCH}" ] && log_info "  Base branch: ${CACHE_BASE_BRANCH}"
        
        return 0
    else
        log_info "✗ No cache found, will perform full analysis"
        export CACHE_STRATEGY="full_analysis"
        return 1
    fi
}

# Task 6.3: 执行增量更新流程
run_incremental_update() {
    log_info "Running incremental update flow..."
    
    # 1. 下载基准缓存
    log_info "Downloading base context from ${CACHE_COMMIT:0:8}..."
    python3 scripts/blob_cache.py download \
        --connection-string "${AZURE_CONNECTION}" \
        --project-id "${PROJECT_ID}" \
        --branch "${BRANCH}" \
        --commit "${CACHE_COMMIT}" \
        --local-dir "${REPO_DIR}/.copilot.base" || {
        log_error "Failed to download base cache, falling back to full analysis"
        export CACHE_STRATEGY="full_analysis"
        return 1
    }
    
    # 2. 检测变更
    log_info "Detecting changes: ${CACHE_COMMIT:0:8}..${CURRENT_COMMIT:0:8}"
    python3 scripts/detect_changes.py \
        --repo "${REPO_DIR}" \
        --base-commit "${CACHE_COMMIT}" \
        --current-commit "${CURRENT_COMMIT}" \
        --output changes.json || {
        log_error "Failed to detect changes, falling back to full analysis"
        export CACHE_STRATEGY="full_analysis"
        return 1
    }
    
    # 显示变更统计
    AFFECTED_MODULES=$(python3 -c "import json; data=json.load(open('changes.json')); print(', '.join(data.get('affected_modules', [])))")
    TOTAL_CHANGES=$(python3 -c "import json; data=json.load(open('changes.json')); print(data.get('total_changed_files', 0))")
    
    log_info "Changes detected:"
    log_info "  Total files: ${TOTAL_CHANGES}"
    log_info "  Affected modules: ${AFFECTED_MODULES}"
    
    # 3. 执行增量更新
    log_info "Running incremental analysis..."
    
    # 在主仓库根目录运行（Copilot CLI 认证与当前 git 仓库绑定）
    export PYTHONPATH="${PWD}/index_repo/src:${PYTHONPATH:-}"
    
    # 使用 Orchestrator 的增量更新 API
    python3 -c "
from pathlib import Path
from project_understanding.orchestrator import Orchestrator, OrchestratorConfig

config = OrchestratorConfig(
    agent_timeout=3600,
    enable_cache=False,
    output_dir='.copilot'
)

orchestrator = Orchestrator(
    workspace=Path('${REPO_DIR}'),
    config=config,
    repo_id='${PROJECT_ID}',
    branch='${BRANCH}',
    commit_sha='${CURRENT_COMMIT}'
)

try:
    context = orchestrator.run_incremental_update(
        base_context_dir=Path('${REPO_DIR}/.copilot.base'),
        changes_json_path=Path('changes.json'),
        update_modules=None  # Auto-detect
    )
    print('[SUCCESS] Incremental update completed')
    print(f'  Updated modules: {len(context.scan.files)} files analyzed')
except Exception as e:
    print(f'[ERROR] Incremental update failed: {e}')
    exit(1)
" || {
        log_error "Incremental update failed, falling back to full analysis"
        export CACHE_STRATEGY="full_analysis"
        return 1
    }
    
    log_info "✓ Incremental update completed successfully"
    return 0
}

# 执行完整分析
run_full_analysis() {
    log_info "Running full project analysis..."
    
    # 在主仓库根目录运行（Copilot CLI 认证与当前 git 仓库绑定）
    # 使用 PYTHONPATH 导入 project_understanding 模块
    export PYTHONPATH="${PWD}/index_repo/src:${PYTHONPATH:-}"
    python3 -m project_understanding.cli \
        "${REPO_DIR}" \
        --output-dir "${REPO_DIR}/.copilot" \
        --output-file project_context.md \
        --no-cache \
        --timeout 3600 \
        -v || {
        log_error "Full analysis failed"
        return 1
    }
    
    log_info "✓ Full analysis completed"
    return 0
}

# 上传新缓存（带去重）
upload_cache_with_dedup() {
    log_info "Uploading context cache with deduplication..."
    
    if [ -z "${AZURE_CONNECTION}" ]; then
        log_warn "Azure connection not configured, skipping cache upload"
        return 0
    fi
    
    if [ ! -d "${REPO_DIR}/.copilot" ]; then
        log_warn "No context directory found, skipping upload"
        return 0
    fi
    
    # 上传时使用去重功能
    python3 scripts/blob_cache.py upload \
        --connection-string "${AZURE_CONNECTION}" \
        --project-id "${PROJECT_ID}" \
        --branch "${BRANCH}" \
        --commit "${CURRENT_COMMIT}" \
        --parent-commit "${PARENT_COMMIT}" \
        --local-dir "${REPO_DIR}/.copilot" || {
        log_warn "Failed to upload cache"
        return 1
    }
    
    log_info "✓ Cache uploaded successfully"
    return 0
}

# ============= 主流程 =============

main() {
    log_info "====== CI Context Manager ======"
    log_info "Project: ${PROJECT_ID}"
    log_info "Branch: ${BRANCH}"
    log_info "Commit: ${CURRENT_COMMIT:0:8}"
    log_info "Parent: ${PARENT_COMMIT:0:8}"
    log_info "================================"
    
    START_TIME=$(date +%s)
    
    # Step 1: 检测新分支
    detect_new_branch
    
    # Step 2: 智能缓存查找
    find_best_cache
    
    # Step 3: 根据策略执行分析
    case "${CACHE_STRATEGY}" in
        "exact")
            log_info "Strategy: Exact match - Using cached context directly"
            python3 scripts/blob_cache.py download \
                --connection-string "${AZURE_CONNECTION}" \
                --project-id "${PROJECT_ID}" \
                --branch "${BRANCH}" \
                --commit "${CACHE_COMMIT}" \
                --local-dir "${REPO_DIR}/.copilot"
            SKIP_UPLOAD=true
            ;;
        
        "incremental"|"parent_commit"|"branch_latest")
            log_info "Strategy: ${CACHE_STRATEGY} - Running incremental update"
            run_incremental_update || run_full_analysis
            ;;
        
        "cross-branch")
            log_info "Strategy: Cross-branch - Running incremental update from ${CACHE_BASE_BRANCH}"
            run_incremental_update || run_full_analysis
            ;;
        
        "full_analysis"|*)
            log_info "Strategy: Full analysis - Analyzing entire project"
            run_full_analysis
            ;;
    esac
    
    # Step 4: 上传新缓存
    if [ "${SKIP_UPLOAD}" != "true" ]; then
        upload_cache_with_dedup
    fi
    
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    
    log_info "================================"
    log_info "Context management completed in ${DURATION}s"
    log_info "Strategy used: ${CACHE_STRATEGY}"
    log_info "================================"
}

# 执行主流程
main
