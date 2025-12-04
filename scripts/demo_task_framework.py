#!/usr/bin/env python3
"""
快速测试任务编排框架
"""
import sys
from pathlib import Path

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from task_framework import TaskPlan, SubTask, TaskExecutor, TaskAggregator, TaskStatus
import json
import time


def demo_simple_workflow():
    """演示简单的工作流"""
    print("=== 演示：简单任务工作流 ===\n")
    
    # 创建任务计划
    plan = TaskPlan(
        task_id="demo-001",
        task_type="demo",
        title="演示任务编排",
        description="展示框架的基本功能",
        max_concurrent_tasks=2,
        enable_parallel=True
    )
    
    # 添加子任务
    plan.subtasks = [
        SubTask(
            id="task-1",
            title="第一步：初始化",
            description="准备工作环境",
            task_type="setup",
            priority=10
        ),
        SubTask(
            id="task-2a",
            title="第二步A：处理模块A",
            description="并行任务A",
            task_type="process",
            priority=8,
            depends_on=["task-1"]
        ),
        SubTask(
            id="task-2b",
            title="第二步B：处理模块B",
            description="并行任务B",
            task_type="process",
            priority=8,
            depends_on=["task-1"]
        ),
        SubTask(
            id="task-3",
            title="第三步：汇总结果",
            description="合并所有结果",
            task_type="aggregate",
            priority=5,
            depends_on=["task-2a", "task-2b"]
        )
    ]
    
    # 打印计划
    print("任务计划：")
    print(f"- 任务ID: {plan.task_id}")
    print(f"- 子任务数: {len(plan.subtasks)}")
    print(f"- 最大并发: {plan.max_concurrent_tasks}")
    print()
    
    # 定义任务处理器
    def handle_task(subtask: SubTask):
        """模拟任务执行"""
        print(f"  执行中: {subtask.id} - {subtask.title}")
        time.sleep(1)  # 模拟工作
        return {
            'status': 'success',
            'message': f'{subtask.title} 完成',
            'data': f'Result of {subtask.id}'
        }
    
    task_handlers = {
        'setup': handle_task,
        'process': handle_task,
        'aggregate': handle_task,
        'default': handle_task
    }
    
    # 执行任务
    print("开始执行...\n")
    with TaskExecutor(plan, task_handlers) as executor:
        result = executor.execute()
    
    print("\n执行结果：")
    print(f"- 总计: {result['total']}")
    print(f"- 成功: {result['completed']}")
    print(f"- 失败: {result['failed']}")
    print(f"- 耗时: {result['elapsed_seconds']:.1f}秒")
    
    return plan, result


def demo_mr_review_plan():
    """演示MR审查计划生成"""
    print("\n\n=== 演示：MR审查计划 ===\n")
    
    # 模拟大型MR
    plan = TaskPlan(
        task_id="mr-review-456",
        task_type="mr_review",
        title="Review Large MR",
        description="审查包含100+文件的大型MR",
        max_concurrent_tasks=3
    )
    
    # 模拟不同类别的审查任务
    categories = [
        ('critical', 10, 5),   # (类别, 优先级, 文件数)
        ('source', 8, 40),
        ('test', 6, 30),
        ('doc', 4, 15),
        ('config', 7, 10)
    ]
    
    for category, priority, file_count in categories:
        plan.subtasks.append(SubTask(
            id=f"review-{category}",
            title=f"审查{category}文件",
            description=f"审查{file_count}个{category}文件",
            task_type="review",
            priority=priority,
            estimated_tokens=file_count * 1000,
            metadata={'category': category, 'file_count': file_count}
        ))
    
    # 打印计划
    print("MR审查任务计划：")
    print(f"任务数: {len(plan.subtasks)}")
    print("\n子任务列表（按优先级排序）：")
    
    sorted_tasks = sorted(plan.subtasks, key=lambda x: -x.priority)
    for task in sorted_tasks:
        print(f"  [{task.priority:2d}] {task.id:20s} - {task.title:30s} ({task.metadata['file_count']} files)")
    
    # 保存计划
    output_path = Path("/tmp/demo_mr_plan.json")
    plan.save(output_path)
    print(f"\n计划已保存到: {output_path}")
    
    # 显示JSON片段
    print("\nJSON结构示例：")
    plan_dict = json.loads(plan.to_json())
    print(json.dumps({
        'task_id': plan_dict['task_id'],
        'subtasks': [
            {
                'id': st['id'],
                'priority': st['priority'],
                'file_count': st['metadata']['file_count']
            }
            for st in plan_dict['subtasks'][:3]
        ],
        '...': f'... and {len(plan_dict["subtasks"]) - 3} more'
    }, indent=2, ensure_ascii=False))
    
    return plan


def demo_aggregation():
    """演示结果聚合"""
    print("\n\n=== 演示：结果聚合 ===\n")
    
    # 创建带结果的任务计划
    plan = TaskPlan(
        task_id="demo-agg",
        task_type="demo",
        title="聚合演示",
        description="展示如何聚合多个子任务的结果"
    )
    
    # 模拟已完成的子任务
    plan.subtasks = [
        SubTask(
            id=f"task-{i}",
            title=f"任务{i}",
            description="",
            task_type="review",
            status=TaskStatus.COMPLETED,
            result={
                'findings_count': i * 2,
                'findings': [
                    {'severity': 'critical' if j % 4 == 0 else 'major' if j % 3 == 0 else 'minor',
                     'file': f'file{i}.py',
                     'line': j * 10}
                    for j in range(i * 2)
                ]
            }
        )
        for i in range(1, 6)
    ]
    
    # 模拟执行结果
    execution_result = {
        'status': 'completed',
        'total': len(plan.subtasks),
        'completed': len(plan.subtasks),
        'failed': 0,
        'skipped': 0,
        'elapsed_seconds': 45.5,
        'subtasks': [st.to_dict() for st in plan.subtasks]
    }
    
    # 自定义聚合函数
    def aggregate_review_results(subtasks):
        total_findings = sum(st.result.get('findings_count', 0) for st in subtasks)
        all_findings = []
        severity_count = {'critical': 0, 'major': 0, 'minor': 0}
        
        for st in subtasks:
            findings = st.result.get('findings', [])
            all_findings.extend(findings)
            for f in findings:
                sev = f.get('severity', 'minor')
                if sev in severity_count:
                    severity_count[sev] += 1
        
        return {
            'total_findings': total_findings,
            'severity_stats': severity_count,
            'files_reviewed': len(subtasks)
        }
    
    # 执行聚合
    aggregator = TaskAggregator(plan, execution_result)
    aggregated = aggregator.aggregate({
        'review': aggregate_review_results,
        'default': lambda sts: {'count': len(sts)}
    })
    
    # 显示结果
    print("聚合结果：")
    print(json.dumps(aggregated['results_by_type']['review'], indent=2, ensure_ascii=False))
    
    # 生成Markdown摘要
    print("\nMarkdown摘要：")
    print("─" * 50)
    summary = aggregator.generate_summary_markdown(aggregated)
    print(summary)
    print("─" * 50)
    
    return aggregated


def main():
    """运行所有演示"""
    print("=" * 60)
    print("  任务编排框架 - 功能演示")
    print("=" * 60)
    print()
    
    try:
        # 演示1：简单工作流
        demo_simple_workflow()
        
        # 演示2：MR审查计划
        demo_mr_review_plan()
        
        # 演示3：结果聚合
        demo_aggregation()
        
        print("\n" + "=" * 60)
        print("  ✅ 所有演示完成")
        print("=" * 60)
        print("\n下一步：")
        print("1. 查看 docs/TASK_ORCHESTRATION.md 了解详细用法")
        print("2. 运行 ./scripts/mr_review_orchestrated.sh 进行实际MR审查")
        print("3. 自定义任务处理器以适应你的需求")
        
        return 0
        
    except Exception as e:
        print(f"\n[ERROR] 演示失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
