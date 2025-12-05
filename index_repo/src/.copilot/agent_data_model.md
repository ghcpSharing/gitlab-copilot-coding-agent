# Data Model Analysis

- Status: ✓ Success
- Retries: 0

---

I'll analyze the project's data structures by examining the models and related files.

✔ List directory project_understanding
   └ 18 files found

✔ Glob "**/*.py"
   └ 14 files found

✔ List directory project_understanding/models
   └ 6 files found

✔ List directory project_understanding/services
   └ 6 files found

✔ Read project_understanding/orchestrator.py
   └ 437 lines read

✔ Read project_understanding/agents/__init__.py
   └ 259 lines read

✔ Read project_understanding/copilot.py
   └ 265 lines read

✔ Read project_understanding/scanner.py
   └ 250 lines read

✔ Grep "class.*Agent" in agents/*.py
   └ No matches found

✘ $ find /workspaces/codes/gitlab-copilot-coding-agent -name "*.py" -type f | grep -E
   "(database|db|orm|migrate)" | head -20
   Permission denied and could not request permission from user

✔ Glob "**/*.sql"
   └ No matches found

✔ Read project_understanding/agents/data_model.py
   └ 80 lines read

✔ Glob "**/requirements*.txt"
   └ No matches found

Based on my analysis of the project's data structures, here is the data model documentation:

```markdown
## Database Schema
**No Traditional Database** - This is a static analysis tool with in-memory data structures only
- Uses Python dataclasses with no persistence layer
- No SQL/NoSQL database configured
- Data exists only during runtime

## Entity Relationships

### Core Entities

**ScanResult** --1:N--> **FileInfo**
- ScanResult contains multiple FileInfo objects categorized by type

**ProjectContext** --1:1--> **AgentOutput** (multiple types)
- ProjectContext aggregates outputs from 5 specialized agents
- tech_stack, data_model, domain, security, api_structure

**ProjectContext** --1:N--> **ReviewResult**
- ProjectContext contains multiple review results

**AgentOutput** --N:1--> **AgentRole**
- Multiple outputs can share the same role (via retries)

**CacheMetadata** --1:1--> **ProjectContext**
- Metadata tracks cache validity for a project context

### Relationship Summary
```
ScanResult (1) ──> (N) FileInfo
ProjectContext (1) ──> (1) AgentOutput × 5
ProjectContext (1) ──> (N) ReviewResult
AgentOutput (N) ──> (1) AgentRole (enum)
CacheMetadata (1) ──> (1) ProjectContext
```

## Data Transfer Objects

### Input DTOs
- **FileInfo**: Represents scanned file metadata
  - path: str
  - category: str (config/schema/source/doc/test)
  - size: int
  - content: Optional[str]

- **ScanResult**: Aggregated scan output
  - file_tree: str
  - key_files: dict[str, FileInfo]
  - total_files: int
  - languages: list[str]

### Output DTOs
- **AgentOutput**: Individual agent analysis result
  - agent: AgentRole
  - content: str (markdown formatted analysis)
  - raw_response: str
  - success: bool
  - error: Optional[str]
  - retry_count: int

- **ReviewResult**: Quality assurance feedback
  - agent: AgentRole
  - status: ReviewStatus (PENDING/PASSED/FAILED/RETRY)
  - issues: list[str]
  - suggestions: list[str]

### Context DTOs
- **ProjectContext**: Final aggregated analysis
  - repo_id: str
  - branch: str
  - commit_sha: str
  - tech_stack/data_model/domain/security/api_structure: Optional[AgentOutput]
  - reviews: list[ReviewResult]
  - final_context: str (synthesized markdown)
  - token_count: int
  - created_at: datetime
  - analysis_time_ms: int

- **CacheMetadata**: Cache control
  - repo_id/branch/commit_sha: str (cache key)
  - last_updated: datetime
  - version: str
  - is_expired(max_age_days): bool method

### Configuration DTOs
- **AgentConfig**: Agent runtime settings
  - max_retries: int = 2
  - timeout: int = 120
  - model: str = "claude-sonnet-4"
  - max_output_tokens: int = 4096

- **OrchestratorConfig**: Workflow settings
  - agent_timeout/max_retries/model
  - parallel_agents: bool = True
  - max_workers: int = 5
  - enable_review: bool = False
  - output_dir/output_file
  - enable_cache: bool = True
  - cache_max_age_days: int = 7

### Communication DTOs
- **CopilotResponse**: External service response
  - success: bool
  - content: str
  - error: Optional[str]
  - exit_code: int

## Validation Rules

### Enum Constraints
- **AgentRole**: Limited to 8 roles (SCANNER/TECH_STACK/DATA_MODEL/DOMAIN/SECURITY/API/REVIEWER/SYNTHESIZER)
- **ReviewStatus**: Limited to 4 states (PENDING/PASSED/FAILED/RETRY)

### Business Rules
1. **Cache Invalidation**: CacheMetadata expires after 7 days (configurable)
2. **Commit Matching**: Cache invalidates if commit_sha changes
3. **File Size Limit**: FileInfo.content truncated at 100KB in scanner
4. **Tree Depth Limit**: Scanner stops at 10 directory levels
5. **Max Files**: Scanner processes max 500 files
6. **Retry Limits**: AgentOutput.retry_count ≤ max_retries (default 2)
7. **Review Iterations**: Max 2 review cycles per agent (if enabled)
8. **Token Budget**: Synthesizer respects max_context_tokens = 4000
9. **Parallel Workers**: Max 5 concurrent agents
10. **Timeout**: Default 3600s (1 hour) for Copilot calls

### Data Flow Validation
1. **Scanner** → FileInfo → ScanResult
2. **Expert Agents** (parallel/sequential) → AgentOutput[]
3. **Optional Review Loop** → ReviewResult + updated AgentOutput
4. **Synthesizer** → final_context (merged markdown)
5. **Orchestrator** → ProjectContext + file output
6. **Cache Layer** → CacheMetadata + JSON persistence

### Type Safety
- All entities use `@dataclass` with explicit type hints
- Optional fields clearly marked with `Optional[T]`
- Default values provided via `field(default_factory=...)`
- Enums prevent invalid state values
```