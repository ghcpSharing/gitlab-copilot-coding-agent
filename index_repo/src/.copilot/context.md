# Project Context

## Overview
A CLI-based multi-agent orchestration system that analyzes codebases using GitHub Copilot to generate comprehensive project documentation for GitLab MR reviews.

## Tech Stack
- **Languages**: Python 3.10+
- **Frameworks**: Custom multi-agent orchestration (inspired by Microsoft Agent Framework)
- **Key Dependencies**: 
  - GitHub Copilot CLI (`gh copilot`) - core AI execution engine
  - `concurrent.futures` - parallel agent execution
  - `subprocess` - external process wrapper
  - `dataclasses` - structured data modeling
  - Standard library only (no external Python packages)

## Architecture
- **Pattern**: Multi-agent orchestration with pipeline processing
- **Layers**:
  - **CLI Layer**: `argparse`-based command interface (`cli.py`)
  - **Orchestration Layer**: Workflow coordination, caching, parallel execution (`orchestrator.py`)
  - **Agent Layer**: 7 specialized agents (Scanner, TechStack, DataModel, Domain, Security, API, Reviewer, Synthesizer)
  - **Infrastructure Layer**: Copilot subprocess adapter (`copilot.py`), file system scanner (`scanner.py`)
- **Execution Model**: ThreadPoolExecutor (max 5 workers) for parallel expert analysis, sequential synthesis
- **State Management**: In-memory dataclasses, file-based caching (`.copilot/`)

## Data Model
**Core Entities**:
- `ScanResult` → contains multiple `FileInfo` (project structure snapshot)
- `ProjectContext` → aggregates 5 `AgentOutput` instances (tech, data, domain, security, API)
- `AgentOutput` → produced by agents, validated by `ReviewResult`
- `CacheMetadata` → tracks cache validity (commit SHA + 7-day expiration)

**Enums**: `AgentRole` (8 roles), `ReviewStatus` (PENDING/PASSED/FAILED/RETRY)

**Key DTOs**: `CopilotResponse` (subprocess wrapper), `AgentConfig`, `OrchestratorConfig`

## API Structure
**Type**: CLI tool (not REST/GraphQL)

**CLI Interface**:
```bash
python -m project_understanding.cli \
  --workspace /path/to/repo \
  --output-dir .copilot \
  [--review] [--no-cache] [--parallel-agents]
```

**Internal APIs**:
- `Scanner.scan_workspace()` → `ScanResult`
- `Agent.analyze(scan_result)` → `AgentOutput`
- `CopilotClient.call(prompt)` → `CopilotResponse`
- `Orchestrator.analyze()` → `ProjectContext`

**Output**: Markdown files (`context.md`, `context_details.md`, `agent_*.md`)

## Security
- **Authentication**: None (delegates to `gh` CLI OAuth)
- **Authorization**: OS-level file system permissions only
- **Data Protection**: 
  - No encryption (plaintext processing and caching)
  - File contents sent to Copilot API without sanitization
  - Cache stored in `.copilot/` directory (plaintext)
- **Key Risks**:
  - Sensitive file exposure to external API
  - Cache contains code snippets in plaintext
  - No secrets filtering in scanned content
- **Mitigations**:
  - File size limit (100KB), depth limit (10 levels), file count limit (500)
  - Hardcoded subprocess command (no shell injection)
  - Timeout protection (3600s default)
  - Path traversal prevention via `Path.resolve()`

## Code Review Focus Areas

### 1. **Agent Output Quality**
- Verify `Reviewer` agent validation logic (70% confidence threshold)
- Check retry mechanism (max 2 iterations) for failed reviews
- Ensure fallback synthesis activates on Copilot API failures

### 2. **Parallel Execution Safety**
- Review ThreadPoolExecutor error isolation (each agent in try/except)
- Confirm file writes are atomic and non-overlapping (separate files per agent)
- Validate no race conditions in cache metadata writes

### 3. **Cache Invalidation**
- Verify commit SHA matching logic prevents stale context
- Check 7-day expiration enforced correctly
- Ensure cache miss triggers full re-analysis

### 4. **Error Handling Paths**
- Test timeout handling (exit 124) triggers retry
- Verify command-not-found (exit 127) terminates immediately
- Confirm graceful degradation (review failures default to PASSED)

### 5. **Resource Limits**
- Validate scanner stops at 500 files, 10 depth levels
- Check 100KB file content truncation enforced
- Ensure subprocess timeout prevents indefinite hangs

### 6. **Input Validation**
- Review CLI argument parsing for edge cases (`--workspace` required)
- Check file path sanitization in scanner
- Verify no user-controlled data in subprocess commands

### 7. **Sensitive Data Exposure**
- Flag if auth/secrets files (`.env`, `credentials.json`) are included in key_files
- Check if error messages leak full file paths
- Verify cache files have appropriate permissions

### 8. **Integration Points**
- Test GitLab CI environment variable handling (`CI_COMMIT_SHA`, `CI_PROJECT_ID`)
- Verify artifact output directory creation
- Confirm exit codes align with CI expectations (0/1/130)