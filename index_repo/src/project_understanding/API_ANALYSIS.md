# API Analysis: Project Understanding Module

## API Type
- **Type**: CLI Tool (Command-Line Interface)
- **Interface**: Python module with subprocess-based internal API
- **Base Path**: N/A (CLI-based, not HTTP REST/GraphQL/gRPC)
- **Execution**: `python -m project_understanding.cli`

## Architecture Pattern

This is **NOT a traditional web API**. Instead, it's an **Agent-based CLI orchestration system** with:

### 1. **External Interface (CLI)**
```bash
python -m project_understanding.cli [OPTIONS] [WORKSPACE]
```

**Command-Line Arguments:**
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `WORKSPACE` | path | Project directory | current dir |
| `--output-dir` | str | Output directory | `.copilot` |
| `--output-file` | str | Output filename | `context.md` |
| `--no-review` | flag | Disable review | false |
| `--no-cache` | flag | Disable caching | false |
| `--max-tokens` | int | Max output tokens | 4000 |
| `--timeout` | int | Copilot timeout (sec) | 120 |
| `--model` | str | Model name | `claude-sonnet-4` |
| `--repo-id` | str | GitLab repo ID | - |
| `--branch` | str | Branch name | - |
| `--commit` | str | Commit SHA | - |
| `-v, --verbose` | flag | Verbose output | false |

### 2. **Internal API (Python Classes)**

The system uses an **object-oriented orchestration pattern** with subprocess-based Copilot calls.

#### Core Components:

```python
# Entry Point
Orchestrator(workspace, config, repo_id, branch, commit_sha)
  └─> run() -> ProjectContext

# Copilot Client (Subprocess API)
CopilotClient(timeout, max_retries, model)
  ├─> call(prompt, context) -> CopilotResponse
  ├─> call_with_retry() -> CopilotResponse
  └─> call_with_output_file() -> (CopilotResponse, dict)

# Agent Base Classes
BaseAgent(config, client)
  └─> analyze(scan_result) -> AgentOutput

ReviewableAgent(BaseAgent)
  └─> analyze_with_review(scan_result, reviewer) -> AgentOutput
```

## Request/Response Patterns

### 1. **CLI Invocation Pattern**
```bash
# Input: Command-line arguments
python -m project_understanding.cli /path/to/project --no-review

# Output: Files written to disk
.copilot/
  ├── context.md              # Main output
  ├── context_details.md      # Detailed analysis
  ├── agent_tech_stack.md     # Individual agent outputs
  ├── agent_data_model.md
  ├── agent_domain.md
  ├── agent_security.md
  ├── agent_api.md
  └── cache_metadata.json     # Cache metadata
```

### 2. **Internal Copilot API Pattern**
```python
# Request Pattern (subprocess stdin)
CopilotClient.call(
    prompt: str,           # System prompt
    context: str           # Project context
) -> CopilotResponse

# Process execution
subprocess.run(
    ['copilot', '--allow-all-tools'],
    input=f"{prompt}\n\n---\nContext:\n{context}",
    capture_output=True,
    timeout=120
)

# Response Pattern
CopilotResponse:
  - success: bool
  - content: str          # stdout
  - error: str | None     # stderr
  - exit_code: int
```

### 3. **Agent Communication Pattern**
```python
# Input to Agent
ScanResult:
  - file_tree: str
  - key_files: dict[str, FileInfo]
  - total_files: int
  - languages: list[str]

# Output from Agent
AgentOutput:
  - agent: AgentRole
  - content: str           # Markdown analysis
  - raw_response: str
  - success: bool
  - error: str | None
  - retry_count: int
```

## Data Models (Domain Objects)

### Core Models
```python
@dataclass
class FileInfo:
    path: str
    category: str          # config, schema, source, doc, test
    size: int
    content: str | None

@dataclass
class ScanResult:
    file_tree: str
    key_files: dict[str, FileInfo]
    total_files: int
    languages: list[str]

@dataclass
class AgentOutput:
    agent: AgentRole       # Enum: SCANNER, TECH_STACK, etc.
    content: str
    raw_response: str
    success: bool
    error: str | None
    retry_count: int

@dataclass
class ProjectContext:
    repo_id: str
    branch: str
    commit_sha: str
    tech_stack: AgentOutput | None
    data_model: AgentOutput | None
    domain: AgentOutput | None
    security: AgentOutput | None
    api_structure: AgentOutput | None
    reviews: list[ReviewResult]
    final_context: str     # Synthesized markdown
    token_count: int
    created_at: datetime
    analysis_time_ms: int
```

## Agent Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      Orchestrator.run()                      │
└─────────────────────────────────────────────────────────────┘
                             ↓
        ┌────────────────────┴────────────────────┐
        │    Phase 1: Scanner (Python)            │
        │    scan_project(workspace) -> ScanResult│
        └────────────────────┬────────────────────┘
                             ↓
        ┌────────────────────┴────────────────────┐
        │    Phase 2: Expert Agents (Parallel)    │
        │    ThreadPoolExecutor(max_workers=5)    │
        ├─────────────────────────────────────────┤
        │  ┌─> TechStackAgent.analyze()           │
        │  ├─> DataModelAgent.analyze()           │
        │  ├─> DomainAgent.analyze()              │
        │  ├─> SecurityAgent.analyze()            │
        │  └─> APIAgent.analyze()                 │
        │     (each calls CopilotClient via subprocess)
        └────────────────────┬────────────────────┘
                             ↓
        ┌────────────────────┴────────────────────┐
        │    Phase 3: Synthesizer                 │
        │    SynthesizerAgent.synthesize()        │
        │    (merge & compress to max_tokens)     │
        └────────────────────┬────────────────────┘
                             ↓
        ┌────────────────────┴────────────────────┐
        │    Phase 4: Output                      │
        │    Write .copilot/*.md files            │
        └─────────────────────────────────────────┘
```

## Error Handling

### 1. **CLI Level**
```python
try:
    context = orchestrator.run()
    sys.exit(0)
except KeyboardInterrupt:
    logger.info("Analysis interrupted")
    sys.exit(130)
except Exception as e:
    logger.exception(f"Analysis failed: {e}")
    sys.exit(1)
```

**Exit Codes:**
- `0`: Success
- `1`: General error
- `130`: Interrupted (Ctrl+C)

### 2. **Copilot Client Level**
```python
CopilotResponse.exit_code:
  - 0:   Success
  - 1:   General error
  - 124: Timeout (subprocess.TimeoutExpired)
  - 127: Command not found (copilot CLI missing)
```

**Retry Strategy:**
- Max retries: 2 (configurable)
- Retries on timeout (124)
- No retry on command not found (127)

### 3. **Agent Level**
```python
AgentOutput:
  - success: bool
  - error: str | None
  - retry_count: int

# Reviewer feedback loop (if enabled)
for iteration in range(max_iterations):
    review_result = reviewer.review(output)
    if review_result.status == PASSED:
        return output
    elif review_result.status == FAILED:
        output = retry_with_feedback(suggestions)
```

## Versioning Strategy

- **No API versioning** (CLI tool, not web service)
- **Module version**: Implicit (Python package)
- **Output format**: Stable markdown structure
- **Cache version**: `cache_metadata.json` includes `"version": "1.0"`

**Cache Invalidation:**
- Different `commit_sha` → cache miss
- Expired (> 7 days) → cache miss
- `--no-cache` flag → bypass cache

## Integration Patterns

### 1. **GitLab CI Integration**
```yaml
project-analysis:
  stage: analyze
  script:
    - python -m project_understanding.cli --no-cache -v
  artifacts:
    paths:
      - .copilot/
```

### 2. **Bash Script Integration**
```bash
python -m project_understanding.cli \
    --repo-id "${CI_PROJECT_ID}" \
    --branch "${CI_COMMIT_REF_NAME}" \
    --commit "${CI_COMMIT_SHA}"

export PROJECT_CONTEXT=$(cat .copilot/context.md)
```

### 3. **Programmatic Integration**
```python
from project_understanding.orchestrator import Orchestrator, OrchestratorConfig

config = OrchestratorConfig(
    enable_review=False,
    max_context_tokens=4000
)

orchestrator = Orchestrator(
    workspace=Path("/project"),
    config=config,
    repo_id="123",
    branch="main",
    commit_sha="abc123"
)

context = orchestrator.run()
print(context.final_context)
```

## Performance Characteristics

- **Execution Time**: 2-5 minutes (first run)
- **Parallel Execution**: Up to 5 agents concurrently
- **Timeout**: 120 seconds per Copilot call (configurable)
- **Token Limit**: 4000 tokens output (configurable)
- **Caching**: Commit-based, 7-day expiration

**Optimization Flags:**
- `--no-review`: ~30% faster (skips quality validation)
- `--max-tokens 2000`: Smaller output, faster synthesis
- Cached result: < 1 second

## Security Considerations

1. **Subprocess Execution**: Uses `subprocess.run()` with explicit command array (no shell injection)
2. **File System Access**: Reads workspace files, writes to `.copilot/` directory
3. **Environment Variables**: Reads CI variables (`CI_PROJECT_ID`, etc.)
4. **No Network API**: Pure CLI tool, no HTTP/network exposure
5. **Copilot CLI Dependency**: Requires authenticated `gh copilot` CLI

## Summary

This is **not a REST/GraphQL/gRPC API**, but a **CLI orchestration tool** with:

- **Interface**: Command-line + Python module API
- **Architecture**: Multi-agent system with subprocess-based Copilot calls
- **Communication**: Local file I/O and stdout/stderr
- **Execution**: Sequential (Scanner) → Parallel (Agents) → Sequential (Synthesizer)
- **Output**: Markdown files on disk
- **Error Handling**: Exit codes + structured error objects
- **No versioning**: CLI tool without web API versioning needs
