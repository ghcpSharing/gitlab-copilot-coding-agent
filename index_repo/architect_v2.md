# Project Understanding 架构设计 v2

## 1. 核心理念

**目标**：使用 Python + Copilot CLI 实现多 Agent 协作的项目分析流程，带有质量 Review 环节。

**关键约束**：
- 使用 Copilot CLI 作为 LLM 后端
- 纯 Python 实现流程编排
- 支持 Review + 重试机制

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Project Understanding Pipeline                           │
└─────────────────────────────────────────────────────────────────────────────┘

                         ┌─────────────────┐
                         │     Scanner     │  纯 Python
                         │  (文件扫描)     │  无 LLM 调用
                         └────────┬────────┘
                                  │
                                  ▼
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  TechStack      │    │  DataModel      │    │    Domain       │
│  Agent          │    │  Agent          │    │    Agent        │
│  (Copilot CLI)  │    │  (Copilot CLI)  │    │  (Copilot CLI)  │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Security       │    │     API         │    │                 │
│  Agent          │    │    Agent        │    │    (可扩展)     │
│  (Copilot CLI)  │    │  (Copilot CLI)  │    │                 │
└────────┬────────┘    └────────┬────────┘    └─────────────────┘
         │                      │
         └──────────┬───────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │      Reviewer       │  Copilot CLI
         │   (质量校验)        │  检查各 Agent 输出
         └──────────┬──────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
    ┌──────────┐        ┌──────────┐
    │  PASSED  │        │  FAILED  │
    └────┬─────┘        └────┬─────┘
         │                   │
         │                   ▼
         │            ┌──────────────┐
         │            │   重试对应    │
         │            │   Agent      │
         │            │  (最多3次)   │
         │            └──────────────┘
         │
         ▼
┌─────────────────────┐
│    Synthesizer      │  Copilot CLI
│   (合并压缩)        │  生成最终 context.md
└─────────────────────┘
```

---

## 3. Agent 设计

### 3.1 Agent 基类

```python
class BaseAgent:
    """Agent 基类 - 封装 Copilot CLI 调用"""
    
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.max_retries = 3
    
    def build_prompt(self, context: dict) -> str:
        """构建 Prompt（子类实现）"""
        raise NotImplementedError
    
    def parse_output(self, raw_output: str) -> dict:
        """解析输出（子类实现）"""
        raise NotImplementedError
    
    def run(self, context: dict) -> AgentOutput:
        """运行 Agent"""
        prompt = self.build_prompt(context)
        raw_output = self._call_copilot(prompt)
        result = self.parse_output(raw_output)
        return AgentOutput(agent=self.name, content=result, raw=raw_output)
    
    def _call_copilot(self, prompt: str) -> str:
        """调用 Copilot CLI"""
        # 方式 1: 使用 gh copilot suggest
        # 方式 2: 使用现有的 scripts/common.sh 中的函数
        # 方式 3: 直接调用 API（如果有）
        pass
```

### 3.2 专家 Agents

| Agent | 输入 | 输出 | Prompt 重点 |
|-------|------|------|------------|
| **TechStack** | package.json, Dockerfile, config files | 语言、框架、数据库、基础设施 | "只分析配置文件，不看业务代码" |
| **DataModel** | schema.prisma, models.py, SQL | 实体、字段、关系 | "列出核心 Model，忽略辅助字段" |
| **Domain** | README.md, src/ 结构 | 业务目标、核心流程 | "用自然语言总结，不列代码" |
| **Security** | .env*, auth/, middleware/ | 认证机制、敏感文件、RBAC | "不输出实际密钥值" |
| **API** | routes/, controllers/, openapi.yaml | 端点列表、请求/响应 | "按模块分组，标注 HTTP 方法" |

### 3.3 Reviewer Agent

```python
class ReviewerAgent(BaseAgent):
    """质量校验 Agent"""
    
    REVIEW_RULES = """
    请检查以下分析结果的质量：
    
    1. TechStack: 必须识别到编程语言
    2. DataModel: 如果有 schema 文件，必须提取到至少 1 个实体
    3. Domain: 业务描述不能少于 50 字
    4. Security: 不能包含实际的密钥/Token 值
    5. API: 端点格式必须正确 (METHOD /path)
    
    对每个 Agent 的输出给出：
    - status: PASSED / FAILED
    - issues: 具体问题列表
    - suggestions: 改进建议
    
    输出 JSON 格式。
    """
    
    def build_prompt(self, context: dict) -> str:
        return f"""
{self.REVIEW_RULES}

=== TechStack 输出 ===
{context.get('tech_stack', 'N/A')}

=== DataModel 输出 ===
{context.get('data_model', 'N/A')}

=== Domain 输出 ===
{context.get('domain', 'N/A')}

=== Security 输出 ===
{context.get('security', 'N/A')}

=== API 输出 ===
{context.get('api', 'N/A')}
"""
```

### 3.4 Synthesizer Agent

```python
class SynthesizerAgent(BaseAgent):
    """合并压缩 Agent"""
    
    SYNTH_PROMPT = """
    请将以下分析结果合并为一份简洁的项目上下文文档。
    
    要求：
    1. 使用 Markdown 格式
    2. 总长度不超过 2000 字
    3. 按重要性排序
    4. 突出关键信息，省略细节
    5. 适合作为代码审查的背景知识
    
    输出结构：
    # 项目上下文
    ## 1. 技术架构
    ## 2. 核心数据模型
    ## 3. 业务简介
    ## 4. 安全配置
    ## 5. API 概览
    """
```

---

## 4. 流程编排 (Orchestrator)

```python
class Orchestrator:
    """流程编排器"""
    
    def __init__(self):
        self.scanner = Scanner()
        self.agents = {
            'tech_stack': TechStackAgent(),
            'data_model': DataModelAgent(),
            'domain': DomainAgent(),
            'security': SecurityAgent(),
            'api': APIAgent(),
        }
        self.reviewer = ReviewerAgent()
        self.synthesizer = SynthesizerAgent()
    
    def run(self, workspace: Path, repo_id: str, branch: str) -> ProjectContext:
        """运行完整流程"""
        
        # Phase 1: 扫描
        print("=== Phase 1: Scanning ===")
        scan_result = self.scanner.scan(workspace)
        
        # Phase 2: 并行运行专家 Agents
        print("=== Phase 2: Expert Analysis ===")
        agent_outputs = {}
        for name, agent in self.agents.items():
            print(f"  Running {name}...")
            output = agent.run(scan_result)
            agent_outputs[name] = output
        
        # Phase 3: Review（带重试）
        print("=== Phase 3: Review ===")
        for attempt in range(3):
            review_result = self.reviewer.run(agent_outputs)
            
            failed_agents = [r for r in review_result if r.status == 'FAILED']
            if not failed_agents:
                print("  All agents passed review!")
                break
            
            print(f"  Retry attempt {attempt + 1} for: {[a.agent for a in failed_agents]}")
            for failed in failed_agents:
                # 重新运行失败的 Agent，附带 Review 反馈
                agent = self.agents[failed.agent]
                agent_outputs[failed.agent] = agent.run(
                    scan_result, 
                    feedback=failed.issues
                )
        
        # Phase 4: 合成
        print("=== Phase 4: Synthesize ===")
        final_context = self.synthesizer.run(agent_outputs)
        
        return ProjectContext(
            repo_id=repo_id,
            branch=branch,
            final_context=final_context,
            agent_outputs=agent_outputs,
            review_result=review_result,
        )
```

---

## 5. Copilot CLI 调用方式（方案 A：Bash 封装）

基于现有的 `scripts/common.sh`，封装 Copilot CLI 调用。

### 5.1 Bash 封装脚本

```bash
# scripts/copilot_agent.sh
#!/bin/bash
# Agent 调用封装 - 供 Python 调用

source "$(dirname "$0")/common.sh"

# 使用方法: ./copilot_agent.sh <agent_name> <prompt_file> [context_file...]
AGENT_NAME="$1"
PROMPT_FILE="$2"
shift 2
CONTEXT_FILES=("$@")

# 读取 prompt
PROMPT=$(cat "$PROMPT_FILE")

# 构建 context 参数
CONTEXT_ARGS=""
for f in "${CONTEXT_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        CONTEXT_ARGS="$CONTEXT_ARGS
---
File: $f
$(cat "$f")
---"
    fi
done

# 构建完整 prompt
FULL_PROMPT="$PROMPT

$CONTEXT_ARGS"

# 调用 Copilot（复用 common.sh 中的逻辑）
echo "$FULL_PROMPT" | gh copilot suggest -t code 2>/dev/null

# 或者使用你现有的调用方式
# call_copilot "$FULL_PROMPT"
```

### 5.2 Python 封装

```python
# src/project_understanding/copilot.py
"""Copilot CLI 调用封装"""

import subprocess
import tempfile
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class CopilotResponse:
    """Copilot 响应"""
    success: bool
    content: str
    error: Optional[str] = None
    execution_time_ms: int = 0


class CopilotClient:
    """Copilot CLI 客户端 - 通过 Bash 脚本调用"""
    
    def __init__(self, scripts_dir: Path = None):
        self.scripts_dir = scripts_dir or Path(__file__).parent.parent.parent.parent / "scripts"
        self.timeout = 120  # 2 分钟超时
    
    def call(
        self, 
        prompt: str, 
        context_files: list[Path] = None,
        agent_name: str = "default"
    ) -> CopilotResponse:
        """
        调用 Copilot CLI
        
        Args:
            prompt: 提示词
            context_files: 上下文文件列表
            agent_name: Agent 名称（用于日志）
        
        Returns:
            CopilotResponse: 响应结果
        """
        import time
        start_time = time.time()
        
        # 写入临时 prompt 文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(prompt)
            prompt_file = f.name
        
        try:
            # 构建命令
            cmd = [
                "bash", 
                str(self.scripts_dir / "copilot_agent.sh"),
                agent_name,
                prompt_file,
            ]
            
            # 添加上下文文件
            if context_files:
                cmd.extend([str(f) for f in context_files if f.exists()])
            
            # 执行
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, "NO_COLOR": "1"},  # 禁用颜色输出
            )
            
            execution_time = int((time.time() - start_time) * 1000)
            
            if result.returncode != 0:
                return CopilotResponse(
                    success=False,
                    content="",
                    error=result.stderr or "Unknown error",
                    execution_time_ms=execution_time,
                )
            
            return CopilotResponse(
                success=True,
                content=result.stdout.strip(),
                execution_time_ms=execution_time,
            )
            
        except subprocess.TimeoutExpired:
            return CopilotResponse(
                success=False,
                content="",
                error=f"Timeout after {self.timeout}s",
                execution_time_ms=self.timeout * 1000,
            )
        finally:
            # 清理临时文件
            Path(prompt_file).unlink(missing_ok=True)
    
    def call_with_retry(
        self,
        prompt: str,
        context_files: list[Path] = None,
        agent_name: str = "default",
        max_retries: int = 2,
    ) -> CopilotResponse:
        """带重试的调用"""
        last_error = None
        
        for attempt in range(max_retries + 1):
            response = self.call(prompt, context_files, agent_name)
            
            if response.success:
                return response
            
            last_error = response.error
            print(f"  Attempt {attempt + 1} failed: {last_error}")
        
        return CopilotResponse(
            success=False,
            content="",
            error=f"Failed after {max_retries + 1} attempts: {last_error}",
        )


# 全局单例
_client: Optional[CopilotClient] = None

def get_copilot_client() -> CopilotClient:
    """获取 Copilot 客户端单例"""
    global _client
    if _client is None:
        _client = CopilotClient()
    return _client
```

### 5.3 在 Agent 中使用

```python
# src/project_understanding/agents/base.py
from project_understanding.copilot import get_copilot_client, CopilotResponse

class BaseAgent:
    """Agent 基类"""
    
    def __init__(self, name: str):
        self.name = name
        self.client = get_copilot_client()
    
    def run(self, context: dict) -> AgentOutput:
        """运行 Agent"""
        # 1. 构建 prompt
        prompt = self.build_prompt(context)
        
        # 2. 获取上下文文件
        context_files = self.get_context_files(context)
        
        # 3. 调用 Copilot
        response = self.client.call_with_retry(
            prompt=prompt,
            context_files=context_files,
            agent_name=self.name,
        )
        
        # 4. 解析输出
        if not response.success:
            return AgentOutput(
                agent=self.name,
                success=False,
                error=response.error,
            )
        
        parsed = self.parse_output(response.content)
        return AgentOutput(
            agent=self.name,
            success=True,
            content=parsed,
            raw_response=response.content,
            execution_time_ms=response.execution_time_ms,
        )
    
    def build_prompt(self, context: dict) -> str:
        """构建 prompt（子类实现）"""
        raise NotImplementedError
    
    def get_context_files(self, context: dict) -> list[Path]:
        """获取需要传递给 Copilot 的上下文文件（子类实现）"""
        return []
    
    def parse_output(self, raw_output: str) -> dict:
        """解析输出（子类实现）"""
        return {"raw": raw_output}
```

---

## 6. 目录结构

```
index_repo/
├── architect_v2.md              # 本文档
├── pyproject.toml
├── requirements.txt
│
└── src/project_understanding/
    ├── __init__.py
    ├── models.py                # 数据模型
    ├── scanner.py               # 文件扫描（纯 Python）
    ├── copilot.py               # Copilot CLI 封装（方案 A）
    │
    ├── agents/                  # Agent 实现
    │   ├── __init__.py
    │   ├── base.py              # BaseAgent（使用 copilot.py）
    │   ├── tech_stack.py
    │   ├── data_model.py
    │   ├── domain.py
    │   ├── security.py
    │   ├── api.py
    │   ├── reviewer.py
    │   └── synthesizer.py
    │
    ├── prompts/                 # Prompt 模板
    │   ├── tech_stack.txt
    │   ├── data_model.txt
    │   ├── domain.txt
    │   ├── security.txt
    │   ├── api.txt
    │   ├── reviewer.txt
    │   └── synthesizer.txt
    │
    ├── orchestrator.py          # 流程编排
    ├── cache.py                 # 缓存管理
    └── cli.py                   # CLI 入口

scripts/
├── common.sh                    # 现有脚本（保持不变）
├── copilot_agent.sh             # 新增：Agent 调用封装
└── mr_review_orchestrated.sh    # 修改：集成 Phase 0
```

---

## 7. 执行流程示例

```bash
# GitLab CI 中调用
python -m project_understanding.cli analyze \
    --workspace . \
    --repo-id $CI_PROJECT_ID \
    --branch $CI_COMMIT_REF_NAME \
    --output .copilot/context.md

# 输出示例
=== Phase 1: Scanning ===
  Found 156 files, 3 languages detected: [TypeScript, Python, Shell]
  Key files: package.json, schema.prisma, README.md

=== Phase 2: Expert Analysis ===
  Running tech_stack... done (2.3s)
  Running data_model... done (3.1s)
  Running domain... done (2.8s)
  Running security... done (2.5s)
  Running api... done (3.2s)

=== Phase 3: Review ===
  Reviewing tech_stack... PASSED
  Reviewing data_model... PASSED
  Reviewing domain... FAILED (description too short)
  Retrying domain with feedback...
  Reviewing domain... PASSED
  Reviewing security... PASSED
  Reviewing api... PASSED

=== Phase 4: Synthesize ===
  Generating final context...
  Token count: 1,847 (within limit)

✅ Context saved to .copilot/context.md
```

---

## 8. 与现有流程集成

```bash
# mr_review_orchestrated.sh 修改

# === Phase 0: Project Understanding (新增) ===
if [[ "${ENABLE_PROJECT_CONTEXT:-true}" == "true" ]]; then
    echo "=== Phase 0: Project Understanding ==="
    
    python -m project_understanding.cli analyze \
        --workspace "${REPO_DIR}" \
        --repo-id "${CI_PROJECT_ID}" \
        --branch "${CI_COMMIT_REF_NAME}" \
        --output "${REPO_DIR}/.copilot/context.md" \
        --cache-dir "${CI_PROJECT_DIR}/.cache/copilot"
    
    if [[ -f "${REPO_DIR}/.copilot/context.md" ]]; then
        PROJECT_CONTEXT=$(cat "${REPO_DIR}/.copilot/context.md")
        export PROJECT_CONTEXT
    fi
fi

# === Phase 1: Planning (现有逻辑) ===
# Planner prompt 中注入 PROJECT_CONTEXT
```


---

## 9. 调用链路图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            完整调用链路                                      │
└─────────────────────────────────────────────────────────────────────────────┘

GitLab CI
    │
    ▼
mr_review_orchestrated.sh
    │
    ├── Phase 0: Project Understanding
    │       │
    │       ▼
    │   python -m project_understanding.cli
    │       │
    │       ▼
    │   orchestrator.py
    │       │
    │       ├── scanner.py (纯 Python)
    │       │
    │       ├── agents/*.py
    │       │       │
    │       │       ▼
    │       │   copilot.py
    │       │       │
    │       │       ▼
    │       │   subprocess.run()
    │       │       │
    │       │       ▼
    │       │   scripts/copilot_agent.sh
    │       │       │
    │       │       ▼
    │       │   source common.sh
    │       │       │
    │       │       ▼
    │       │   gh copilot suggest ...
    │       │
    │       └── 输出: .copilot/context.md
    │
    ├── Phase 1: Planning (现有)
    │       └── 使用 PROJECT_CONTEXT
    │
    ├── Phase 2: Execution (现有)
    │
    └── Phase 3: Summary (现有)
```

