# 技术架构 - 多代理编排分支

---

## 概述

此分支 (`multi-agents`) 为 GitLab Copilot 编码代理引入了复杂的**多阶段编排工作流**。它代表了从基础单次执行实现到生产就绪、企业级系统的重大演进。

---

## 核心技术

### 1. 多阶段编排执行

系统现在不再使用单次 Copilot CLI 调用，而是将复杂任务分解为多个阶段：

```
┌─────────────────────────────────────────────────────────────────┐
│                      编排工作流                                   │
├─────────────────────────────────────────────────────────────────┤
│  阶段 1: 确认                                                    │
│     └── 向 Issue/MR 发布确认评论                                 │
│                                                                 │
│  阶段 2: 仓库克隆                                                │
│     └── 使用认证克隆目标仓库                                      │
│                                                                 │
│  阶段 3: 项目理解上下文                                           │
│     ├── 从 Azure Blob 缓存加载（如可用）                          │
│     └── 或运行完整项目分析                                        │
│                                                                 │
│  阶段 4: 任务规划                                                │
│     ├── 分析 issue/请求复杂度                                     │
│     ├── 分解为子任务                                              │
│     └── 确定执行顺序（依赖关系）                                   │
│                                                                 │
│  阶段 5: 创建 MR（如需要）                                        │
│     └── 创建分支和空 MR 作为占位符                                 │
│                                                                 │
│  阶段 6: 执行子任务                                               │
│     ├── 使用隔离的 Copilot 会话运行每个子任务                       │
│     ├── 复杂任务使用 3 倍超时乘数                                  │
│     └── 收集结果和产物                                            │
│                                                                 │
│  阶段 7: 提交 & 推送                                              │
│     └── 暂存、提交并推送所有变更                                   │
│                                                                 │
│  阶段 8: 上传更新后的上下文                                        │
│     └── 上传到 Azure Blob 并进行去重                              │
│                                                                 │
│  阶段 9: 完成                                                    │
│     └── 更新 MR 描述，发布完成评论                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2. Git 风格的项目理解缓存

受 Git 内容寻址存储启发的复杂缓存系统：

```
Azure Blob 存储结构:
code/
├── {project_id}/
│   ├── main/
│   │   ├── {commit1}/metadata.json
│   │   ├── {commit2}/metadata.json
│   │   └── latest.json
│   ├── feature-x/
│   │   └── {commit3}/metadata.json
│   └── _base_branches.json
└── objects/
    ├── sha256-abc123... (共享内容)
    └── sha256-def456...
```

**5 级缓存查找策略：**

| 级别 | 策略 | 描述 |
|------|------|------|
| 1 | 精确匹配 | 当前分支 + 当前 commit |
| 2 | 父 Commit | 从父 commit 增量更新 |
| 3 | 分支最新 | 同分支的最新 commit |
| 4 | 跨分支 | 从基础分支复用（如 main） |
| 5 | 完整分析 | 无缓存，运行完整分析 |

**内容去重：**
- 文件按内容哈希存储（SHA-256）
- 跨 commit/分支的相同内容只存储一次
- 元数据引用共享内容对象
- 新分支可以引用父分支的上下文

### 3. 智能任务规划

`issue_planner.py` 和 `mr_review_planner.py` 分析请求并生成执行计划：

```json
{
  "issue_id": "123",
  "complexity": {
    "scope": "medium",
    "estimated_files": 5
  },
  "subtasks": [
    {
      "id": "task_1",
      "task_type": "analysis",
      "title": "需求分析",
      "description": "...",
      "estimated_time_seconds": 300,
      "priority": 1,
      "dependencies": []
    },
    {
      "id": "task_2", 
      "task_type": "implementation",
      "title": "核心实现",
      "dependencies": ["task_1"],
      "priority": 2
    }
  ],
  "max_concurrent_tasks": 1
}
```

### 4. Webhook 事件路由

Flask webhook 服务智能路由不同的 GitLab 事件：

```python
事件类型:
├── Issue Hook
│   └── action: "update" + assignee 包含 copilot
│       → TRIGGER_TYPE: "issue_assignee"
│
├── Note Hook (Issue)
│   └── note 包含 "@copilot"
│       → TRIGGER_TYPE: "issue_note"
│
├── Note Hook (MR)
│   └── note 包含 "@copilot"
│       ├── 有审查关键词 (review, check, 审查...)
│       │   → TRIGGER_TYPE: "mr_review_note"
│       └── 有实现关键词 (fix, apply...)
│           → TRIGGER_TYPE: "mr_note"
│
└── Merge Request Hook
    └── action: "update" + reviewer 包含 copilot
        → TRIGGER_TYPE: "mr_reviewer"
```

---

## 事件工作流详解

### 事件 1: Issue 指派 (`issue_assignee`)

**触发**: 将 Copilot 用户指派给 GitLab Issue

**脚本**: `scripts/issue_workflow_orchestrated.sh`

**流程**:
```
1. 向 issue 发布确认评论
2. 克隆仓库到新分支
3. 加载/生成项目理解上下文
4. 规划器分析 issue → 生成子任务计划
5. 创建空 MR 作为占位符
6. 执行器顺序运行子任务
   - 每个子任务: 使用隔离提示词的 Copilot CLI
   - 超时: estimated_time × 3
7. 提交并推送所有变更
8. 上传更新后的上下文到 Azure Blob
9. 使用执行结果更新 MR 描述
10. 向 issue 发布完成评论
```

**关键变量**:
- `TARGET_ISSUE_IID`: Issue 编号
- `ISSUE_TITLE`, `ISSUE_DESCRIPTION`: Issue 内容
- `NEW_BRANCH_NAME`: 自动生成的分支名称

---

### 事件 2: Issue 评论 (`issue_note`)

**触发**: 在 Issue 中评论 `@copilot <指令>`

**脚本**: `scripts/issue_note_workflow.sh`

**流程**:
```
1. 发布确认评论
2. 克隆仓库
3. 加载项目理解上下文
4. 直接使用 Copilot CLI 执行指令
5. 暂存、提交、推送变更
6. 如果分支是新的则创建 MR
7. 上传更新后的上下文
8. 发布带有 MR 链接的完成评论
```

**关键变量**:
- `ISSUE_NOTE_INSTRUCTION`: 用户的请求（从评论中提取）
- `NOTE_AUTHOR_USERNAME`: 评论者

---

### 事件 3: MR 评论 - 实现 (`mr_note`)

**触发**: 在 MR 中评论 `@copilot <实现请求>`  
（关键词: fix, apply, implement, add, create, update, modify, 修复, 应用, 实现...）

**脚本**: `scripts/mr_note_orchestrated.sh`

**流程**:
```
1. 向 MR 发布确认评论
2. 克隆并检出源分支
3. 加载项目理解上下文
4. 获取 MR 讨论（之前的审查评论）
5. 规划器生成任务计划
6. 执行器运行子任务
7. 提交并推送到源分支
8. 上传更新后的上下文
9. 发布完成评论
```

**关键变量**:
- `MR_NOTE_INSTRUCTION`: 用户的实现请求
- `SOURCE_BRANCH`: 要修改的 MR 源分支
- `MR_DISCUSSIONS`: 之前的审查评论用于上下文

---

### 事件 4: MR 评论 - 审查 (`mr_review_note`)

**触发**: 在 MR 中评论 `@copilot review/check/审查/检查`

**脚本**: `scripts/mr_review_orchestrated.sh`

**流程**:
```
1. 发布审查确认
2. 克隆仓库
3. 加载项目理解上下文（新功能！）
4. 获取分支并检出源分支
5. 规划器生成审查任务计划
6. 执行器执行代码审查
7. 解析发现并生成摘要
8. 向 MR 发布审查摘要
9. （可选）为严重问题发布行内评论
```

**关键变量**:
- `IS_REVIEW_REQUEST`: "true"
- `TARGET_BRANCH`, `SOURCE_BRANCH`: 用于差异分析

---

### 事件 5: MR 审阅者指派 (`mr_reviewer`)

**触发**: 将 Copilot 指派为 MR 审阅者

**脚本**: `scripts/mr_review_orchestrated.sh`

**流程**: 与事件 4 (mr_review_note) 相同

**关键变量**:
- `TRIGGER_TYPE`: "mr_reviewer"

---

## 核心组件

### Webhook 服务 (`src/webhook_service.py`)

```python
# 核心路由逻辑
def _extract_mr_note_variables(self, event_data):
    # 从评论中检测用户意图
    instruction = note_text.replace("@copilot", "").strip()
    
    # 实现关键词优先
    implementation_keywords = ['fix', 'apply', 'implement', '修复', '应用'...]
    review_keywords = ['review', 'check', '审查', '检查'...]
    
    has_implementation = any(kw in instruction for kw in implementation_keywords)
    has_review = any(kw in instruction for kw in review_keywords)
    
    # 路由到正确的工作流
    if has_review and not has_implementation:
        trigger_type = "mr_review_note"  # 代码审查
    else:
        trigger_type = "mr_note"  # 实现
```

### 任务规划器 (`scripts/issue_planner.py`)

使用 Copilot CLI 分析需求并生成结构化计划：
- 估算复杂度
- 分解为子任务
- 分配优先级和依赖关系
- 估算执行时间

### 任务执行器 (`scripts/issue_executor.py`)

具有弹性的子任务执行：
- 3 倍超时乘数
- 详细错误日志（`timeout_error.log`、`error.log`）
- 部分成功处理（≥50% 成功 = 作业成功）
- 产物收集

### Blob 缓存 (`scripts/blob_cache.py`)

实现 Git 风格的内容寻址存储：
- 按 SHA-256 内容去重
- 跨分支上下文复用
- 5 级缓存查找
- 增量更新

---

## 配置

### CI/CD 变量

| 变量 | 描述 |
|------|------|
| `GITLAB_TOKEN` | GitLab PAT 用于 API 访问 |
| `GITHUB_TOKEN` | 具有 Copilot 访问权限的 GitHub PAT |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob 存储（可选） |
| `COPILOT_AGENT_USERNAME` | 机器人用户名（用于循环防护） |
| `ENABLE_PROJECT_UNDERSTANDING` | 启用上下文缓存 |
| `USE_ORCHESTRATED_ISSUE` | 对 issues 使用多阶段 |
| `USE_ORCHESTRATED_MR_NOTE` | 对 MR notes 使用多阶段 |

### Webhook 环境变量

| 变量 | 描述 |
|------|------|
| `PIPELINE_TRIGGER_TOKEN` | GitLab CI 触发令牌 |
| `PIPELINE_PROJECT_ID` | Copilot 代理仓库 ID |
| `COPILOT_AGENT_USERNAME` | 机器人用户名 |
| `COPILOT_LANGUAGE` | 响应语言（en/zh/ja/ko/hi/th） |

---

## 错误处理

### 超时处理
- 默认: `estimated_time × 3`
- 保存 `timeout_error.log` 包含部分输出
- 继续下一个子任务

### 部分成功
- 如果 ≥50% 子任务成功则作业成功
- 失败任务记录完整堆栈跟踪
- 即使失败也上传产物

### 无限循环防护
- 机器人忽略自己的评论
- 检查 `note_author == copilot_agent_username`

---

## 产物 & 调试

所有工作流保存调试产物：

```
repo-{project_id}/
├── .copilot/
│   └── project_context.md
├── .copilot_tasks/
│   ├── task_1/
│   │   ├── prompt.txt
│   │   ├── output.txt
│   │   ├── stderr.txt
│   │   ├── timeout_error.log (如超时)
│   │   └── error.log (如错误)
│   └── task_2/
└── .review_tasks/ (用于审查工作流)

根级别:
├── issue_plan.json
├── execution_results.json
├── context_manager.log
└── project_analysis.log
```

---

## 版本历史

| 版本 | 变更 |
|------|------|
| v0.0.1 | 初始编排工作流 |
| v0.0.2 | 为 MR 审查添加项目上下文 |
| v0.0.3 | 添加 MR 讨论获取 |
| v0.0.4 | 3 倍超时、50% 成功阈值 |
| v0.0.5 | 详细错误日志 |
| v0.0.6-7 | Bug 修复 |
| v0.0.8 | Issues 上下文上传、跨分支去重 |

---

## 未来改进

- [ ] 第 5 级缓存: 内容相似度检测（rebase 场景）
- [ ] 并行子任务执行
- [ ] MR 实现建议的行内评论
- [ ] 交互式澄清（在评论中提问）
- [ ] 多语言代码审查模板
