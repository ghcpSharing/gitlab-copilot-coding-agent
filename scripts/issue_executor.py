#!/usr/bin/env python3
"""
Issue 任务执行器
执行由 issue_planner.py 生成的任务计划
"""
import sys
import os
import subprocess
import json
import time
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass
class SubTaskResult:
    """子任务执行结果"""
    task_id: str
    status: str  # success, failed, timeout
    output: str
    artifacts: Dict
    duration_seconds: float
    error: Optional[str] = None


def load_project_context(workspace: Path) -> Optional[str]:
    """加载项目理解上下文"""
    context_paths = [
        workspace / ".copilot" / "project_context.md",
        workspace / ".copilot" / "context.md",
    ]
    
    for path in context_paths:
        if path.exists():
            content = path.read_text(encoding='utf-8')
            print(f"[INFO] Loaded project context from {path} ({len(content)} chars)")
            return content
    
    return None


def build_subtask_prompt(
    subtask: Dict,
    workspace: Path,
    project_context: Optional[str],
    previous_results: Dict[str, SubTaskResult],
    issue_title: str,
    issue_description: str
) -> str:
    """构建子任务的 prompt"""
    
    prompt_parts = []
    
    # 添加项目上下文
    if project_context:
        prompt_parts.append(f"""## 项目上下文（AI 分析生成）

以下是项目的技术架构和代码结构分析：

{project_context[:8000]}

---
""")
    
    # 添加 Issue 信息
    prompt_parts.append(f"""## Issue 信息

**标题**: {issue_title}

**描述**:
{issue_description[:3000]}

---
""")
    
    # 添加前置任务结果
    if subtask.get('dependencies'):
        prompt_parts.append("## 前置任务结果\n")
        for dep_id in subtask['dependencies']:
            if dep_id in previous_results:
                result = previous_results[dep_id]
                prompt_parts.append(f"""### {dep_id}
状态: {result.status}
输出摘要:
{result.output[:2000] if result.output else '无输出'}

""")
    
    # 添加当前任务描述
    prompt_parts.append(f"""## 当前任务

**任务ID**: {subtask['id']}
**任务类型**: {subtask['task_type']}
**标题**: {subtask['title']}

{subtask['description']}

---

**重要提示**:
1. 你正在仓库目录 `{workspace}` 中工作
2. 请直接创建/修改文件，不要只输出代码块
3. 完成后请简要总结你做了什么

开始执行任务：
""")
    
    return '\n'.join(prompt_parts)


def execute_subtask(
    subtask: Dict,
    workspace: Path,
    project_context: Optional[str],
    previous_results: Dict[str, SubTaskResult],
    issue_title: str,
    issue_description: str
) -> SubTaskResult:
    """执行单个子任务"""
    
    task_id = subtask['id']
    start_time = time.time()
    
    print(f"\n[INFO] Starting subtask: {task_id} - {subtask['title']}")
    
    # 创建子任务工作目录
    subtask_dir = workspace / f".copilot_tasks" / task_id
    subtask_dir.mkdir(parents=True, exist_ok=True)
    
    # 构建 prompt
    prompt = build_subtask_prompt(
        subtask, workspace, project_context, 
        previous_results, issue_title, issue_description
    )
    
    # 保存 prompt
    prompt_file = subtask_dir / "prompt.txt"
    prompt_file.write_text(prompt, encoding='utf-8')
    
    print(f"[INFO] Prompt size: {len(prompt)} chars")
    
    # 调用 Copilot
    try:
        result = subprocess.run(
            ['copilot', '--allow-all-tools', '--allow-all-paths'],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=subtask.get('estimated_time_seconds', 600),
            cwd=workspace
        )
        
        output = result.stdout
        
        # 保存输出
        (subtask_dir / "output.txt").write_text(output, encoding='utf-8')
        
        if result.returncode != 0:
            print(f"[WARN] Copilot returned non-zero: {result.returncode}")
        
        # 检查是否有生成的文件
        artifacts = {}
        for artifact_name in ['analysis.json', 'architecture.json', 'implementation.json']:
            artifact_path = workspace / artifact_name
            if artifact_path.exists():
                try:
                    artifacts[artifact_name] = json.loads(artifact_path.read_text(encoding='utf-8'))
                except json.JSONDecodeError:
                    artifacts[artifact_name] = artifact_path.read_text(encoding='utf-8')
        
        duration = time.time() - start_time
        print(f"[SUCCESS] Subtask {task_id} completed in {duration:.1f}s")
        
        return SubTaskResult(
            task_id=task_id,
            status='success',
            output=output,
            artifacts=artifacts,
            duration_seconds=duration
        )
        
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        print(f"[ERROR] Subtask {task_id} timed out after {duration:.1f}s")
        return SubTaskResult(
            task_id=task_id,
            status='timeout',
            output='',
            artifacts={},
            duration_seconds=duration,
            error=f"Timeout after {subtask.get('estimated_time_seconds', 600)}s"
        )
    except Exception as e:
        duration = time.time() - start_time
        print(f"[ERROR] Subtask {task_id} failed: {e}")
        return SubTaskResult(
            task_id=task_id,
            status='failed',
            output='',
            artifacts={},
            duration_seconds=duration,
            error=str(e)
        )


def execute_plan(
    plan: Dict,
    workspace: Path,
    project_context: Optional[str],
    issue_title: str,
    issue_description: str
) -> Dict:
    """执行整个任务计划"""
    
    subtasks = plan['subtasks']
    max_concurrent = plan.get('max_concurrent_tasks', 1)
    
    print(f"\n[INFO] Executing plan with {len(subtasks)} subtasks")
    print(f"[INFO] Max concurrent tasks: {max_concurrent}")
    
    results: Dict[str, SubTaskResult] = {}
    pending_tasks = {s['id']: s for s in subtasks}
    completed_ids = set()
    
    total_start_time = time.time()
    
    while pending_tasks:
        # 找出可以执行的任务（依赖已完成）
        ready_tasks = []
        for task_id, task in pending_tasks.items():
            deps = set(task.get('dependencies', []))
            if deps.issubset(completed_ids):
                ready_tasks.append(task)
        
        if not ready_tasks:
            if pending_tasks:
                print(f"[ERROR] Deadlock detected! Pending: {list(pending_tasks.keys())}")
                break
        
        # 按优先级排序
        ready_tasks.sort(key=lambda t: t.get('priority', 999))
        
        # 限制并发数
        batch = ready_tasks[:max_concurrent]
        
        print(f"\n[INFO] Executing batch of {len(batch)} tasks: {[t['id'] for t in batch]}")
        
        # 串行执行（避免 Copilot CLI 并发问题）
        for task in batch:
            result = execute_subtask(
                task, workspace, project_context,
                results, issue_title, issue_description
            )
            results[task['id']] = result
            completed_ids.add(task['id'])
            del pending_tasks[task['id']]
    
    total_duration = time.time() - total_start_time
    
    # 统计结果
    success_count = sum(1 for r in results.values() if r.status == 'success')
    failed_count = sum(1 for r in results.values() if r.status in ['failed', 'timeout'])
    
    print(f"\n[INFO] Plan execution completed:")
    print(f"  Total time: {total_duration:.1f}s")
    print(f"  Success: {success_count}")
    print(f"  Failed: {failed_count}")
    
    return {
        'status': 'success' if failed_count == 0 else 'partial',
        'total_duration_seconds': total_duration,
        'success_count': success_count,
        'failed_count': failed_count,
        'results': {
            task_id: {
                'status': r.status,
                'duration_seconds': r.duration_seconds,
                'error': r.error,
                'artifacts': list(r.artifacts.keys())
            }
            for task_id, r in results.items()
        }
    }


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Issue Task Executor')
    parser.add_argument('--plan', required=True, help='Path to issue_plan.json')
    parser.add_argument('--workspace', required=True, help='Workspace directory')
    parser.add_argument('--issue-title', required=True, help='Issue title')
    parser.add_argument('--issue-description', required=True, help='Issue description')
    parser.add_argument('--output', default='execution_results.json', help='Output file')
    
    args = parser.parse_args()
    
    workspace = Path(args.workspace).resolve()
    
    # 加载计划
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    print(f"[INFO] Loaded plan for issue: {plan['issue_title']}")
    
    # 加载项目上下文
    project_context = load_project_context(workspace)
    
    # 执行计划
    results = execute_plan(
        plan=plan,
        workspace=workspace,
        project_context=project_context,
        issue_title=args.issue_title,
        issue_description=args.issue_description
    )
    
    # 保存结果
    Path(args.output).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n[INFO] Results saved to {args.output}")
    
    return 0 if results['status'] == 'success' else 1


if __name__ == '__main__':
    sys.exit(main())
