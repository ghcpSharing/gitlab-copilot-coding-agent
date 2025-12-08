# Git-like Project Context Storage - Task Breakdown

**设计文档**: [PROJECT_CONTEXT_STORAGE.md](PROJECT_CONTEXT_STORAGE.md)  
**开始日期**: 2025-12-08  
**状态**: Planning

---

## 🎯 项目目标

实现基于 Git-like 对象存储的项目理解上下文管理系统，支持：
- 内容寻址存储（Content-Addressable Storage, CAS）
- 跨 commit/branch 内容去重
- 智能缓存查找（5 级回退策略）
- 增量更新（只分析变化的模块）

---

## 📋 Task List

### **Phase 1: 基础设施准备** (1-2 天)

#### Task 1.1: 增强 metadata.json 结构
- [x] **文件**: `index_repo/src/project_understanding/models.py`
- [x] **目标**: 扩展 `ProjectContext` 和 `CacheMetadata` 数据模型
- [x] **子任务**:
  - [x] 添加 `lineage` 字段（parent_commit, base_branch, base_commit, merge_from, fork_type）
  - [x] 添加 `content_objects` 字段（文件路径 → {hash, size, source, source_commit}）
  - [x] 添加 `agents` 执行状态字段（status: inherited/success/failed/skipped）
  - [x] 添加 `stats` 统计字段（inherited_files, updated_files, new_files, deduplication_ratio）
  - [x] 添加 `git` 信息字段（author, message, changed_files, additions, deletions）
- [x] **验收标准**: 
  - metadata.json 可序列化/反序列化
  - 包含所有必需字段的 JSON schema
- [x] **预计时间**: 2-3 小时
- [x] **完成时间**: 2025-12-08

#### Task 1.2: 创建 parent_branch.json 数据结构
- [x] **文件**: `index_repo/src/project_understanding/models.py`
- [x] **目标**: 定义分支派生关系的数据模型
- [x] **子任务**:
  - [x] 创建 `BranchForkInfo` dataclass
  - [x] 字段：base_branch, base_commit, created_at, fork_type, created_by
  - [x] 支持序列化为 JSON
- [x] **验收标准**: 可以记录和读取分支派生信息
- [x] **预计时间**: 1 小时
- [x] **完成时间**: 2025-12-08

#### Task 1.3: 实现 content hash 计算
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 添加文件内容 SHA-256 hash 计算功能
- [x] **子任务**:
  - [x] 添加 `_compute_file_hash(file_path) -> str` 方法
  - [x] 返回格式：`sha256-{hex_digest}`
  - [x] 支持大文件（流式计算）
  - [ ] 添加单元测试（Phase 7）
- [x] **验收标准**: 
  - 相同内容文件生成相同 hash
  - 性能测试：100MB 文件 < 2s
- [x] **预计时间**: 2 小时
- [x] **完成时间**: 2025-12-08

---

### **Phase 2: Blob Storage 结构重构** (2-3 天)

#### Task 2.1: 实现 objects/content/ 内容对象存储
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 实现基于 hash 的内容对象上传/下载
- [x] **子任务**:
  - [x] 添加 `_upload_content_object(file_path, content_hash)` 方法
    - 路径格式：`objects/content/{content_hash}`
    - 上传前检查是否已存在（去重）
  - [x] 添加 `_download_content_object(content_hash, local_path)` 方法
  - [x] 添加 `_content_exists(content_hash) -> bool` 方法
  - [ ] 批量上传优化（并发上传）（Phase 7）
- [x] **验收标准**: 
  - 相同内容只上传一次
  - 下载的文件与原文件 hash 相同
- [x] **预计时间**: 4-5 小时
- [x] **完成时间**: 2025-12-08

#### Task 2.2: 重构 projects/ 目录结构
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 实现新的 projects/{project_id}/branches/{branch}/commits/ 结构
- [x] **子任务**:
  - [x] 修改 `_get_metadata_path()` 方法
    - 新路径：`projects/{project_id}/branches/{branch}/commits/{commit_sha}/metadata.json`
  - [x] 添加 `_get_branch_path()` 方法
  - [x] 添加 `_get_commit_path()` 方法
  - [x] 添加 `_sanitize_branch_name()` 方法
  - [ ] 迁移现有数据（可选）
- [x] **验收标准**: 
  - 新旧路径兼容
  - 目录结构清晰可导航
- [x] **预计时间**: 3 小时
- [x] **完成时间**: 2025-12-08

#### Task 2.3: 实现 latest.json 最新 commit 索引
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 快速查找分支最新 commit
- [x] **子任务**:
  - [x] 添加 `_update_branch_latest(project_id, branch, commit_sha, metadata)` 方法
    - 路径：`projects/{project_id}/branches/{branch}/latest.json`
    - 内容：`{commit_sha, created_at, analysis_type}`
  - [x] 添加 `_get_branch_latest(project_id, branch)` 方法
  - [ ] 上传 metadata 时自动更新 latest.json（Phase 4 集成）
- [x] **验收标准**: 
  - latest.json 始终指向最新 commit
  - 并发上传时无冲突
- [x] **预计时间**: 2 小时
- [x] **完成时间**: 2025-12-08

#### Task 2.4: 实现 parent_branch.json 派生关系记录
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 记录分支的基准分支信息
- [x] **子任务**:
  - [x] 添加 `record_branch_fork()` 方法
    - 参数：project_id, new_branch, base_branch, base_commit
    - 路径：`projects/{project_id}/branches/{new_branch}/parent_branch.json`
  - [x] 添加 `_get_base_branch_info()` 方法
  - [x] 添加 CLI 支持：`blob_cache.py record-fork`
- [x] **验收标准**: 
  - 可记录分支派生关系
  - 可读取基准分支信息
- [x] **预计时间**: 2 小时
- [x] **完成时间**: 2025-12-08

---

### **Phase 3: 智能缓存查找** ✅ (100% 完成)

#### Task 3.1: 实现 Level 1-4 缓存查找 ✅
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 实现精确匹配、父 commit、分支最新、跨分支查找
- [x] **子任务**:
  - [x] 添加 `_get_metadata()` 辅助方法
  - [x] 添加 `find_best_context()` 方法（156 行）
  - [x] 实现 Level 1: 精确匹配（当前 commit）
  - [x] 实现 Level 2: 父 commit（增量更新）
  - [x] 实现 Level 3: 分支最新 commit
  - [x] 实现 Level 4: 跨分支复用（via parent_branch.json）
  - [x] 添加详细日志记录（每级查找结果）
- [x] **验收标准**: 
  - 按优先级返回最佳缓存 ✓
  - 返回结构化 dict: found, commit_sha, metadata, reuse_strategy ✓
- [x] **预计时间**: 4 小时
- [x] **完成时间**: 2025-12-08

#### Task 3.2: 实现 Level 4 跨分支缓存复用 ✅
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 新分支复用基准分支的分析
- [x] **说明**: 已合并到 Task 3.1 中实现
- [x] **完成时间**: 2025-12-08（与 3.1 同步）

#### Task 3.3: Level 5 内容相似度基础 ✅
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 为 rebase 场景准备相似度计算
- [x] **子任务**:
  - [x] 添加 `_calculate_similarity(tree1, tree2)` 方法（Jaccard）
  - [x] 在 find_best_context 中预留 Level 5 框架
- [x] **说明**: 完整的 git 树提取需要 git 仓库访问，后续按需实现
- [x] **完成时间**: 2025-12-08

#### Task 3.4: 添加 CLI 支持 ✅
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 提供命令行接口
- [x] **子任务**:
  - [x] 添加 `find-best` action
    - 参数：--project-id, --branch, --commit, --parent-commit
    - 输出：JSON 格式的查找结果
  - [x] 更新 action choices
- [x] **验收标准**: 
  - CLI 可独立运行 ✓
  - 输出 JSON 格式正确 ✓
- [x] **完成时间**: 2025-12-08

---

### **Phase 4: 去重上传实现** ✅ (100% 完成)

#### Task 4.1: 实现去重上传核心逻辑 ✅
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 上传时自动去重，复用已有 content objects
- [x] **子任务**:
  - [x] 实现 `upload_context_with_dedup()` 方法
  - [x] 遍历本地文件，计算 SHA-256 hash
  - [x] 与 parent_metadata 比较，判断 inherited/updated/new
  - [x] 检查 `objects/content/{hash}` 是否存在（via _content_exists）
  - [x] 只上传不存在的 content objects
  - [x] 构建 metadata.json 的 content_objects 索引
  - [x] 记录每个文件的 source 和 source_commit
- [x] **验收标准**: 
  - 相同内容不重复上传 ✓
  - metadata.json 正确引用 content objects ✓
  - 详细日志输出每个文件状态 ✓
- [x] **完成时间**: 2025-12-08

#### Task 4.2: 基于 metadata 的下载实现 ✅
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 根据 metadata.json 下载所有引用的文件
- [x] **子任务**:
  - [x] 重构 `download_context()` 方法
  - [x] 先下载 metadata.json（via _get_metadata）
  - [x] 解析 content_objects 索引
  - [x] 批量下载引用的 content objects（via _download_content_object）
  - [x] 按原路径重建目录结构
  - [x] 保留旧版 _download_context_legacy() 兼容性
- [x] **验收标准**: 
  - 下载的目录结构与上传时一致 ✓
  - 所有文件内容完整 ✓
  - 支持回退到旧版下载 ✓
- [x] **完成时间**: 2025-12-08

#### Task 4.3: 计算去重统计 ✅
- [x] **文件**: `scripts/blob_cache.py`
- [x] **目标**: 在 metadata 中记录去重效果
- [x] **子任务**:
  - [x] 在上传时统计：
    - total_files: 总文件数
    - inherited_files: 复用的文件数
    - updated_files: 更新的文件数
    - new_files: 新增的文件数
    - uploaded_objects: 实际上传的对象数
  - [x] 计算 deduplication_ratio = inherited / total
  - [x] 记录到 metadata.stats
  - [x] 添加详细日志输出（含百分比）
- [x] **验收标准**: 
  - stats 数据准确 ✓
  - 日志可读性好（✓/↻/+ 符号标注）✓
- [x] **完成时间**: 2025-12-08

---

### **Phase 5: 增量更新支持** (3-4 天)

#### Task 5.1: 实现变更检测脚本
- [ ] **文件**: `scripts/detect_changes.py` (新建)
- [ ] **目标**: 分析 git diff，确定影响的模块
- [ ] **子任务**:
  - [ ] 读取 git diff 输出（parent_commit..current_commit）
  - [ ] 分类文件变更：added, modified, deleted
  - [ ] 映射文件到模块：
    - `src/` → domain, api
    - `schema.prisma` → data_model
    - `package.json` → tech_stack
    - `src/auth/*` → security
  - [ ] 输出 changes.json：
    ```json
    {
      "affected_modules": ["api", "data_model"],
      "added_files": [...],
      "modified_files": [...],
      "deleted_files": [...],
      "estimated_impact": {
        "tech_stack": "none",
        "data_model": "high",
        ...
      }
    }
    ```
- [ ] **验收标准**: 
  - 准确识别影响的模块
  - 支持自定义映射规则
- [ ] **预计时间**: 4 小时

#### Task 5.2: 创建增量更新 prompt
- [ ] **文件**: `prompts/en/project_update.txt` (新建)
- [ ] **目标**: 为增量更新提供专用 prompt
- [ ] **子任务**:
  - [ ] 编写 prompt 模板
  - [ ] 输入：base_context + git_diff + changes.json
  - [ ] 输出：更新后的完整文件（JSON/Markdown）
  - [ ] 标注变更部分（🆕 新增、🔄 更新、❌ 删除）
  - [ ] 添加多语言版本（en, zh, ja, ko, hi, th）
- [ ] **验收标准**: 
  - prompt 清晰易懂
  - 输出格式标准化
- [ ] **预计时间**: 3 小时

#### Task 5.3: 实现增量更新逻辑
- [ ] **文件**: `index_repo/src/project_understanding/orchestrator.py`
- [ ] **目标**: 支持 update 模式（vs 完整 analyze）
- [ ] **子任务**:
  - [ ] 添加 `Orchestrator.run_incremental_update()` 方法
  - [ ] 参数：base_context_dir, changes_json_path, update_modules
  - [ ] 只运行受影响模块的 Agents
  - [ ] 其他模块直接复用 base_context
  - [ ] 合并生成最终 context
- [ ] **验收标准**: 
  - 只更新指定的模块
  - 未变化模块保持不变
  - 时间消耗 < 完整分析的 30%
- [ ] **预计时间**: 6 小时

#### Task 5.4: 添加 CLI update 子命令
- [ ] **文件**: `index_repo/src/project_understanding/cli.py`
- [ ] **目标**: 提供增量更新命令行接口
- [ ] **子任务**:
  - [ ] 添加 `update` 子命令
  - [ ] 参数：
    - `--base-context`: 基准 context 目录
    - `--changes`: changes.json 路径
    - `--update-modules`: 要更新的模块列表
  - [ ] 调用 `Orchestrator.run_incremental_update()`
- [ ] **验收标准**: 
  - 命令可独立运行
  - 参数验证完整
- [ ] **预计时间**: 2 小时

---

### **Phase 6: CI/CD 集成** (2-3 天)

#### Task 6.1: 检测新分支并记录派生关系
- [ ] **文件**: `.gitlab-ci.yml`
- [ ] **目标**: CI 中自动检测新分支并记录 parent_branch
- [ ] **子任务**:
  - [ ] 添加分支检测脚本：
    ```bash
    if ! git show-ref --verify --quiet refs/remotes/origin/${CI_COMMIT_REF_NAME}; then
      IS_NEW_BRANCH=true
      BASE_BRANCH=$(git show-branch | grep '*' | ...)
      BASE_COMMIT=$(git merge-base HEAD origin/${BASE_BRANCH})
    fi
    ```
  - [ ] 调用 `blob_cache.py record-fork`
  - [ ] 添加环境变量：IS_NEW_BRANCH, BASE_BRANCH, BASE_COMMIT
- [ ] **验收标准**: 
  - 新分支首次运行时记录派生关系
  - 后续 commit 不重复记录
- [ ] **预计时间**: 3 小时

#### Task 6.2: 集成智能缓存查找
- [ ] **文件**: `.gitlab-ci.yml`
- [ ] **目标**: 替换当前简单的缓存下载为 5 级查找
- [ ] **子任务**:
  - [ ] 调用 `blob_cache.py find-best`
  - [ ] 解析返回的 JSON（reuse_strategy, commit_sha）
  - [ ] 根据策略选择执行路径：
    - `exact`: 跳过分析
    - `incremental/cross-branch/content-similar`: 增量更新
    - `full_analysis`: 完整分析
  - [ ] 添加日志输出（使用了哪级缓存）
- [ ] **验收标准**: 
  - 正确选择缓存策略
  - 日志清晰可读
- [ ] **预计时间**: 4 小时

#### Task 6.3: 集成增量更新流程
- [ ] **文件**: `.gitlab-ci.yml`
- [ ] **目标**: 在 CI 中支持增量更新
- [ ] **子任务**:
  - [ ] 当策略为 incremental/cross-branch 时：
    ```bash
    # 下载基准缓存
    python scripts/blob_cache.py download ...
    
    # 检测变更
    python scripts/detect_changes.py \
      --parent ${BASE_COMMIT} \
      --current ${CURRENT_COMMIT}
    
    # 增量更新
    python -m project_understanding.cli update \
      --base-context .copilot \
      --changes changes.json
    
    # 上传新缓存（去重）
    python scripts/blob_cache.py upload --deduplicate ...
    ```
  - [ ] 添加性能统计（分析耗时、去重率）
- [ ] **验收标准**: 
  - 增量更新正常工作
  - 时间节省明显（< 30% 完整分析）
- [ ] **预计时间**: 4 小时

#### Task 6.4: 更新 mr_review_executor 加载 context
- [ ] **文件**: `scripts/mr_review_executor.py`
- [ ] **目标**: 确保 executor 能正确加载新结构的 context
- [ ] **子任务**:
  - [ ] 适配新的 .copilot/ 目录结构
  - [ ] 加载 metadata.json（可选，用于调试）
  - [ ] 保持向后兼容（支持旧的单文件 context.md）
- [ ] **验收标准**: 
  - MR review 可正常使用 context
  - 新旧格式都支持
- [ ] **预计时间**: 2 小时

---

### **Phase 7: 测试和优化** (2-3 天)

#### Task 7.1: 单元测试
- [ ] **文件**: `tests/test_blob_cache.py` (新建)
- [ ] **目标**: 测试 blob_cache.py 的核心功能
- [ ] **子任务**:
  - [ ] 测试 content hash 计算
  - [ ] 测试去重上传/下载
  - [ ] 测试 5 级缓存查找
  - [ ] 测试分支派生记录
  - [ ] 测试相似度计算
  - [ ] 使用 mock Azure Blob Storage
- [ ] **验收标准**: 
  - 覆盖率 > 80%
  - 所有测试通过
- [ ] **预计时间**: 6 小时

#### Task 7.2: 集成测试
- [ ] **文件**: `tests/test_integration.py` (新建)
- [ ] **目标**: 端到端测试完整流程
- [ ] **子任务**:
  - [ ] 测试场景 1：同分支线性开发
    - commit A (完整) → commit B (增量) → commit C (增量)
  - [ ] 测试场景 2：跨分支复用
    - main@C → feature@D (继承 main@C)
  - [ ] 测试场景 3：rebase 场景
    - feature@E → rebase → feature@E' (内容相似)
  - [ ] 验证去重率、时间节省
- [ ] **验收标准**: 
  - 所有场景测试通过
  - 性能指标达标
- [ ] **预计时间**: 4 小时

#### Task 7.3: 性能优化
- [ ] **文件**: `scripts/blob_cache.py`
- [ ] **目标**: 优化上传/下载性能
- [ ] **子任务**:
  - [ ] 并发上传 content objects（ThreadPoolExecutor）
  - [ ] 并发下载 content objects
  - [ ] 添加本地缓存（避免重复下载）
  - [ ] 压缩大文件（gzip）
  - [ ] 添加进度条（tqdm）
- [ ] **验收标准**: 
  - 50 个文件上传 < 30s
  - 50 个文件下载 < 20s
- [ ] **预计时间**: 4 小时

#### Task 7.4: 错误处理和日志
- [ ] **文件**: `scripts/blob_cache.py`, `orchestrator.py`
- [ ] **目标**: 完善错误处理和日志记录
- [ ] **子任务**:
  - [ ] 添加重试机制（网络错误）
  - [ ] 添加超时处理
  - [ ] 统一日志格式
  - [ ] 添加调试模式（--verbose）
  - [ ] 记录性能指标（duration, dedup_ratio）
- [ ] **验收标准**: 
  - 网络异常可恢复
  - 日志信息充分
- [ ] **预计时间**: 3 小时

---

### **Phase 8: 监控和文档** (1-2 天)

#### Task 8.1: 添加性能监控
- [ ] **文件**: `scripts/blob_cache.py`
- [ ] **目标**: 上传统计数据到 Blob Storage
- [ ] **子任务**:
  - [ ] 创建 `stats/{project_id}/YYYY-MM.json`
  - [ ] 记录每次分析的指标：
    - cache_hit_level (1-6)
    - analysis_type (full/incremental/inherited)
    - duration_ms
    - deduplication_ratio
    - storage_saved_bytes
  - [ ] 添加 `blob_cache.py stats` 子命令（查询统计）
- [ ] **验收标准**: 
  - 统计数据准确
  - 可生成报表
- [ ] **预计时间**: 3 小时

#### Task 8.2: 更新用户文档
- [ ] **文件**: `README.md`, `docs/DEPLOYMENT_GUIDE_CN.md`
- [ ] **目标**: 说明新的缓存机制
- [ ] **子任务**:
  - [ ] 更新 README 的架构图
  - [ ] 添加缓存策略说明
  - [ ] 添加去重效果示例
  - [ ] 更新环境变量说明
  - [ ] 添加故障排查指南
- [ ] **验收标准**: 
  - 文档清晰易懂
  - 示例可运行
- [ ] **预计时间**: 3 小时

#### Task 8.3: 创建运维手册
- [ ] **文件**: `docs/OPERATIONS.md` (新建)
- [ ] **目标**: 运维人员参考文档
- [ ] **子任务**:
  - [ ] 如何手动触发完整分析
  - [ ] 如何清理过期缓存
  - [ ] 如何查看缓存使用情况
  - [ ] 如何排查缓存未命中问题
  - [ ] 性能调优建议
- [ ] **验收标准**: 
  - 覆盖常见运维场景
  - 命令可直接复制执行
- [ ] **预计时间**: 2 小时

---

## 📊 时间估算

| Phase | 任务数 | 预计时间 | 依赖 |
|-------|-------|---------|------|
| Phase 1: 基础设施准备 | 3 | 1-2 天 | - |
| Phase 2: Blob Storage 重构 | 4 | 2-3 天 | Phase 1 |
| Phase 3: 智能缓存查找 | 4 | 3-4 天 | Phase 2 |
| Phase 4: 去重上传实现 | 3 | 2-3 天 | Phase 2 |
| Phase 5: 增量更新支持 | 4 | 3-4 天 | Phase 3, 4 |
| Phase 6: CI/CD 集成 | 4 | 2-3 天 | Phase 3, 4, 5 |
| Phase 7: 测试和优化 | 4 | 2-3 天 | Phase 1-6 |
| Phase 8: 监控和文档 | 3 | 1-2 天 | Phase 7 |
| **总计** | **29** | **16-24 天** | - |

---

## 🎯 里程碑

### Milestone 1: 基础可用 (Week 1)
- ✅ Phase 1 完成
- ✅ Phase 2 完成
- ✅ 可以上传/下载去重的 content objects

### Milestone 2: 智能缓存 (Week 2)
- ✅ Phase 3 完成
- ✅ 5 级缓存查找工作
- ✅ 跨分支复用可用

### Milestone 3: 增量更新 (Week 3)
- ✅ Phase 4 完成
- ✅ Phase 5 完成
- ✅ 增量更新节省 70%+ 时间

### Milestone 4: 生产就绪 (Week 4)
- ✅ Phase 6 完成
- ✅ Phase 7 完成
- ✅ Phase 8 完成
- ✅ 所有测试通过
- ✅ 文档完整

---

## 🚀 快速开始（开发者）

### 克隆并切换分支
```bash
git checkout -b feature/gitlike-context
```

### 从 Phase 1 开始
```bash
# 1. 增强数据模型
vim index_repo/src/project_understanding/models.py

# 2. 实现 content hash
vim scripts/blob_cache.py

# 3. 运行测试
python -m pytest tests/test_blob_cache.py -v
```

### 提交规范
```bash
git commit -m "feat(blob-cache): implement content hash calculation

- Add _compute_file_hash() method
- Support streaming for large files
- Add unit tests

Task: 1.3
Phase: 1
```

---

## 📝 进度跟踪

**当前阶段**: Phase 4 完成 ✅ 进入 Phase 5  
**总体进度**: 14/29 任务 (48%)  
**下一步**: Phase 5 - 增量更新支持

### 已完成阶段
- [x] **Phase 1: 基础设施准备** (3/3 任务) - 100% ✅
- [x] **Phase 2: Blob 存储重构** (4/4 任务) - 100% ✅
- [x] **Phase 3: 智能缓存查找** (4/4 任务) - 100% ✅
- [x] **Phase 4: 去重上传实现** (3/3 任务) - 100% ✅

### 进行中任务
- [ ] **Phase 5: 增量更新支持** (0/4 任务) - 准备开始

### 阻塞问题
- 无

---

## 🔗 相关资源

- [设计文档](PROJECT_CONTEXT_STORAGE.md)
- [项目理解架构](../index_repo/architect_v2.md)
- [Azure Blob Storage SDK](https://learn.microsoft.com/en-us/python/api/azure-storage-blob/)
- [Git 内部原理](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)

---

## 📞 联系方式

如有问题，请在 GitLab Issue 中讨论：
- 技术问题：添加 `label: tech-design`
- Bug 报告：添加 `label: bug`
- 功能建议：添加 `label: enhancement`
