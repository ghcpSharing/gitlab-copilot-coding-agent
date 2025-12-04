#!/usr/bin/env python3
"""
MR Review任务规划器
根据MR的规模和复杂度，智能生成review任务计划
"""
import sys
import os
import subprocess
import json
import re
from pathlib import Path
from typing import List, Dict, Tuple
from task_framework import TaskPlan, SubTask, TaskType

# 配置常量
MAX_DIFF_SIZE_PER_TASK = 100 * 1024  # 100KB per subtask
MAX_FILES_PER_TASK = 20
CRITICAL_FILE_PATTERNS = [
    r'.*/(auth|security|crypto|password|token).*',
    r'.*/api/.*',
    r'.*\.sql$',
    r'.*/middleware/.*'
]
EXCLUDE_PATTERNS = [
    r'.*/node_modules/.*',
    r'.*/vendor/.*',
    r'.*\.min\.js$',
    r'.*\.lock$',
    r'.*/dist/.*',
    r'.*/build/.*',
    r'.*/__pycache__/.*'
]


def get_git_diff_stats(base_branch: str, head_branch: str) -> Dict:
    """获取git diff统计信息"""
    # 获取变更的文件列表
    result = subprocess.run(
        ['git', 'diff', '--name-only', f'{base_branch}...{head_branch}'],
        capture_output=True,
        text=True,
        check=True
    )
    changed_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
    
    # 获取完整diff大小
    result = subprocess.run(
        ['git', 'diff', f'{base_branch}...{head_branch}'],
        capture_output=True,
        text=True,
        check=True
    )
    total_diff_size = len(result.stdout.encode('utf-8'))
    
    # 获取每个文件的变更统计
    result = subprocess.run(
        ['git', 'diff', '--numstat', f'{base_branch}...{head_branch}'],
        capture_output=True,
        text=True,
        check=True
    )
    
    file_stats = {}
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) >= 3:
            added, removed, filepath = parts[0], parts[1], parts[2]
            try:
                file_stats[filepath] = {
                    'added': int(added) if added != '-' else 0,
                    'removed': int(removed) if removed != '-' else 0
                }
            except ValueError:
                # Binary files show '-' for stats
                file_stats[filepath] = {'added': 0, 'removed': 0, 'binary': True}
    
    return {
        'total_files': len(changed_files),
        'total_diff_size': total_diff_size,
        'changed_files': changed_files,
        'file_stats': file_stats
    }


def categorize_files(files: List[str]) -> Dict[str, List[str]]:
    """将文件分类"""
    categories = {
        'critical': [],      # 安全、认证相关
        'source': [],        # 源代码
        'test': [],          # 测试文件
        'doc': [],           # 文档
        'config': [],        # 配置文件
        'other': []          # 其他
    }
    
    for file in files:
        # 检查是否应该排除
        if any(re.match(pattern, file) for pattern in EXCLUDE_PATTERNS):
            continue
        
        # 检查是否是关键文件
        if any(re.match(pattern, file) for pattern in CRITICAL_FILE_PATTERNS):
            categories['critical'].append(file)
        elif re.match(r'.*/(test|spec|__tests__).*', file) or file.endswith(('_test.py', '_test.go', '.test.js', '.spec.ts')):
            categories['test'].append(file)
        elif file.endswith(('.md', '.rst', '.txt', '.adoc')):
            categories['doc'].append(file)
        elif file.endswith(('.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.xml')):
            categories['config'].append(file)
        elif file.endswith(('.py', '.js', '.ts', '.go', '.java', '.rb', '.php', '.cpp', '.c', '.h', '.rs', '.swift')):
            categories['source'].append(file)
        else:
            categories['other'].append(file)
    
    return categories


def chunk_files(files: List[str], file_stats: Dict, max_files: int, max_size: int) -> List[List[str]]:
    """将文件列表分块，考虑文件大小"""
    chunks = []
    current_chunk = []
    current_size = 0
    
    for file in files:
        stats = file_stats.get(file, {})
        # 估算diff大小（每行约100字节）
        file_size = (stats.get('added', 0) + stats.get('removed', 0)) * 100
        
        if len(current_chunk) >= max_files or (current_size + file_size > max_size and current_chunk):
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        
        current_chunk.append(file)
        current_size += file_size
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def create_review_plan(
    mr_iid: str,
    mr_title: str,
    base_branch: str,
    head_branch: str,
    mr_description: str = ""
) -> TaskPlan:
    """
    创建MR Review执行计划
    
    根据MR的规模自动拆分为多个子任务：
    - 小型MR（<10文件，<500行）：单个任务
    - 中型MR（10-50文件，500-2000行）：按类别拆分
    - 大型MR（>50文件，>2000行）：按类别+文件分块拆分
    """
    print(f"[INFO] Analyzing MR #{mr_iid}: {mr_title}")
    
    # 获取diff统计
    stats = get_git_diff_stats(base_branch, head_branch)
    total_files = stats['total_files']
    total_size = stats['total_diff_size']
    
    print(f"[INFO] Total files changed: {total_files}")
    print(f"[INFO] Total diff size: {total_size} bytes ({total_size/1024:.1f} KB)")
    
    # 创建任务计划
    task_plan = TaskPlan(
        task_id=f"mr-review-{mr_iid}",
        task_type=TaskType.MR_REVIEW.value,
        title=f"Review MR #{mr_iid}: {mr_title}",
        description=mr_description or f"Automated review of merge request #{mr_iid}",
        metadata={
            'mr_iid': mr_iid,
            'mr_title': mr_title,
            'base_branch': base_branch,
            'head_branch': head_branch,
            'total_files': total_files,
            'total_diff_size': total_size
        }
    )
    
    # 判断MR规模
    if total_files <= 10 and total_size < 500 * 1024:
        # 小型MR - 单个任务
        print("[INFO] Small MR detected - creating single review task")
        task_plan.subtasks.append(SubTask(
            id="review-all",
            title="Review all changes",
            description=f"Review all {total_files} changed files",
            task_type="review",
            priority=10,
            estimated_tokens=min(total_size // 4, 50000),  # 粗略估算
            file_patterns=stats['changed_files']
        ))
    
    else:
        # 中大型MR - 拆分任务
        print("[INFO] Large MR detected - splitting into multiple review tasks")
        
        # 按类别分组文件
        categorized = categorize_files(stats['changed_files'])
        
        subtask_id = 1
        
        # 优先审查关键文件
        if categorized['critical']:
            print(f"[INFO] Found {len(categorized['critical'])} critical files")
            chunks = chunk_files(
                categorized['critical'],
                stats['file_stats'],
                MAX_FILES_PER_TASK,
                MAX_DIFF_SIZE_PER_TASK
            )
            
            for i, chunk in enumerate(chunks):
                task_plan.subtasks.append(SubTask(
                    id=f"review-critical-{subtask_id}",
                    title=f"Review critical files (batch {i+1}/{len(chunks)})",
                    description=f"Review security-sensitive files: {', '.join(chunk[:3])}{'...' if len(chunk) > 3 else ''}",
                    task_type="review",
                    priority=10,
                    estimated_tokens=len(chunk) * 2000,
                    file_patterns=chunk,
                    metadata={'category': 'critical', 'file_count': len(chunk)}
                ))
                subtask_id += 1
        
        # 审查源代码
        if categorized['source']:
            print(f"[INFO] Found {len(categorized['source'])} source files")
            chunks = chunk_files(
                categorized['source'],
                stats['file_stats'],
                MAX_FILES_PER_TASK,
                MAX_DIFF_SIZE_PER_TASK
            )
            
            for i, chunk in enumerate(chunks):
                task_plan.subtasks.append(SubTask(
                    id=f"review-source-{subtask_id}",
                    title=f"Review source code (batch {i+1}/{len(chunks)})",
                    description=f"Review source files: {', '.join(chunk[:3])}{'...' if len(chunk) > 3 else ''}",
                    task_type="review",
                    priority=8,
                    estimated_tokens=len(chunk) * 2000,
                    file_patterns=chunk,
                    metadata={'category': 'source', 'file_count': len(chunk)}
                ))
                subtask_id += 1
        
        # 审查测试
        if categorized['test']:
            print(f"[INFO] Found {len(categorized['test'])} test files")
            task_plan.subtasks.append(SubTask(
                id=f"review-tests",
                title="Review test files",
                description=f"Review test coverage and quality ({len(categorized['test'])} files)",
                task_type="review",
                priority=6,
                estimated_tokens=len(categorized['test']) * 1000,
                file_patterns=categorized['test'],
                metadata={'category': 'test', 'file_count': len(categorized['test'])}
            ))
        
        # 审查文档
        if categorized['doc']:
            print(f"[INFO] Found {len(categorized['doc'])} documentation files")
            task_plan.subtasks.append(SubTask(
                id=f"review-docs",
                title="Review documentation",
                description=f"Review documentation updates ({len(categorized['doc'])} files)",
                task_type="review",
                priority=4,
                estimated_tokens=len(categorized['doc']) * 500,
                file_patterns=categorized['doc'],
                metadata={'category': 'doc', 'file_count': len(categorized['doc'])}
            ))
        
        # 审查配置文件
        if categorized['config']:
            print(f"[INFO] Found {len(categorized['config'])} config files")
            task_plan.subtasks.append(SubTask(
                id=f"review-config",
                title="Review configuration changes",
                description=f"Review config file changes ({len(categorized['config'])} files)",
                task_type="review",
                priority=7,
                estimated_tokens=len(categorized['config']) * 500,
                file_patterns=categorized['config'],
                metadata={'category': 'config', 'file_count': len(categorized['config'])}
            ))
        
        # 其他文件
        if categorized['other']:
            print(f"[INFO] Found {len(categorized['other'])} other files")
            task_plan.subtasks.append(SubTask(
                id=f"review-other",
                title="Review other changes",
                description=f"Review miscellaneous files ({len(categorized['other'])} files)",
                task_type="review",
                priority=3,
                estimated_tokens=len(categorized['other']) * 500,
                file_patterns=categorized['other'],
                metadata={'category': 'other', 'file_count': len(categorized['other'])}
            ))
    
    # 设置并发参数
    if len(task_plan.subtasks) <= 3:
        task_plan.max_concurrent_tasks = len(task_plan.subtasks)
    else:
        task_plan.max_concurrent_tasks = 3
    
    task_plan.batch_size = min(5, len(task_plan.subtasks))
    
    print(f"[INFO] Created plan with {len(task_plan.subtasks)} review subtasks")
    print(f"[INFO] Max concurrent tasks: {task_plan.max_concurrent_tasks}")
    
    return task_plan


def main():
    """主函数 - 从命令行参数或环境变量读取配置"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate MR Review Task Plan')
    parser.add_argument('--mr-iid', required=True, help='Merge Request IID')
    parser.add_argument('--mr-title', required=True, help='Merge Request Title')
    parser.add_argument('--base-branch', default='main', help='Base branch')
    parser.add_argument('--head-branch', required=True, help='Head branch')
    parser.add_argument('--mr-description', default='', help='MR Description')
    parser.add_argument('--output', default='task_plan.json', help='Output file path')
    
    args = parser.parse_args()
    
    try:
        # 生成计划
        plan = create_review_plan(
            mr_iid=args.mr_iid,
            mr_title=args.mr_title,
            base_branch=args.base_branch,
            head_branch=args.head_branch,
            mr_description=args.mr_description
        )
        
        # 保存计划
        output_path = Path(args.output)
        plan.save(output_path)
        
        print(f"\n[SUCCESS] Task plan saved to {output_path}")
        print(f"[INFO] Run task executor to execute the plan")
        
        return 0
        
    except Exception as e:
        print(f"[ERROR] Failed to generate task plan: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
