#!/usr/bin/env python3
"""
通用任务编排框架
支持任务规划、拆分、并行执行和结果聚合
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Callable, Any
from enum import Enum
from pathlib import Path
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskType(Enum):
    """任务类型"""
    MR_REVIEW = "mr_review"
    ISSUE_IMPLEMENT = "issue_implement"
    CODE_REFACTOR = "code_refactor"
    CUSTOM = "custom"


@dataclass
class SubTask:
    """子任务定义"""
    id: str
    title: str
    description: str
    
    # 任务配置
    task_type: str = "generic"  # review, code, test, doc, etc.
    priority: int = 5  # 1-10, 10最高
    
    # 资源限制
    estimated_tokens: int = 5000
    estimated_time_seconds: int = 300
    max_diff_size_bytes: int = 100 * 1024  # 100KB
    
    # 依赖关系
    depends_on: List[str] = field(default_factory=list)
    
    # 执行范围（用于过滤）
    file_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    
    # 执行状态
    status: TaskStatus = TaskStatus.PENDING
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # 自定义数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        d = asdict(self)
        d['status'] = self.status.value
        return d
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SubTask':
        """从字典创建"""
        data = data.copy()
        if 'status' in data:
            data['status'] = TaskStatus(data['status'])
        return cls(**data)


@dataclass
class TaskPlan:
    """任务执行计划"""
    task_id: str
    task_type: str
    title: str
    description: str
    
    # 子任务列表
    subtasks: List[SubTask] = field(default_factory=list)
    
    # 全局配置
    max_total_tokens: int = 150000
    max_execution_time_seconds: int = 3600
    max_concurrent_tasks: int = 3
    batch_size: int = 5
    
    # 执行策略
    enable_parallel: bool = True
    fail_fast: bool = False  # True: 任意失败则停止；False: 继续执行其他任务
    
    # 元数据
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_json(self, indent: int = 2) -> str:
        """序列化为JSON"""
        return json.dumps({
            'task_id': self.task_id,
            'task_type': self.task_type,
            'title': self.title,
            'description': self.description,
            'subtasks': [st.to_dict() for st in self.subtasks],
            'max_total_tokens': self.max_total_tokens,
            'max_execution_time_seconds': self.max_execution_time_seconds,
            'max_concurrent_tasks': self.max_concurrent_tasks,
            'batch_size': self.batch_size,
            'enable_parallel': self.enable_parallel,
            'fail_fast': self.fail_fast,
            'created_at': self.created_at,
            'metadata': self.metadata
        }, indent=indent)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'TaskPlan':
        """从JSON反序列化"""
        data = json.loads(json_str)
        subtasks = [SubTask.from_dict(st) for st in data.pop('subtasks', [])]
        return cls(subtasks=subtasks, **data)
    
    def save(self, path: Path) -> None:
        """保存到文件"""
        path.write_text(self.to_json(), encoding='utf-8')
        logger.info(f"Task plan saved to {path}")
    
    @classmethod
    def load(cls, path: Path) -> 'TaskPlan':
        """从文件加载"""
        logger.info(f"Loading task plan from {path}")
        return cls.from_json(path.read_text(encoding='utf-8'))


class TaskExecutor:
    """任务执行器 - 支持依赖管理和并行执行"""
    
    def __init__(
        self,
        plan: TaskPlan,
        task_handlers: Dict[str, Callable[[SubTask], Dict]]
    ):
        """
        初始化执行器
        
        Args:
            plan: 任务计划
            task_handlers: 任务类型到处理函数的映射
                           例如: {'review': handle_review_task, 'code': handle_code_task}
        """
        self.plan = plan
        self.task_handlers = task_handlers
        self.executor = ThreadPoolExecutor(max_workers=plan.max_concurrent_tasks)
        
    def can_execute(self, subtask: SubTask) -> bool:
        """检查子任务是否可以执行（依赖已完成）"""
        if subtask.status != TaskStatus.PENDING:
            return False
        
        for dep_id in subtask.depends_on:
            dep_task = self._find_subtask(dep_id)
            if not dep_task:
                logger.warning(f"Dependency {dep_id} not found for task {subtask.id}")
                return False
            if dep_task.status != TaskStatus.COMPLETED:
                return False
        return True
    
    def _find_subtask(self, task_id: str) -> Optional[SubTask]:
        """查找子任务"""
        for st in self.plan.subtasks:
            if st.id == task_id:
                return st
        return None
    
    def execute_subtask(self, subtask: SubTask) -> Dict:
        """执行单个子任务"""
        logger.info(f"Executing subtask: {subtask.id} - {subtask.title}")
        subtask.status = TaskStatus.RUNNING
        subtask.start_time = time.time()
        
        try:
            # 根据任务类型选择处理器
            handler = self.task_handlers.get(subtask.task_type)
            if not handler:
                handler = self.task_handlers.get('default')
            
            if not handler:
                raise ValueError(f"No handler found for task type: {subtask.task_type}")
            
            # 执行任务
            result = handler(subtask)
            
            subtask.status = TaskStatus.COMPLETED
            subtask.result = result
            subtask.end_time = time.time()
            
            elapsed = subtask.end_time - subtask.start_time
            logger.info(f"✓ Completed subtask {subtask.id} in {elapsed:.1f}s")
            
            return result
            
        except Exception as e:
            subtask.status = TaskStatus.FAILED
            subtask.error = str(e)
            subtask.end_time = time.time()
            
            logger.error(f"✗ Failed subtask {subtask.id}: {e}")
            
            if self.plan.fail_fast:
                raise
            
            return {'status': 'failed', 'error': str(e)}
    
    def execute_batch(self, batch: List[SubTask]) -> List[Dict]:
        """执行一批任务（并行或串行）"""
        if not self.plan.enable_parallel or len(batch) == 1:
            # 串行执行
            logger.info(f"Executing {len(batch)} tasks serially")
            return [self.execute_subtask(st) for st in batch]
        
        # 并行执行
        logger.info(f"Executing {len(batch)} tasks in parallel")
        futures = {
            self.executor.submit(self.execute_subtask, st): st
            for st in batch
        }
        
        results = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"Task execution error: {e}")
                if self.plan.fail_fast:
                    raise
                results.append({'status': 'failed', 'error': str(e)})
        
        return results
    
    def execute(self) -> Dict:
        """执行整个任务计划"""
        logger.info(f"=== Starting execution of plan: {self.plan.task_id} ===")
        logger.info(f"Total subtasks: {len(self.plan.subtasks)}")
        
        start_time = time.time()
        iteration = 0
        max_iterations = len(self.plan.subtasks) * 2  # 防止死循环
        
        while iteration < max_iterations:
            iteration += 1
            
            # 找出所有可以执行的任务
            ready_tasks = [st for st in self.plan.subtasks if self.can_execute(st)]
            
            if not ready_tasks:
                # 检查是否还有pending任务
                pending = [st for st in self.plan.subtasks if st.status == TaskStatus.PENDING]
                if pending:
                    logger.warning(f"{len(pending)} tasks are blocked by dependencies or failed")
                    for st in pending:
                        st.status = TaskStatus.SKIPPED
                        logger.warning(f"Skipped task: {st.id} - {st.title}")
                break
            
            # 按优先级排序，取前N个
            ready_tasks.sort(key=lambda x: (-x.priority, x.id))
            batch = ready_tasks[:self.plan.batch_size]
            
            logger.info(f"\n--- Batch {iteration}: {len(batch)} tasks ---")
            for st in batch:
                deps_str = f" (depends on: {', '.join(st.depends_on)})" if st.depends_on else ""
                logger.info(f"  • {st.id}: {st.title} [priority={st.priority}]{deps_str}")
            
            # 执行批次
            self.execute_batch(batch)
            
            # 检查是否超时
            elapsed = time.time() - start_time
            if elapsed > self.plan.max_execution_time_seconds:
                logger.warning(f"Execution timeout ({elapsed:.0f}s > {self.plan.max_execution_time_seconds}s)")
                break
        
        # 统计结果
        completed = sum(1 for st in self.plan.subtasks if st.status == TaskStatus.COMPLETED)
        failed = sum(1 for st in self.plan.subtasks if st.status == TaskStatus.FAILED)
        skipped = sum(1 for st in self.plan.subtasks if st.status == TaskStatus.SKIPPED)
        
        elapsed = time.time() - start_time
        
        logger.info(f"\n=== Execution Summary ===")
        logger.info(f"Completed: {completed}/{len(self.plan.subtasks)}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Skipped: {skipped}")
        logger.info(f"Total time: {elapsed:.1f}s")
        
        return {
            'status': 'completed' if failed == 0 else 'partial_success',
            'total': len(self.plan.subtasks),
            'completed': completed,
            'failed': failed,
            'skipped': skipped,
            'elapsed_seconds': elapsed,
            'iterations': iteration,
            'subtasks': [st.to_dict() for st in self.plan.subtasks]
        }
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.executor.shutdown(wait=True)


class TaskAggregator:
    """任务结果聚合器"""
    
    def __init__(self, plan: TaskPlan, execution_result: Dict):
        self.plan = plan
        self.execution_result = execution_result
    
    def aggregate(self, aggregators: Dict[str, Callable]) -> Dict:
        """
        聚合结果
        
        Args:
            aggregators: 任务类型到聚合函数的映射
                        例如: {'review': aggregate_review_results}
        """
        aggregated = {
            'execution_summary': self.execution_result,
            'task_info': {
                'task_id': self.plan.task_id,
                'task_type': self.plan.task_type,
                'title': self.plan.title
            },
            'results_by_type': {}
        }
        
        # 按任务类型分组
        tasks_by_type = {}
        for subtask_dict in self.execution_result['subtasks']:
            subtask = SubTask.from_dict(subtask_dict)
            task_type = subtask.task_type
            
            if task_type not in tasks_by_type:
                tasks_by_type[task_type] = []
            tasks_by_type[task_type].append(subtask)
        
        # 对每种类型调用对应的聚合器
        for task_type, subtasks in tasks_by_type.items():
            aggregator = aggregators.get(task_type) or aggregators.get('default')
            if aggregator:
                try:
                    aggregated['results_by_type'][task_type] = aggregator(subtasks)
                except Exception as e:
                    logger.error(f"Aggregation failed for type {task_type}: {e}")
                    aggregated['results_by_type'][task_type] = {
                        'error': str(e),
                        'task_count': len(subtasks)
                    }
        
        return aggregated
    
    def generate_summary_markdown(self, aggregated_results: Dict) -> str:
        """生成Markdown格式的摘要"""
        exec_summary = aggregated_results['execution_summary']
        task_info = aggregated_results['task_info']
        
        md = f"""## 🤖 任务执行报告

### 基本信息
- **任务ID**: `{task_info['task_id']}`
- **任务类型**: {task_info['task_type']}
- **任务标题**: {task_info['title']}

### 执行统计
- ✅ 成功: {exec_summary['completed']} 个
- ❌ 失败: {exec_summary['failed']} 个
- ⏭️  跳过: {exec_summary['skipped']} 个
- 📊 总计: {exec_summary['total']} 个子任务
- ⏱️  耗时: {exec_summary['elapsed_seconds']:.1f} 秒

"""
        
        # 添加各类型的详细结果
        if aggregated_results.get('results_by_type'):
            md += "### 详细结果\n\n"
            for task_type, results in aggregated_results['results_by_type'].items():
                md += f"#### {task_type.upper()}\n"
                if isinstance(results, dict):
                    for key, value in results.items():
                        if key != 'details':  # 跳过详细信息
                            md += f"- **{key}**: {value}\n"
                md += "\n"
        
        return md


if __name__ == '__main__':
    # 示例用法
    print("Task Framework loaded. Use this module to build task orchestration systems.")
