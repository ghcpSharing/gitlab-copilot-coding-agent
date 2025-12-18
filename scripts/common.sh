#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export UPSTREAM_GITLAB_BASE_URL="${UPSTREAM_GITLAB_BASE_URL:-https://gitlab.com}"

# Maximum file size for git commit (default: 50MB)
MAX_FILE_SIZE_MB="${MAX_FILE_SIZE_MB:-50}"

# Files/patterns to always exclude from commits
EXCLUDED_PATTERNS=(
  "core"
  "core.*"
  "*.core"
  "*.dump"
  "*.heapdump"
  "*.heapsnapshot"
  "*.log"
  "*.tmp"
  "*.temp"
  "*.swp"
  "*.swo"
  ".DS_Store"
  "Thumbs.db"
  "node_modules"
  "__pycache__"
  "*.pyc"
  ".venv"
  "venv"
  ".env"
  "*.env.local"
)

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Environment variable ${name} is required" >&2
    exit 1
  fi
}

# Function to check and exclude large/unwanted files before commit
# Usage: pre_commit_cleanup [repo_dir]
pre_commit_cleanup() {
  local repo_dir="${1:-.}"
  local excluded_count=0
  local large_file_count=0
  
  echo "[INFO] Running pre-commit cleanup..."
  
  cd "$repo_dir" || return 1
  
  # 1. Check for large files in staging area
  local max_size_bytes=$((MAX_FILE_SIZE_MB * 1024 * 1024))
  
  # Get list of staged files
  local staged_files
  staged_files=$(git diff --cached --name-only 2>/dev/null || true)
  
  if [[ -n "$staged_files" ]]; then
    while IFS= read -r file; do
      if [[ -f "$file" ]]; then
        local file_size
        file_size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
        
        if [[ "$file_size" -gt "$max_size_bytes" ]]; then
          local size_mb=$((file_size / 1024 / 1024))
          echo "[WARN] Excluding large file: $file (${size_mb}MB > ${MAX_FILE_SIZE_MB}MB limit)"
          git reset HEAD -- "$file" 2>/dev/null || true
          # Also add to .gitignore if not already there
          if ! grep -qF "$file" .gitignore 2>/dev/null; then
            echo "$file" >> .gitignore
            echo "[INFO] Added $file to .gitignore"
          fi
          ((large_file_count++))
        fi
      fi
    done <<< "$staged_files"
  fi
  
  # 2. Check for excluded patterns in staging area
  for pattern in "${EXCLUDED_PATTERNS[@]}"; do
    # Find matching staged files
    local matching_files
    matching_files=$(git diff --cached --name-only 2>/dev/null | grep -E "^${pattern}$|/${pattern}$|^${pattern}/|/${pattern}/" 2>/dev/null || true)
    
    # Also check exact pattern match
    if [[ -z "$matching_files" ]]; then
      matching_files=$(git diff --cached --name-only 2>/dev/null | grep -F "$pattern" 2>/dev/null || true)
    fi
    
    if [[ -n "$matching_files" ]]; then
      while IFS= read -r file; do
        if [[ -n "$file" ]]; then
          echo "[WARN] Excluding unwanted file: $file (matches pattern: $pattern)"
          git reset HEAD -- "$file" 2>/dev/null || true
          ((excluded_count++))
        fi
      done <<< "$matching_files"
    fi
  done
  
  # 3. Ensure common patterns are in .gitignore
  local gitignore_additions=()
  for pattern in "core" "core.*" "*.core" "*.dump" "*.heapdump"; do
    if ! grep -qF "$pattern" .gitignore 2>/dev/null; then
      gitignore_additions+=("$pattern")
    fi
  done
  
  if [[ ${#gitignore_additions[@]} -gt 0 ]]; then
    echo "" >> .gitignore
    echo "# Auto-added by copilot agent" >> .gitignore
    for pattern in "${gitignore_additions[@]}"; do
      echo "$pattern" >> .gitignore
    done
    git add .gitignore 2>/dev/null || true
    echo "[INFO] Added ${#gitignore_additions[@]} patterns to .gitignore"
  fi
  
  if [[ $large_file_count -gt 0 ]] || [[ $excluded_count -gt 0 ]]; then
    echo "[INFO] Pre-commit cleanup: excluded $large_file_count large files, $excluded_count unwanted files"
  else
    echo "[INFO] Pre-commit cleanup: no issues found"
  fi
  
  return 0
}

# Function to get safe untracked files (excluding large and unwanted files)
# Usage: get_safe_untracked_files [repo_dir]
get_safe_untracked_files() {
  local repo_dir="${1:-.}"
  local max_size_bytes=$((MAX_FILE_SIZE_MB * 1024 * 1024))
  
  cd "$repo_dir" || return 1
  
  git ls-files --others --exclude-standard 2>/dev/null | while IFS= read -r file; do
    # Skip if file doesn't exist
    [[ -f "$file" ]] || continue
    
    # Skip large files
    local file_size
    file_size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
    if [[ "$file_size" -gt "$max_size_bytes" ]]; then
      echo "[SKIP] Large file: $file ($(( file_size / 1024 / 1024 ))MB)" >&2
      continue
    fi
    
    # Skip excluded patterns
    local skip=false
    for pattern in "${EXCLUDED_PATTERNS[@]}"; do
      case "$file" in
        $pattern|*/$pattern|$pattern/*|*/$pattern/*)
          echo "[SKIP] Excluded pattern: $file" >&2
          skip=true
          break
          ;;
      esac
    done
    
    if [[ "$skip" == "false" ]]; then
      echo "$file"
    fi
  done
}

# Robust branch checkout function with multiple fallback methods
# Handles branches with slashes (e.g., copilot/issue-8) correctly
# Usage: robust_checkout <branch_name> [repo_dir]
# Returns: 0 on success, 1 on failure
robust_checkout() {
  local branch="$1"
  local repo_dir="${2:-.}"
  
  if [[ -z "$branch" ]]; then
    echo "[ERROR] Branch name is required" >&2
    return 1
  fi
  
  cd "$repo_dir" || return 1
  
  echo "[INFO] Attempting to checkout branch: $branch"
  echo "[DEBUG] Available remote branches:"
  git branch -r 2>/dev/null | head -20 || true
  echo "[DEBUG] Checking for refs matching branch:"
  git show-ref 2>/dev/null | grep -F "$branch" || echo "No refs found matching $branch"
  
  # Fetch latest from origin first
  echo "[INFO] Fetching latest from origin..."
  git fetch origin 2>/dev/null || git fetch --all 2>/dev/null || true
  
  # Method 1: Direct checkout (works if branch exists locally or as remote tracking)
  echo "[INFO] Method 1: Direct checkout..."
  if git checkout "$branch" 2>/dev/null; then
    echo "[SUCCESS] Checked out branch $branch using direct checkout"
    return 0
  fi
  
  # Method 2: Delete local branch first (if corrupted), then create from origin
  echo "[INFO] Method 2: Delete local + create from origin..."
  git branch -D "$branch" 2>/dev/null || true  # Delete local if exists
  if git checkout -b "$branch" "origin/$branch" 2>/dev/null; then
    echo "[SUCCESS] Checked out branch $branch by creating from origin/$branch"
    return 0
  fi
  
  # Method 3: Use --track option
  echo "[INFO] Method 3: Track remote branch..."
  if git checkout --track "origin/$branch" 2>/dev/null; then
    echo "[SUCCESS] Checked out branch $branch using --track"
    return 0
  fi
  
  # Method 4: Explicit fetch of the branch then checkout
  echo "[INFO] Method 4: Explicit fetch + checkout..."
  if git fetch origin "$branch:$branch" 2>/dev/null && git checkout "$branch" 2>/dev/null; then
    echo "[SUCCESS] Checked out branch $branch using explicit fetch"
    return 0
  fi
  
  # Method 5: Fetch to FETCH_HEAD and create branch from it
  echo "[INFO] Method 5: FETCH_HEAD method..."
  if git fetch origin "$branch" 2>/dev/null; then
    git branch -D "$branch" 2>/dev/null || true
    if git checkout -b "$branch" FETCH_HEAD 2>/dev/null; then
      echo "[SUCCESS] Checked out branch $branch from FETCH_HEAD"
      return 0
    fi
  fi
  
  # Method 6: Detached HEAD then create branch
  echo "[INFO] Method 6: Detached HEAD + branch creation..."
  if git checkout "origin/$branch" 2>/dev/null; then
    if git checkout -b "$branch" 2>/dev/null; then
      echo "[SUCCESS] Created and checked out branch $branch from detached HEAD"
      return 0
    fi
  fi
  
  # Method 7: Use refs/remotes directly
  echo "[INFO] Method 7: Using refs/remotes directly..."
  if git checkout -b "$branch" "refs/remotes/origin/$branch" 2>/dev/null; then
    echo "[SUCCESS] Checked out branch $branch using refs/remotes"
    return 0
  fi
  
  echo "[ERROR] All checkout methods failed for branch: $branch" >&2
  echo "[DEBUG] Final state - all refs:" >&2
  git show-ref 2>/dev/null | head -30 >&2 || true
  return 1
}

