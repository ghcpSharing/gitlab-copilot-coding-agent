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
  
  # Fetch latest from origin first
  echo "[INFO] Fetching from origin..."
  git fetch origin --prune 2>&1 || true
  
  echo "[DEBUG] Remote refs for this branch:"
  git ls-remote origin "refs/heads/$branch" 2>&1 || true
  
  # Method 1: Simple - just use the commit SHA directly
  echo "[INFO] Method 1: Get SHA and checkout directly..."
  local sha
  sha=$(git ls-remote origin "refs/heads/$branch" 2>/dev/null | awk '{print $1}')
  if [[ -n "$sha" ]]; then
    echo "[DEBUG] Found SHA: $sha"
    # Delete any existing local branch
    git branch -D "$branch" 2>/dev/null || true
    # Checkout the SHA in detached HEAD
    if git checkout "$sha" 2>&1; then
      # Create local branch from current HEAD
      if git checkout -b "$branch" 2>&1; then
        echo "[SUCCESS] Checked out branch $branch (SHA: $sha)"
        return 0
      fi
    fi
  fi
  
  # Method 2: Fetch specific ref and checkout
  echo "[INFO] Method 2: Fetch specific ref..."
  git branch -D "$branch" 2>/dev/null || true
  if git fetch origin "refs/heads/$branch:refs/heads/$branch" 2>&1; then
    if git checkout "$branch" 2>&1; then
      echo "[SUCCESS] Checked out branch $branch via specific ref fetch"
      return 0
    fi
  fi
  
  # Method 3: Try with quotes around the branch name (for branches with slashes)
  echo "[INFO] Method 3: Checkout with origin prefix..."
  git branch -D "$branch" 2>/dev/null || true
  if git checkout -b "$branch" --track "origin/$branch" 2>&1; then
    echo "[SUCCESS] Checked out branch $branch with --track"
    return 0
  fi

  echo "[ERROR] All checkout methods failed for branch: $branch" >&2
  echo "[DEBUG] Final git status:" >&2
  git status 2>&1 >&2
  echo "[DEBUG] All remote branches:" >&2
  git branch -r 2>&1 >&2
  return 1
}
