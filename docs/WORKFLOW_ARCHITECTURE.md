# GitLab Copilot Coding Agent 工作机制

## 概述

GitLab Copilot Coding Agent 是一个基于 GitHub Copilot CLI 的自动化编码助手，深度集成 GitLab 工作流。它能够自动处理 Issue、响应 MR 评论、执行代码审查，并具备项目理解和上下文缓存能力。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GitLab Copilot Coding Agent                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   GitLab                    Webhook Service              GitLab CI/CD       │
│  ┌────────┐                ┌──────────────┐            ┌──────────────┐     │
│  │ Issue  │───webhook────▶│              │───trigger──▶│  Pipeline    │     │
│  │ MR     │                │   Flask App  │             │  (K8s Runner)│     │
│  │ Note   │◀───comment────│              │◀───result───│              │     │
│  └────────┘                └──────────────┘            └──────────────┘     │
│                                   │                           │             │
│                                   │                           │             │
│                            ┌──────▼──────┐              ┌─────▼─────┐       │
│                            │   Azure     │              │  Copilot  │       │
│                            │   Blob      │◀────────────▶│   CLI     │       │
│                            │   Storage   │   context    │           │       │
│                            └─────────────┘              └───────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 触发方式

### 1. Issue 分配触发 (Assignee)

当将 Issue 分配给 Copilot Agent 用户时，自动触发实现工作流。

```
用户操作: Issue → Assignee → @copilot-agent
触发类型: TRIGGER_TYPE = "issue_assignee"
```

**工作流程**:
1. 发布确认评论到 Issue
2. 创建 `copilot/issue-{iid}` 分支
3. 加载项目理解上下文
4. 多阶段执行（分析 → 架构 → 实现）
5. 提交代码并创建 MR
6. 在 Issue 中回复 MR 链接

### 2. Issue 评论触发 (@mention)

在 Issue 评论中 @copilot 并附带指令。

```
用户操作: Issue Comment → "@copilot 请添加用户登录功能"
触发类型: TRIGGER_TYPE = "issue_note"
```

**工作流程**:
1. 发布确认评论
2. 创建 `copilot/issue-{iid}-{instruction}` 分支
3. 加载项目上下文
4. 执行用户指令
5. 创建 MR
6. 回复完成状态

### 3. MR 评论触发 (@mention)

在 MR 评论中 @copilot 请求修改。

```
用户操作: MR Comment → "@copilot 请修复这个 bug"
触发类型: TRIGGER_TYPE = "mr_note"
```

**工作流程**:
1. 发布确认评论
2. 切换到 MR 的 source branch
3. 加载/更新项目上下文
4. 多阶段执行任务
5. 推送更改到同一 MR
6. 上传更新的上下文缓存

### 4. MR 审查触发 (Reviewer)

将 Copilot Agent 设为 MR Reviewer 时触发代码审查。

```
用户操作: MR → Reviewers → @copilot-agent
触发类型: TRIGGER_TYPE = "mr_reviewer"
```

**工作流程**:
1. 加载项目理解上下文
2. 获取 MR diff
3. 多维度代码审查（安全、性能、规范、逻辑）
4. 生成审查报告
5. 发布 inline comments（行级评论）
6. 发布审查总结

---

## 系统架构

### 组件说明

| 组件 | 说明 | 技术栈 |
|------|------|--------|
| **Webhook Service** | 接收 GitLab webhook，路由到对应工作流 | Flask + Python |
| **GitLab CI Runner** | 执行实际任务的 K8s Pod | Docker + K8s |
| **Copilot CLI** | GitHub Copilot 命令行工具 | `@github/copilot` |
| **Azure Blob Storage** | 项目理解上下文缓存 | Azure SDK |
| **Project Understanding** | 项目分析模块 | Python |

### 目录结构

```
├── src/
│   └── webhook_service.py      # Webhook 服务入口
├── scripts/
│   ├── issue_workflow.sh                # Issue 单阶段工作流
│   ├── issue_workflow_orchestrated.sh   # Issue 多阶段工作流
│   ├── issue_note_workflow.sh           # Issue @mention 工作流
│   ├── issue_planner.py                 # 任务计划生成器
│   ├── issue_executor.py                # 多阶段任务执行器
│   ├── mr_update.sh                     # MR Note 单阶段工作流
│   ├── mr_note_orchestrated.sh          # MR Note 多阶段工作流
│   ├── mr_review.sh                     # MR 审查工作流
│   ├── mr_review_orchestrated.sh        # MR 编排审查工作流
│   ├── ci_context_manager.sh            # 上下文缓存管理
│   └── blob_cache.py                    # Azure Blob 缓存操作
├── index_repo/src/
│   └── project_understanding/           # 项目理解模块
├── prompts/                             # 多语言 prompt 模板
│   ├── en/
│   ├── zh/
│   ├── ja/
│   └── ...
└── k8s-runner/                          # K8s 部署配置
```

---

## 多阶段执行机制

### 任务复杂度分析

系统根据 Issue/请求的内容自动判断复杂度：

```python
# 关键词检测
api_keywords = ['api', 'endpoint', 'rest', 'graphql', '接口']
db_keywords = ['database', 'db', 'migration', 'schema', '数据库']
ui_keywords = ['ui', 'frontend', 'component', 'page', '界面']
```

### 阶段划分

| 阶段 | 名称 | 触发条件 | 输出 |
|------|------|----------|------|
| 1 | **需求分析** | 始终执行 | `analysis.json` |
| 2 | **架构设计** | 中/大型任务或涉及 API/DB | `architecture.json` |
| 3 | **代码实现** | 始终执行 | 代码文件 |
| 4 | **测试编写** | 项目有测试框架 | 测试文件 |
| 5 | **文档更新** | API 变更或大型任务 | README/CHANGELOG |

### 执行流程

```
                    ┌──────────────┐
                    │  Task Plan   │
                    │  Generator   │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Analysis │─▶│ Architect│─▶│  Impl    │
        │  Task    │ │   Task   │ │  Tasks   │
        └──────────┘ └──────────┘ └──────────┘
              │            │            │
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Copilot  │ │ Copilot  │ │ Copilot  │
        │  Call 1  │ │  Call 2  │ │  Call 3  │
        └──────────┘ └──────────┘ └──────────┘
```

每个阶段独立调用 Copilot CLI，前一阶段的输出作为下一阶段的输入。

---

## 项目理解与上下文缓存

### 缓存策略（5 级）

```
Level 1: exact          - 精确匹配 (同项目/同分支/同 commit)
Level 2: parent_commit  - 父提交匹配 (增量更新)
Level 3: branch_latest  - 分支最新 (同分支任意 commit)
Level 4: cross-branch   - 跨分支 (从基准分支继承)
Level 5: full_analysis  - 全量分析 (无缓存命中)
```

### 缓存流程

```
┌─────────────────────────────────────────────────────────────┐
│                   Context Cache Flow                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 查找缓存                                                 │
│     └── blob_cache.py find-best                             │
│         └── 5 级策略逐级查找                                  │
│                                                             │
│  2. 下载/更新                                                │
│     ├── exact: 直接使用                                      │
│     ├── incremental: 增量更新                                │
│     └── full: 全量分析                                       │
│                                                             │
│  3. 上传新缓存                                               │
│     └── blob_cache.py upload                                │
│         └── 关联 project/branch/commit                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Azure Blob 存储结构

```
copilot-cache/
├── projects/
│   └── {project_id}/
│       └── branches/
│           └── {branch}/
│               └── commits/
│                   └── {commit_sha}/
│                       ├── project_context.md
│                       ├── architecture.json
│                       └── ...
└── fork-relations/
    └── {project_id}/
        └── {branch}.json
```

---

## 代码审查机制

### 审查维度

| 维度 | 检查内容 | 严重级别 |
|------|----------|----------|
| **安全性** | SQL 注入、XSS、敏感信息泄露 | Critical/Major |
| **性能** | N+1 查询、内存泄漏、复杂度 | Major/Minor |
| **代码规范** | 命名、格式、文档 | Minor/Info |
| **逻辑正确性** | 边界条件、空指针、并发 | Critical/Major |
| **可维护性** | 重复代码、耦合度、测试覆盖 | Minor/Info |

### Inline Comments

审查结果会以行级评论形式发布到 MR：

```
┌────────────────────────────────────────────────────────────┐
│ 📍 src/api/user.py:45                                       │
├────────────────────────────────────────────────────────────┤
│ 🔴 **Critical - Security**                                  │
│                                                             │
│ SQL injection vulnerability detected.                       │
│                                                             │
│ ```python                                                   │
│ # Before                                                    │
│ query = f"SELECT * FROM users WHERE id = {user_id}"        │
│                                                             │
│ # After                                                     │
│ query = "SELECT * FROM users WHERE id = ?"                 │
│ cursor.execute(query, (user_id,))                          │
│ ```                                                         │
└────────────────────────────────────────────────────────────┘
```

---

## 配置选项

### Webhook Service 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PIPELINE_TRIGGER_TOKEN` | GitLab Pipeline 触发 Token | (必需) |
| `PIPELINE_PROJECT_ID` | Pipeline 所在项目 ID | (必需) |
| `GITLAB_API_BASE` | GitLab API 地址 | `https://gitlab.com` |
| `COPILOT_AGENT_USERNAME` | Copilot 用户名 | `copilot-agent` |
| `COPILOT_LANGUAGE` | 提示语言 | `en` |
| `USE_ORCHESTRATED_ISSUE` | Issue 多阶段执行 | `true` |
| `USE_ORCHESTRATED_MR_NOTE` | MR Note 多阶段执行 | `true` |
| `ENABLE_PROJECT_UNDERSTANDING` | 启用项目理解 | `true` |
| `ENABLE_INLINE_REVIEW_COMMENTS` | 启用行级审查评论 | `true` |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure 存储连接串 | (可选) |

### GitLab CI 变量

| 变量 | 说明 |
|------|------|
| `TRIGGER_TYPE` | 触发类型 (issue_assignee/issue_note/mr_note/mr_reviewer) |
| `TARGET_PROJECT_ID` | 目标项目 ID |
| `TARGET_ISSUE_IID` | Issue IID |
| `TARGET_MR_IID` | MR IID |
| `SOURCE_BRANCH` | MR 源分支 |
| `TARGET_BRANCH` | MR 目标分支 |

---

## 部署架构

```
                    ┌─────────────────────────────────────┐
                    │           Azure AKS Cluster          │
                    ├─────────────────────────────────────┤
                    │                                     │
                    │  ┌─────────────────────────────┐   │
                    │  │     gitlab-runner namespace  │   │
                    │  ├─────────────────────────────┤   │
                    │  │                             │   │
   GitLab           │  │  ┌───────────────────────┐ │   │
   Webhook ─────────┼──┼─▶│   webhook-service     │ │   │
                    │  │  │   (Flask + Gunicorn)  │ │   │
                    │  │  └───────────┬───────────┘ │   │
                    │  │              │             │   │
                    │  │              ▼             │   │
                    │  │  ┌───────────────────────┐ │   │
                    │  │  │   gitlab-runner       │ │   │
                    │  │  │   (K8s Executor)      │ │   │
                    │  │  └───────────┬───────────┘ │   │
                    │  │              │             │   │
                    │  └──────────────┼─────────────┘   │
                    │                 │                 │
                    │                 ▼                 │
                    │  ┌─────────────────────────────┐  │
                    │  │   Runner Pod (per job)      │  │
                    │  │   copilot-runner:v0.0.1     │  │
                    │  │   - Copilot CLI             │  │
                    │  │   - Git                     │  │
                    │  │   - Python                  │  │
                    │  └─────────────────────────────┘  │
                    │                                   │
                    └───────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │        Azure Blob Storage           │
                    │     (Project Context Cache)         │
                    └─────────────────────────────────────┘
```

---

## 多语言支持

系统支持多种语言的 prompt 模板：

| 语言 | 代码 | 状态 |
|------|------|------|
| English | `en` | ✅ 完整 |
| 中文 | `zh` | ✅ 完整 |
| 日本語 | `ja` | ✅ 完整 |
| 한국어 | `ko` | ✅ 完整 |
| हिंदी | `hi` | ✅ 完整 |
| ไทย | `th` | ✅ 完整 |

通过 `COPILOT_LANGUAGE` 环境变量配置。

---

## 典型使用场景

### 场景 1: 新功能开发

```
1. 创建 Issue: "添加用户注册功能"
2. 将 Issue 分配给 @copilot-agent
3. Copilot 自动:
   - 分析需求
   - 设计架构
   - 实现代码
   - 创建 MR
4. 用户审查并合并
```

### 场景 2: Bug 修复

```
1. 在 Issue 评论: "@copilot 修复登录页面的验证问题"
2. Copilot 自动:
   - 分析问题
   - 修复代码
   - 创建 MR
3. 用户确认修复
```

### 场景 3: MR 迭代

```
1. 创建 MR 后，在评论: "@copilot 请添加单元测试"
2. Copilot 自动:
   - 在 source branch 上添加测试
   - 推送更新
3. MR 自动更新
```

### 场景 4: 代码审查

```
1. 创建 MR 后，添加 @copilot-agent 为 Reviewer
2. Copilot 自动:
   - 分析代码变更
   - 发布行级评论
   - 生成审查总结
3. 用户根据反馈修改
```

---

## 限制与注意事项

1. **Token 限制**: Copilot CLI 有上下文长度限制，大型项目分析可能被截断
2. **执行时间**: 单任务默认超时 3600 秒
3. **并发限制**: 为避免 Copilot CLI 并发问题，任务串行执行
4. **分支保护**: Copilot 无法直接推送到受保护分支，需通过 MR
5. **权限要求**: Copilot Agent 用户需要项目的 Developer 权限

---

## 版本历史

| 版本 | 日期 | 主要更新 |
|------|------|----------|
| v0.0.6 | 2024-12-16 | MR Note 多阶段执行、上下文缓存更新 |
| v0.0.5 | 2024-12-16 | Issue @mention 支持 |
| v0.0.4 | 2024-12-15 | 项目理解缓存集成 |
| v0.0.3 | 2024-12-14 | 多阶段 Issue 执行 |
| v0.0.2 | 2024-12-13 | Inline review comments |
| v0.0.1 | 2024-12-12 | 初始版本 |
