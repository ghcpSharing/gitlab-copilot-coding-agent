"""CLI 入口点

用法:
    python -m project_understanding.cli [OPTIONS] [WORKSPACE]
    
示例:
    # 分析当前目录
    python -m project_understanding.cli
    
    # 分析指定目录
    python -m project_understanding.cli /path/to/project
    
    # 指定输出目录
    python -m project_understanding.cli --output-dir .analysis
    
    # 禁用 Review
    python -m project_understanding.cli --no-review
"""

import argparse
import logging
import sys
from pathlib import Path

from .orchestrator import Orchestrator, OrchestratorConfig


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 降低第三方库日志级别
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Project Understanding - 分析项目结构，生成代码审查上下文',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                          分析当前目录
  %(prog)s /path/to/project         分析指定项目
  %(prog)s --no-review              禁用质量校验
  %(prog)s --output-dir .analysis   自定义输出目录
  %(prog)s -v                       详细输出

环境变量:
  COPILOT_TIMEOUT     Copilot 调用超时时间（秒，默认 120）
  COPILOT_MODEL       使用的模型（默认 claude-sonnet-4）
  CI_PROJECT_ID       GitLab 项目 ID
  CI_COMMIT_REF_NAME  分支名
  CI_COMMIT_SHA       Commit SHA
"""
    )
    
    parser.add_argument(
        'workspace',
        nargs='?',
        default='.',
        help='项目目录路径（默认: 当前目录）'
    )
    
    parser.add_argument(
        '-o', '--output-dir',
        default='.copilot',
        help='输出目录（默认: .copilot）'
    )
    
    parser.add_argument(
        '--output-file',
        default='context.md',
        help='输出文件名（默认: context.md）'
    )
    
    parser.add_argument(
        '--no-review',
        action='store_true',
        help='禁用 Reviewer 质量校验'
    )
    
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='禁用缓存'
    )
    
    parser.add_argument(
        '--max-tokens',
        type=int,
        default=4000,
        help='最大输出 token 数（默认: 4000）'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=120,
        help='Copilot 调用超时时间（秒，默认: 120）'
    )
    
    parser.add_argument(
        '--model',
        default='claude-sonnet-4',
        help='使用的模型（默认: claude-sonnet-4）'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='详细输出'
    )
    
    parser.add_argument(
        '--repo-id',
        default='',
        help='GitLab 仓库 ID（也可通过 CI_PROJECT_ID 环境变量设置）'
    )
    
    parser.add_argument(
        '--branch',
        default='',
        help='分支名（也可通过 CI_COMMIT_REF_NAME 环境变量设置）'
    )
    
    parser.add_argument(
        '--commit',
        default='',
        help='Commit SHA（也可通过 CI_COMMIT_SHA 环境变量设置）'
    )
    
    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()
    
    # 配置日志
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # 获取工作目录
    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        logger.error(f"Workspace not found: {workspace}")
        sys.exit(1)
    
    if not workspace.is_dir():
        logger.error(f"Workspace is not a directory: {workspace}")
        sys.exit(1)
    
    # 从环境变量获取 GitLab 信息
    import os
    repo_id = args.repo_id or os.environ.get('CI_PROJECT_ID', '')
    branch = args.branch or os.environ.get('CI_COMMIT_REF_NAME', '')
    commit_sha = args.commit or os.environ.get('CI_COMMIT_SHA', '')
    
    # 创建配置
    config = OrchestratorConfig(
        agent_timeout=args.timeout,
        agent_model=args.model,
        enable_review=not args.no_review,
        enable_cache=not args.no_cache,
        output_dir=args.output_dir,
        output_file=args.output_file,
        max_context_tokens=args.max_tokens
    )
    
    # 创建编排器
    orchestrator = Orchestrator(
        workspace=workspace,
        config=config,
        repo_id=repo_id,
        branch=branch,
        commit_sha=commit_sha
    )
    
    try:
        # 执行分析
        logger.info(f"Analyzing project: {workspace}")
        context = orchestrator.run()
        
        # 输出摘要
        logger.info("=" * 60)
        logger.info("Analysis Summary:")
        logger.info(f"  Token count: {context.token_count}")
        logger.info(f"  Analysis time: {context.analysis_time_ms}ms")
        logger.info(f"  Output: {workspace / args.output_dir / args.output_file}")
        logger.info("=" * 60)
        
        # 成功退出
        sys.exit(0)
        
    except KeyboardInterrupt:
        logger.info("Analysis interrupted")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Analysis failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
