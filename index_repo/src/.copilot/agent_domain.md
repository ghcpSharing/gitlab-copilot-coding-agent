# Domain Analysis

- Status: ✓ Success
- Retries: 0

---

I'll analyze the project's business domain by examining the codebase structure and documentation.

✔ List directory project_understanding
   └ 18 files found

✔ Read project_understanding/models.py
   └ 111 lines read

✔ Read project_understanding/scanner.py
   └ 250 lines read

✔ Read project_understanding/orchestrator.py
   └ 437 lines read

✔ List directory project_understanding/agents
   └ 15 files found

✔ Read project_understanding/agents/domain.py
   └ 85 lines read

✔ Read project_understanding/copilot.py
   └ 265 lines read

✔ Read project_understanding/agents/__init__.py
   └ 259 lines read

✔ Read project_understanding/agents/reviewer.py
   └ 176 lines read

✔ Read project_understanding/agents/synthesizer.py
   └ 201 lines read

✔ Glob "**/prompts/project_understanding/*.txt"
   └ No matches found

Now I'll create the comprehensive business domain analysis document:

```markdown
## Core Domain Concepts

### Project Analysis System
- **Workspace**: A source code repository being analyzed, represented as a file system path with git metadata (repo_id, branch, commit_sha)
- **Agent**: An autonomous analytical unit with a specific expert role (Tech Stack, Data Model, Domain, Security, API, Reviewer, Synthesizer) that produces structured analysis outputs
- **Scan Result**: A structured representation of project structure including file tree, key files by category (config, schema, doc, auth, api), detected languages, and file count
- **Agent Output**: The deliverable from an agent containing analyzed content, success status, error information, and retry count
- **Project Context**: The final synthesized artifact containing all expert analyses, review results, token count, and metadata for downstream consumption (MR Review)
- **Review Result**: Quality assessment of an agent output with pass/fail status, identified issues, and improvement suggestions

### File Categorization
- **Key Files**: Critical project files grouped by business purpose (config, schema, documentation, auth, api) with size-limited content snapshots
- **File Tree**: Hierarchical representation of workspace structure with ignored directories filtered out (node_modules, .git, build artifacts)

### Quality Control
- **Review Status**: Tri-state validation result (PENDING, PASSED, FAILED) with confidence scoring
- **Retry Mechanism**: Feedback-driven refinement loop where agents improve outputs based on reviewer suggestions (max 2 iterations)

## Business Rules

### Scanning Constraints
- **File Limit**: Maximum 500 files scanned to prevent performance degradation and excessive token consumption
- **Depth Limit**: Directory traversal capped at 10 levels to avoid deep nesting issues
- **Size Limit**: Key file content limited to 100KB per file to manage memory and processing time
- **Ignore Patterns**: Standard development artifacts excluded (build outputs, dependencies, IDE configs, lock files) to focus on source code

### Agent Execution Rules
- **Parallel Execution**: Expert agents (Tech Stack, Data Model, Domain, Security, API) run concurrently by default using ThreadPoolExecutor (max 5 workers) for time efficiency
- **Sequential Fallback**: Can be disabled via configuration for debugging or resource-constrained environments
- **Timeout Policy**: Each Copilot call times out after 1 hour (3600s) by default to prevent indefinite hangs
- **Retry Strategy**: Failed calls retry up to 2 times; timeout errors trigger retry, but command-not-found errors (exit 127) terminate immediately

### Review Policy
- **Default Disabled**: Review mechanism disabled by default (enable_review=False) due to parsing instability in early versions
- **Pass Threshold**: 70% confidence score required for review to pass (self.pass_threshold = 0.7)
- **Graceful Degradation**: If review call fails or response cannot be parsed, system defaults to PASSED to avoid blocking pipeline
- **Feedback Loop**: Failed reviews trigger agent re-execution with reviewer suggestions appended to prompt (max 2 iterations)

### Caching Strategy
- **Cache Invalidation**: Cache valid only for same commit_sha; branch/commit change invalidates cache
- **Expiration**: Cache expires after 7 days (cache_max_age_days=7) to prevent stale context
- **Cache Artifacts**: Stores final context.md and metadata.json in .copilot/ directory
- **Token Budget**: Final synthesized context target is 1500-2000 words (approx 4000 tokens) for optimal MR review consumption

### Output Persistence
- **Incremental Saves**: Each agent output written immediately to individual file (agent_{role}.md) for crash recovery
- **Atomic Writes**: Final context.md only written after successful synthesis
- **Dual Output**: Both compressed context.md and detailed context_details.md generated for different use cases

## Main Use Cases

### UC1: One-Shot Project Analysis
- **Actors**: DevOps Engineer, GitLab CI Pipeline
- **Trigger**: Manual CLI invocation (`python -m project_understanding.cli`) or CI job start
- **Flow**:
  1. Scanner discovers project structure and key files
  2. Expert agents analyze in parallel (tech stack, data model, domain, security, API)
  3. Synthesizer compresses all outputs into unified context
  4. System writes output to .copilot/context.md
- **Outcome**: Reusable project context document ready for MR review consumption
- **Success Criteria**: Analysis completes within 2-5 minutes, context under 4000 tokens

### UC2: Cached Context Retrieval
- **Actors**: CI Pipeline (repeated runs on same commit)
- **Trigger**: CLI invocation with --enable-cache on unchanged commit
- **Flow**:
  1. System checks .copilot/cache_metadata.json
  2. Validates commit_sha matches and age < 7 days
  3. Returns cached context.md without re-analysis
- **Outcome**: Sub-second context retrieval, pipeline time savings
- **Success Criteria**: Cache hit rate > 80% for same-commit reviews

### UC3: Quality-Assured Analysis (Review Loop)
- **Actors**: Project Understanding Orchestrator, Expert Agents, Reviewer Agent
- **Trigger**: CLI invoked with --review flag
- **Flow**:
  1. Expert agent produces initial analysis
  2. Reviewer agent evaluates completeness, accuracy, clarity
  3. If FAILED and iterations < 2: agent retries with feedback
  4. If PASSED or max iterations: output accepted
- **Outcome**: Higher quality analysis at cost of 2-3x execution time
- **Success Criteria**: 90%+ first-pass approval rate to minimize retries

### UC4: GitLab CI Integration
- **Actors**: GitLab CI, MR Review Script, Copilot CLI
- **Trigger**: Merge request event
- **Flow**:
  1. CI job runs project analysis in 'analyze' stage
  2. Outputs stored as pipeline artifacts (.copilot/)
  3. MR review job (stage: review) consumes artifact
  4. Context injected into MR review prompt as PROJECT_CONTEXT env var
- **Outcome**: MR reviewers receive enriched context without manual setup
- **Success Criteria**: Zero-config operation, < 5 min analysis time

### UC5: Fallback Synthesis
- **Actors**: Synthesizer Agent
- **Trigger**: Copilot call fails during synthesis (timeout, API error)
- **Flow**:
  1. Synthesizer detects response.success == False
  2. Activates _fallback_synthesis() method
  3. Simple concatenation of first 500 chars from each agent output
  4. Appends "(Fallback)" marker to output
- **Outcome**: Degraded but functional context delivered
- **Success Criteria**: Never return empty context; partial info better than none

## Workflows

### W1: Agent Execution State Machine
**States**: IDLE → ANALYZING → (REVIEWING) → COMPLETE / FAILED
**Transitions**:
- IDLE → ANALYZING: analyze() or analyze_with_review() called
- ANALYZING → REVIEWING: enable_review=True and output.success=True
- REVIEWING → ANALYZING: review.status=FAILED and retry_count < max_iterations
- REVIEWING → COMPLETE: review.status=PASSED
- ANALYZING → COMPLETE: enable_review=False and output.success=True
- ANALYZING → FAILED: output.success=False and retry_count >= max_retries
- REVIEWING → COMPLETE: retry_count >= max_review_iterations (graceful exit)

**Invariants**:
- retry_count increments on each re-execution
- FAILED state terminal (no automatic recovery)
- COMPLETE state immutable (output written to disk)

### W2: Orchestrator Execution Pipeline
**Phases**:
1. **Cache Check** (optional): Load cached context if commit_sha matches and not expired
2. **Scan**: Discover workspace structure (file tree, key files, languages)
3. **Expert Analysis**: Execute 5 agents in parallel or sequence
4. **Synthesis**: Merge and compress outputs into final context
5. **Output**: Write context.md, context_details.md, agent_{role}.md files
6. **Cache Save**: Store metadata.json for future lookups

**Parallel Execution Strategy**:
- ThreadPoolExecutor with max_workers=5
- Futures submitted for all 5 expert agents
- Results collected via as_completed() (non-deterministic order)
- Each future wrapped in try/except for fault isolation
- Failed agents return error AgentOutput but don't block others

**Sequential Execution Strategy**:
- For-loop over expert_agents list (deterministic order)
- Each agent blocks until completion
- Failed agent logs warning but doesn't stop pipeline

### W3: Copilot Call Retry Flow
**Entry**: call_with_retry() invoked
**Loop** (max_retries + 1 iterations):
1. Execute subprocess.run(['copilot', '--allow-all-tools'])
2. **If success (exit 0)**: Return immediately with content
3. **If timeout (exit 124)**: Log warning, continue loop
4. **If not-found (exit 127)**: Break loop immediately (no retry)
5. **Other errors**: Log warning, continue loop

**Exit**: Return last_response (success or failure)

**Error Handling**:
- FileNotFoundError: "copilot command not found" (exit 127)
- TimeoutExpired: "Timeout after Ns" (exit 124)
- Generic Exception: str(e) as error message (exit 1)

### W4: Review Result Parsing State Machine
**States**: RAW_RESPONSE → JSON_SEARCH → PARSED / FALLBACK_DEFAULT
**Transitions**:
- RAW_RESPONSE → JSON_SEARCH: Start regex pattern matching
- JSON_SEARCH → PARSED: Valid JSON found and confidence threshold met
- JSON_SEARCH → JSON_SEARCH: Pattern failed, try next regex
- JSON_SEARCH → FALLBACK_DEFAULT: All patterns exhausted
- FALLBACK_DEFAULT: Return ReviewResult(status=PASSED) to avoid blocking

**Patterns Tried** (in order):
1. `r'```json\s*(.*?)\s*```'` (fenced code block with json tag)
2. `r'```\s*(.*?)\s*```'` (fenced code block without tag)
3. `r'\{[^{}]*"status"[^{}]*\}'` (raw JSON object matching)

**Confidence Logic**:
- PASSED + confidence >= 0.7 → ReviewStatus.PASSED
- FAILED + confidence < 0.5 → ReviewStatus.FAILED
- Ambiguous (0.5-0.7 or mismatched) → ReviewStatus.PASSED (permissive default)

---

### Domain-Driven Design Patterns Observed

**Bounded Context**: Project Understanding module is isolated subdomain within larger GitLab Copilot system

**Entities**: ProjectContext, AgentOutput, ScanResult (identity tracked by repo_id + commit_sha)

**Value Objects**: FileInfo, ReviewResult, CopilotResponse (immutable, equality by value)

**Aggregates**: ProjectContext as root aggregate containing all agent outputs and metadata

**Domain Services**: Scanner (stateless project discovery), Orchestrator (workflow coordination), CopilotClient (infrastructure adapter)

**Repositories**: Cache storage (file-based) with metadata validation (implicit repository pattern)

**Factories**: Agent initialization in Orchestrator._init_agents() (factory method pattern)

**Anti-Corruption Layer**: CopilotClient wraps subprocess calls, isolating domain from CLI interface details
```

This analysis reveals a well-structured domain with clear separation of concerns, robust error handling, and pragmatic trade-offs (e.g., review disabled by default, fallback strategies). The system follows multi-agent orchestration patterns with parallel execution, quality gates, and caching for performance optimization.