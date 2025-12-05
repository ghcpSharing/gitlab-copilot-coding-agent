# Project Understanding Module

基于多 Agent 协作的项目分析工具，为 MR Code Review 提供项目上下文。

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                         Orchestrator                            │
│  ┌──────────┐   ┌──────────────────────────┐   ┌────────────┐  │
│  │ Scanner  │ → │     Expert Agents        │ → │ Synthesizer│  │
│  │ (Python) │   │ (Tech/Data/Domain/Sec/API)│   │            │  │
│  └──────────┘   └──────────────────────────┘   └────────────┘  │
│                           ↓                                     │
│                    ┌──────────┐                                 │
│                    │ Reviewer │ ← 质量校验 + 重试               │
│                    └──────────┘                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
                    .copilot/context.md
```

## 快速开始

### 本地运行

```bash
# 进入项目目录
cd /path/to/your/project

# 运行分析（使用默认配置）
python -m project_understanding.cli

# 或指定项目路径
python -m project_understanding.cli /path/to/target/project
```

### 命令行参数

```bash
python -m project_understanding.cli [OPTIONS] [WORKSPACE]

参数:
  WORKSPACE              项目目录路径（默认: 当前目录）

选项:
  -o, --output-dir DIR   输出目录（默认: .copilot）
  --output-file FILE     输出文件名（默认: context.md）
  --no-review            禁用 Reviewer 质量校验（更快）
  --no-cache             禁用缓存
  --max-tokens NUM       最大输出 token 数（默认: 4000）
  --timeout SEC          Copilot 调用超时（默认: 120）
  --model MODEL          模型名称（默认: claude-sonnet-4）
  -v, --verbose          详细输出
  --repo-id ID           GitLab 仓库 ID
  --branch NAME          分支名
  --commit SHA           Commit SHA
  -h, --help             显示帮助
```

### 示例

```bash
# 快速分析（跳过 Review）
python -m project_understanding.cli --no-review

# 详细输出
python -m project_understanding.cli -v

# 自定义输出位置
python -m project_understanding.cli -o .analysis --output-file project_context.md

# 指定 GitLab 信息
python -m project_understanding.cli --repo-id 123 --branch main --commit abc123
```

## GitLab CI 集成

### 方式一：在 MR Review 流程前调用

修改 `.gitlab-ci.yml`：

```yaml
variables:
  # Copilot 相关配置
  COPILOT_TIMEOUT: "120"
  COPILOT_MODEL: "claude-sonnet-4"

stages:
  - analyze
  - review

# 项目分析阶段
project-analysis:
  stage: analyze
  image: your-copilot-image:latest  # 包含 Python 和 gh copilot 的镜像
  script:
    # 运行项目分析
    - python -m project_understanding.cli --no-cache -v
    # 输出生成的上下文
    - cat .copilot/context.md
  artifacts:
    paths:
      - .copilot/
    expire_in: 1 hour
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# MR Review 阶段（使用分析结果）
mr-review:
  stage: review
  image: your-copilot-image:latest
  needs:
    - project-analysis
  script:
    # 设置项目上下文环境变量
    - export PROJECT_CONTEXT=$(cat .copilot/context.md)
    # 执行 MR Review
    - ./scripts/mr_review_orchestrated.sh
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### 方式二：集成到现有 Review 脚本

修改 `scripts/mr_review_orchestrated.sh`：

```bash
#!/usr/bin/env bash

# ... 现有代码 ...

# Phase 0: 项目理解（新增）
echo "=== Phase 0: Project Understanding ==="
python -m project_understanding.cli \
    --repo-id "${CI_PROJECT_ID}" \
    --branch "${CI_COMMIT_REF_NAME}" \
    --commit "${CI_COMMIT_SHA}" \
    --no-review \
    -v

# 读取生成的上下文
if [[ -f ".copilot/context.md" ]]; then
    export PROJECT_CONTEXT=$(cat .copilot/context.md)
    echo "Project context loaded (${#PROJECT_CONTEXT} chars)"
else
    echo "Warning: Project context not generated"
    export PROJECT_CONTEXT=""
fi

# Phase 1: Planning（现有）
echo "=== Phase 1: Planning ==="
# ... 现有 planning 代码，可以使用 $PROJECT_CONTEXT ...
```

### 方式三：作为 CI 脚本单独调用

创建 `scripts/project_analysis.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# 配置
OUTPUT_DIR="${PROJECT_CONTEXT_DIR:-.copilot}"
OUTPUT_FILE="${PROJECT_CONTEXT_FILE:-context.md}"

echo "=== Project Understanding ==="
echo "Workspace: ${CI_PROJECT_DIR:-$(pwd)}"
echo "Output: ${OUTPUT_DIR}/${OUTPUT_FILE}"

# 运行分析
python -m project_understanding.cli \
    --output-dir "${OUTPUT_DIR}" \
    --output-file "${OUTPUT_FILE}" \
    --repo-id "${CI_PROJECT_ID:-}" \
    --branch "${CI_COMMIT_REF_NAME:-}" \
    --commit "${CI_COMMIT_SHA:-}" \
    ${PROJECT_ANALYSIS_FLAGS:-}

# 验证输出
if [[ -f "${OUTPUT_DIR}/${OUTPUT_FILE}" ]]; then
    echo "✓ Context generated successfully"
    echo "  Size: $(wc -c < "${OUTPUT_DIR}/${OUTPUT_FILE}") bytes"
    echo "  Lines: $(wc -l < "${OUTPUT_DIR}/${OUTPUT_FILE}")"
else
    echo "✗ Context generation failed"
    exit 1
fi
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `COPILOT_TIMEOUT` | Copilot 调用超时（秒） | 120 |
| `COPILOT_MODEL` | 使用的模型 | claude-sonnet-4 |
| `CI_PROJECT_ID` | GitLab 项目 ID | - |
| `CI_COMMIT_REF_NAME` | 分支名 | - |
| `CI_COMMIT_SHA` | Commit SHA | - |

## 输出文件

### `.copilot/context.md`

主要输出文件，包含压缩后的项目上下文：

```markdown
# Project Context

## Overview
[项目简介]

## Tech Stack
- Languages: Python, TypeScript
- Frameworks: FastAPI, React
- Key Dependencies: ...

## Architecture
[架构模式和层次]

## Data Model
[核心数据模型]

## API Structure
[API 端点和模式]

## Security
[认证授权机制]

## Code Review Focus Areas
[审查重点区域]
```

### `.copilot/context_details.md`

详细分析结果，包含各 Agent 的原始输出。

### `.copilot/cache_metadata.json`

缓存元数据，用于增量更新。

## Agent 说明

| Agent | 职责 | 分析内容 |
|-------|------|----------|
| **Scanner** | 扫描项目 | 文件结构、关键文件、语言检测 |
| **TechStack** | 技术栈 | 语言、框架、构建工具、依赖 |
| **DataModel** | 数据模型 | 数据库、ORM、DTO、验证规则 |
| **Domain** | 业务领域 | 核心概念、业务规则、用例 |
| **Security** | 安全分析 | 认证、授权、数据保护 |
| **API** | API 结构 | 端点、请求响应、版本控制 |
| **Reviewer** | 质量校验 | 检查输出完整性和准确性 |
| **Synthesizer** | 合并压缩 | 去重、整合、压缩到 token 限制 |

## 依赖要求

- Python 3.10+
- `gh` CLI 已安装并配置
- GitHub Copilot 权限

## 目录结构

```
project_understanding/
├── __init__.py          # 模块入口
├── cli.py               # CLI 入口点
├── copilot.py           # Copilot 客户端封装
├── models.py            # 数据模型
├── orchestrator.py      # 流程编排器
├── scanner.py           # 文件扫描器
├── README.md            # 本文档
└── agents/
    ├── __init__.py      # Agent 基类
    ├── api.py           # API Agent
    ├── data_model.py    # DataModel Agent
    ├── domain.py        # Domain Agent
    ├── reviewer.py      # Reviewer Agent
    ├── security.py      # Security Agent
    ├── synthesizer.py   # Synthesizer Agent
    └── tech_stack.py    # TechStack Agent
```

## 性能建议

1. **首次运行较慢**：需要调用多个 Agent，约 2-5 分钟
2. **使用缓存**：相同 commit 不会重复分析
3. **跳过 Review**：`--no-review` 可节省约 30% 时间
4. **减少 token**：`--max-tokens 2000` 生成更简洁的上下文

## 故障排除

### 问题：Copilot 调用超时

```bash
# 增加超时时间
python -m project_understanding.cli --timeout 180
```

### 问题：输出过长

```bash
# 减少 token 限制
python -m project_understanding.cli --max-tokens 2000
```

### 问题：某个 Agent 失败

启用详细日志查看具体错误：

```bash
python -m project_understanding.cli -v 2>&1 | tee analysis.log
```

### 问题：缓存未生效

```bash
# 强制重新分析
python -m project_understanding.cli --no-cache
```
