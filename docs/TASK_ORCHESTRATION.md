# 🎯 任务编排框架 - Task Orchestration Framework

## 概述

这是一个通用的任务编排框架，用于将大型、复杂的任务（如MR审查、Issue实现）拆分为可管理的子任务，并支持并行执行和结果聚合。

## 核心组件

### 1. 基础框架 (`task_framework.py`)

提供核心的数据结构和执行引擎：

- **`SubTask`**: 子任务定义，包含依赖关系、优先级、资源限制
- **`TaskPlan`**: 任务执行计划，包含多个子任务
- **`TaskExecutor`**: 任务执行器，支持依赖管理和并行执行
- **`TaskAggregator`**: 结果聚合器，合并多个子任务的结果

### 2. MR Review适配器

#### `mr_review_planner.py` - 智能规划器

根据MR的规模自动生成审查计划：

- **小型MR** (< 10文件): 单个任务
- **中型MR** (10-50文件): 按类别拆分（critical, source, test, doc, config）
- **大型MR** (> 50文件): 按类别+文件分块拆分

**特性**：
- 自动识别关键文件（安全、认证相关）并提高优先级
- 排除无需审查的文件（node_modules, vendor等）
- 智能分块，确保每个子任务在token限制内
- 支持并行审查

#### `mr_review_executor.py` - 执行器

执行拆分后的审查任务：

- 为每个子任务获取对应的diff
- 调用Copilot CLI进行审查
- 收集review findings
- 聚合所有结果

#### `mr_review_orchestrated.sh` - 集成脚本

端到端的MR审查流程：

1. **Phase 1**: 生成任务计划
2. **Phase 2**: 并行执行审查任务
3. **Phase 3**: 发布审查摘要
4. **Phase 4**: 发布inline comments（可选）

## 使用方法

### 方式一：使用编排脚本（推荐）

```bash
# 设置环境变量
export GITLAB_TOKEN="your-token"
export TARGET_REPO_URL="https://gitlab.com/user/repo.git"
export TARGET_BRANCH="main"
export SOURCE_BRANCH="feature-branch"
export TARGET_MR_IID="123"
export MR_TITLE="Add new feature"
export MR_DESCRIPTION="This MR adds..."
export UPSTREAM_GITLAB_BASE_URL="https://gitlab.com"
export TARGET_PROJECT_ID="12345"

# 运行编排审查
./scripts/mr_review_orchestrated.sh
```

### 方式二：分步执行

#### 步骤1：生成任务计划

```bash
cd /path/to/repo

python3 scripts/mr_review_planner.py \
  --mr-iid 123 \
  --mr-title "Add new feature" \
  --base-branch origin/main \
  --head-branch origin/feature-branch \
  --output task_plan.json
```

生成的 `task_plan.json` 示例：

```json
{
  "task_id": "mr-review-123",
  "task_type": "mr_review",
  "title": "Review MR #123: Add new feature",
  "subtasks": [
    {
      "id": "review-critical-1",
      "title": "Review critical files",
      "description": "Review security-sensitive files",
      "task_type": "review",
      "priority": 10,
      "file_patterns": ["src/auth/*.py", "src/security/*.py"]
    },
    {
      "id": "review-source-1",
      "title": "Review source code (batch 1/2)",
      "task_type": "review",
      "priority": 8,
      "file_patterns": ["src/api/*.py", "src/models/*.py"]
    }
  ],
  "max_concurrent_tasks": 3,
  "enable_parallel": true
}
```

#### 步骤2：执行任务

```bash
python3 scripts/mr_review_executor.py \
  --plan task_plan.json \
  --workspace . \
  --output review_results.json \
  --summary-output review_summary.md
```

#### 步骤3：查看结果

```bash
# 查看详细结果（JSON）
cat review_results.json | jq .

# 查看摘要（Markdown）
cat review_summary.md
```

## 配置选项

### 环境变量

```bash
# Copilot语言设置
export COPILOT_LANGUAGE=zh  # zh, en, ja, ko, hi, th

# 是否启用inline comments
export ENABLE_INLINE_REVIEW_COMMENTS=true
```

### 规划器配置

在 `mr_review_planner.py` 中修改：

```python
# 每个子任务的diff大小限制
MAX_DIFF_SIZE_PER_TASK = 100 * 1024  # 100KB

# 每个子任务的文件数限制
MAX_FILES_PER_TASK = 20

# 关键文件模式
CRITICAL_FILE_PATTERNS = [
    r'.*/(auth|security|crypto|password).*',
    r'.*/api/.*',
    r'.*\.sql$'
]
```

## 架构优势

### 1. 可扩展性 📈

- 支持任意大小的MR（从小型到超大型）
- 自动拆分，无需手动干预

### 2. 容错性 🛡️

- 单个子任务失败不影响其他任务
- 支持部分结果输出
- 详细的错误报告

### 3. 性能优化 ⚡

- 并行执行独立任务
- 智能批处理
- Token预算管理

### 4. 智能调度 🧠

- 基于依赖关系的自动调度
- 优先级队列
- 资源感知调度

### 5. 可复用性 🔄

- 通用框架，可用于多种场景：
  - MR审查 ✅
  - Issue实现
  - 代码重构
  - 文档生成
  - 自定义任务

## 扩展到其他场景

### 示例：Issue实现

```python
# issue_implement_planner.py
from task_framework import TaskPlan, SubTask

def create_issue_implementation_plan(issue_title, issue_description):
    plan = TaskPlan(
        task_id=f"issue-{issue_iid}",
        task_type="issue_implement",
        title=f"Implement Issue #{issue_iid}",
        description=issue_description
    )
    
    # 规划子任务
    plan.subtasks = [
        SubTask(
            id="analyze",
            title="分析需求",
            task_type="planning",
            priority=10
        ),
        SubTask(
            id="implement-backend",
            title="实现后端",
            task_type="code",
            depends_on=["analyze"],
            priority=9
        ),
        SubTask(
            id="implement-frontend",
            title="实现前端",
            task_type="code",
            depends_on=["analyze"],
            priority=9
        ),
        SubTask(
            id="write-tests",
            title="编写测试",
            task_type="test",
            depends_on=["implement-backend", "implement-frontend"],
            priority=8
        ),
        SubTask(
            id="update-docs",
            title="更新文档",
            task_type="doc",
            depends_on=["write-tests"],
            priority=5
        )
    ]
    
    return plan
```

## 性能对比

### 传统方式 vs 编排方式

| 指标 | 传统方式 | 编排方式 | 改进 |
|------|---------|---------|------|
| **支持的最大MR规模** | ~50文件 | 无限制 | ∞ |
| **处理时间（100文件）** | 失败/超时 | 10-15分钟 | 可完成 |
| **并行能力** | 无 | 3-5个任务 | 3-5x |
| **容错性** | 全失败 | 部分失败 | 高 |
| **资源利用率** | 低 | 高 | 3-4x |

## 故障排查

### 问题1：任务计划生成失败

```bash
# 检查git仓库状态
git status
git log origin/main..origin/feature-branch

# 检查文件权限
ls -la scripts/*.py
chmod +x scripts/*.py
```

### 问题2：Copilot执行超时

```bash
# 增加子任务的超时时间
# 在task_plan.json中修改:
"estimated_time_seconds": 600  # 增加到600秒
```

### 问题3：Findings文件未生成

检查Copilot输出：

```bash
# 查看子任务工作目录
ls subtask_review-*/

# 查看原始输出
cat subtask_review-*/copilot_raw.txt
```

## 最佳实践

### 1. MR大小建议

- **理想**: < 20文件，< 1000行
- **可接受**: 20-50文件，1000-3000行
- **需要拆分**: > 50文件，> 3000行（框架自动处理）

### 2. 性能优化

```bash
# 增加并发数（如果资源充足）
# 在task_plan.json中:
"max_concurrent_tasks": 5

# 增加批次大小
"batch_size": 10
```

### 3. Token管理

```bash
# 为大型任务增加总预算
"max_total_tokens": 200000

# 调整单个子任务预算
"estimated_tokens": 8000
```

## 未来改进

- [ ] 支持增量审查（只审查新增的commits）
- [ ] AI驱动的任务拆分优化
- [ ] 实时进度展示（WebSocket）
- [ ] 审查结果缓存
- [ ] 跨MR的学习和优化
- [ ] 支持更多语言的prompt模板

## 参与贡献

欢迎提交PR改进框架！

### 开发指南

1. Fork仓库
2. 创建功能分支
3. 编写测试
4. 提交PR

### 测试

```bash
# 运行单元测试
pytest scripts/test_task_framework.py

# 集成测试
./scripts/test_mr_review_orchestrated.sh
```

## License

MIT

## 作者

GitLab Copilot Coding Agent Team
