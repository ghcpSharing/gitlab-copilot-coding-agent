#!/usr/bin/env python3
"""
Issue 任务规划器
根据 Issue 的规模和复杂度，智能生成执行任务计划
"""
import sys
import os
import json
import re
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class IssueTaskType(str, Enum):
    """Issue 子任务类型"""
    ANALYSIS = "analysis"           # 需求分析
    ARCHITECTURE = "architecture"   # 架构设计
    IMPLEMENTATION = "implementation"  # 代码实现
    TESTING = "testing"            # 测试
    DOCUMENTATION = "documentation" # 文档
    INTEGRATION = "integration"    # 集成


@dataclass
class IssueSubTask:
    """Issue 子任务定义"""
    id: str
    task_type: IssueTaskType
    title: str
    description: str
    estimated_time_seconds: int = 600
    priority: int = 1  # 1 = 最高优先级
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


@dataclass
class IssuePlan:
    """Issue 执行计划"""
    issue_id: str
    issue_title: str
    total_subtasks: int
    estimated_total_time_seconds: int
    max_concurrent_tasks: int
    subtasks: List[IssueSubTask]
    metadata: Dict = field(default_factory=dict)


def analyze_issue_complexity(issue_title: str, issue_description: str, project_context: Optional[str] = None) -> Dict:
    """分析 Issue 复杂度"""
    complexity = {
        'scope': 'small',  # small, medium, large
        'has_api_changes': False,
        'has_db_changes': False,
        'has_ui_changes': False,
        'has_security_impact': False,
        'estimated_files': 5,
        'keywords': []
    }
    
    text = f"{issue_title} {issue_description}".lower()
    
    # 检测关键词
    api_keywords = ['api', 'endpoint', 'rest', 'graphql', 'route']
    db_keywords = ['database', 'db', 'migration', 'schema', 'model', 'table', 'query']
    ui_keywords = ['ui', 'frontend', 'component', 'page', 'view', 'form', 'button']
    security_keywords = ['auth', 'security', 'permission', 'role', 'token', 'password', 'encrypt']
    large_scope_keywords = ['refactor', 'migrate', 'overhaul', 'redesign', 'rewrite']
    
    if any(k in text for k in api_keywords):
        complexity['has_api_changes'] = True
        complexity['keywords'].append('api')
    if any(k in text for k in db_keywords):
        complexity['has_db_changes'] = True
        complexity['keywords'].append('database')
    if any(k in text for k in ui_keywords):
        complexity['has_ui_changes'] = True
        complexity['keywords'].append('ui')
    if any(k in text for k in security_keywords):
        complexity['has_security_impact'] = True
        complexity['keywords'].append('security')
    if any(k in text for k in large_scope_keywords):
        complexity['scope'] = 'large'
        complexity['estimated_files'] = 20
    
    # 根据描述长度估算复杂度
    desc_len = len(issue_description)
    if desc_len > 2000:
        complexity['scope'] = 'large'
        complexity['estimated_files'] = 15
    elif desc_len > 500:
        complexity['scope'] = 'medium'
        complexity['estimated_files'] = 8
    
    return complexity


def generate_issue_plan(
    issue_id: str,
    issue_title: str,
    issue_description: str,
    project_context: Optional[str] = None,
    repo_structure: Optional[List[str]] = None
) -> IssuePlan:
    """生成 Issue 执行计划"""
    
    # 分析复杂度
    complexity = analyze_issue_complexity(issue_title, issue_description, project_context)
    
    subtasks = []
    task_counter = 1
    
    # 阶段 1: 需求分析（始终需要）
    subtasks.append(IssueSubTask(
        id=f"task_{task_counter}",
        task_type=IssueTaskType.ANALYSIS,
        title="需求分析与任务拆解",
        description=f"""分析 Issue 需求并生成详细的实现计划：

**Issue 标题**: {issue_title}

**Issue 描述**:
{issue_description[:2000]}

**任务**:
1. 理解需求的核心目标
2. 识别技术约束和依赖
3. 拆解成具体的实现步骤
4. 评估潜在风险和边界情况

**输出**: 生成 `analysis.json` 包含：
- requirements: 核心需求列表
- constraints: 技术约束
- implementation_steps: 实现步骤
- risks: 潜在风险
- acceptance_criteria: 验收标准
""",
        estimated_time_seconds=300,
        priority=1,
        metadata={'phase': 'analysis', 'complexity': complexity}
    ))
    task_counter += 1
    
    # 阶段 2: 架构设计（中大型任务需要）
    if complexity['scope'] in ['medium', 'large'] or complexity['has_api_changes'] or complexity['has_db_changes']:
        subtasks.append(IssueSubTask(
            id=f"task_{task_counter}",
            task_type=IssueTaskType.ARCHITECTURE,
            title="架构设计",
            description=f"""设计实现方案的技术架构：

**分析结果**: 参考 analysis.json

**任务**:
1. 确定需要修改/新增的模块和文件
2. 设计数据模型变更（如需要）
3. 设计 API 接口（如需要）
4. 确定代码组织结构

**输出**: 生成 `architecture.json` 包含：
- affected_files: 需要修改的文件列表
- new_files: 需要新增的文件列表
- data_model_changes: 数据模型变更
- api_changes: API 变更
- dependencies: 外部依赖变更
""",
            estimated_time_seconds=300,
            priority=2,
            dependencies=[f"task_{task_counter-1}"],
            metadata={'phase': 'architecture'}
        ))
        task_counter += 1
    
    # 阶段 3: 代码实现（始终需要，可能拆分为多个子任务）
    impl_tasks = []
    
    if complexity['scope'] == 'large':
        # 大型任务拆分为多个实现子任务
        if complexity['has_db_changes']:
            impl_tasks.append(('数据层实现', 'database', ['model', 'migration', 'repository']))
        if complexity['has_api_changes']:
            impl_tasks.append(('API层实现', 'api', ['controller', 'route', 'middleware']))
        if complexity['has_ui_changes']:
            impl_tasks.append(('UI层实现', 'ui', ['component', 'page', 'style']))
        if not impl_tasks:
            impl_tasks.append(('核心功能实现', 'core', ['main']))
    else:
        impl_tasks.append(('功能实现', 'full', ['all']))
    
    for impl_title, impl_scope, impl_focus in impl_tasks:
        deps = [s.id for s in subtasks if s.task_type in [IssueTaskType.ANALYSIS, IssueTaskType.ARCHITECTURE]]
        subtasks.append(IssueSubTask(
            id=f"task_{task_counter}",
            task_type=IssueTaskType.IMPLEMENTATION,
            title=impl_title,
            description=f"""实现代码变更：

**范围**: {impl_scope}
**关注点**: {', '.join(impl_focus)}

**任务**:
1. 按照架构设计实现代码
2. 遵循项目代码规范
3. 添加必要的注释
4. 确保代码可编译/运行

**注意**:
- 使用项目现有的代码风格
- 复用现有的工具函数和模块
- 考虑错误处理和边界情况
""",
            estimated_time_seconds=600 if complexity['scope'] != 'large' else 900,
            priority=3,
            dependencies=deps[-1:] if deps else [],  # 只依赖最后一个分析/架构任务
            metadata={'phase': 'implementation', 'scope': impl_scope, 'focus': impl_focus}
        ))
        task_counter += 1
    
    # 阶段 4: 测试（如果项目有测试框架）
    if repo_structure and any('test' in f.lower() for f in (repo_structure or [])):
        impl_task_ids = [s.id for s in subtasks if s.task_type == IssueTaskType.IMPLEMENTATION]
        subtasks.append(IssueSubTask(
            id=f"task_{task_counter}",
            task_type=IssueTaskType.TESTING,
            title="测试用例编写",
            description=f"""为实现的功能编写测试：

**任务**:
1. 编写单元测试覆盖核心逻辑
2. 编写集成测试（如适用）
3. 确保测试可以运行

**验收标准**:
- 测试覆盖主要功能路径
- 测试覆盖错误处理路径
- 测试命名清晰描述测试目的
""",
            estimated_time_seconds=300,
            priority=4,
            dependencies=impl_task_ids[-1:] if impl_task_ids else [],
            metadata={'phase': 'testing'}
        ))
        task_counter += 1
    
    # 阶段 5: 文档更新（如果涉及 API 或重大变更）
    if complexity['has_api_changes'] or complexity['scope'] == 'large':
        subtasks.append(IssueSubTask(
            id=f"task_{task_counter}",
            task_type=IssueTaskType.DOCUMENTATION,
            title="文档更新",
            description=f"""更新相关文档：

**任务**:
1. 更新 README（如需要）
2. 更新 API 文档（如需要）
3. 添加代码注释
4. 更新 CHANGELOG（如需要）

**注意**:
- 文档应与代码变更保持同步
- 使用项目现有的文档格式
""",
            estimated_time_seconds=180,
            priority=5,
            dependencies=[subtasks[-1].id],
            metadata={'phase': 'documentation'}
        ))
        task_counter += 1
    
    # 计算总时间
    total_time = sum(s.estimated_time_seconds for s in subtasks)
    
    # 确定并发度（实现任务可以并行）
    impl_count = len([s for s in subtasks if s.task_type == IssueTaskType.IMPLEMENTATION])
    max_concurrent = min(impl_count, 3) if impl_count > 1 else 1
    
    return IssuePlan(
        issue_id=issue_id,
        issue_title=issue_title,
        total_subtasks=len(subtasks),
        estimated_total_time_seconds=total_time,
        max_concurrent_tasks=max_concurrent,
        subtasks=subtasks,
        metadata={
            'complexity': complexity,
            'has_project_context': project_context is not None
        }
    )


def plan_to_dict(plan: IssuePlan) -> Dict:
    """将计划转换为字典"""
    return {
        'issue_id': plan.issue_id,
        'issue_title': plan.issue_title,
        'total_subtasks': plan.total_subtasks,
        'estimated_total_time_seconds': plan.estimated_total_time_seconds,
        'max_concurrent_tasks': plan.max_concurrent_tasks,
        'subtasks': [
            {
                'id': s.id,
                'task_type': s.task_type.value,
                'title': s.title,
                'description': s.description,
                'estimated_time_seconds': s.estimated_time_seconds,
                'priority': s.priority,
                'dependencies': s.dependencies,
                'metadata': s.metadata
            }
            for s in plan.subtasks
        ],
        'metadata': plan.metadata
    }


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Issue Task Planner')
    parser.add_argument('--issue-id', required=True, help='Issue ID')
    parser.add_argument('--issue-title', required=True, help='Issue title')
    parser.add_argument('--issue-description', required=True, help='Issue description')
    parser.add_argument('--project-context', help='Path to project context file')
    parser.add_argument('--repo-structure', help='Path to repo structure file')
    parser.add_argument('--output', default='issue_plan.json', help='Output file')
    
    args = parser.parse_args()
    
    # 加载项目上下文
    project_context = None
    if args.project_context and Path(args.project_context).exists():
        project_context = Path(args.project_context).read_text(encoding='utf-8')
        print(f"[INFO] Loaded project context ({len(project_context)} chars)")
    
    # 加载仓库结构
    repo_structure = None
    if args.repo_structure and Path(args.repo_structure).exists():
        repo_structure = Path(args.repo_structure).read_text(encoding='utf-8').split('\n')
        print(f"[INFO] Loaded repo structure ({len(repo_structure)} files)")
    
    # 生成计划
    plan = generate_issue_plan(
        issue_id=args.issue_id,
        issue_title=args.issue_title,
        issue_description=args.issue_description,
        project_context=project_context,
        repo_structure=repo_structure
    )
    
    # 输出计划
    plan_dict = plan_to_dict(plan)
    Path(args.output).write_text(json.dumps(plan_dict, indent=2, ensure_ascii=False), encoding='utf-8')
    
    print(f"[INFO] Generated issue plan:")
    print(f"  Issue: {plan.issue_title}")
    print(f"  Subtasks: {plan.total_subtasks}")
    print(f"  Estimated time: {plan.estimated_total_time_seconds}s")
    print(f"  Max concurrent: {plan.max_concurrent_tasks}")
    print(f"  Output: {args.output}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
