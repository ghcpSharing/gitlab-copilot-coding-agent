"""Orchestrator - 流程编排器

协调所有 Agent 的执行，支持并行执行
"""

import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import (
    AgentRole, AgentOutput, ReviewResult, ReviewStatus,
    ProjectContext, ScanResult, CacheMetadata
)
from .scanner import scan_project
from .copilot import CopilotClient
from .agents import AgentConfig
from .agents.tech_stack import TechStackAgent
from .agents.data_model import DataModelAgent
from .agents.domain import DomainAgent
from .agents.security import SecurityAgent
from .agents.api import APIAgent
from .agents.reviewer import ReviewerAgent
from .agents.synthesizer import SynthesizerAgent

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """编排器配置"""
    # Agent 配置
    agent_timeout: int = 3600  # Copilot 默认超时 1 小时
    agent_model: str = "claude-sonnet-4"
    agent_max_retries: int = 2
    
    # 并行配置
    parallel_agents: bool = True  # 是否并行执行专家 Agents
    max_workers: int = 5  # 最大并行数
    
    # Review 配置
    enable_review: bool = True  # 默认开启 Review
    max_review_iterations: int = 2
    
    # 输出配置
    output_dir: str = ".copilot"
    output_file: str = "context.md"
    max_context_tokens: int = 4000
    
    # 缓存配置
    enable_cache: bool = True
    cache_max_age_days: int = 7


class Orchestrator:
    """流程编排器
    
    协调以下流程：
    1. Scanner 扫描项目
    2. 专家 Agents 并行分析
    3. Reviewer 校验输出
    4. Synthesizer 合并压缩
    5. 输出最终上下文
    """
    
    def __init__(
        self,
        workspace: Path,
        config: Optional[OrchestratorConfig] = None,
        repo_id: str = "",
        branch: str = "",
        commit_sha: str = ""
    ):
        """初始化编排器
        
        Args:
            workspace: 项目根目录
            config: 编排器配置
            repo_id: GitLab 仓库 ID
            branch: 分支名
            commit_sha: Commit SHA
        """
        self.workspace = Path(workspace).resolve()
        self.config = config or OrchestratorConfig()
        self.repo_id = repo_id
        self.branch = branch
        self.commit_sha = commit_sha
        
        # 创建共享的 Copilot 客户端
        self.client = CopilotClient(
            timeout=self.config.agent_timeout,
            model=self.config.agent_model,
            max_retries=self.config.agent_max_retries
        )
        
        # Agent 配置
        self.agent_config = AgentConfig(
            max_retries=self.config.agent_max_retries,
            timeout=self.config.agent_timeout,
            model=self.config.agent_model
        )
        
        # 初始化 Agents
        self._init_agents()
        
        # 输出目录
        self.output_dir = self.workspace / self.config.output_dir
    
    def _init_agents(self):
        """初始化所有 Agents"""
        # 专家 Agents
        self.tech_stack_agent = TechStackAgent(self.agent_config, self.client)
        self.data_model_agent = DataModelAgent(self.agent_config, self.client)
        self.domain_agent = DomainAgent(self.agent_config, self.client)
        self.security_agent = SecurityAgent(self.agent_config, self.client)
        self.api_agent = APIAgent(self.agent_config, self.client)
        
        # Reviewer
        self.reviewer = ReviewerAgent(self.agent_config, self.client)
        
        # Synthesizer
        self.synthesizer = SynthesizerAgent(
            self.agent_config,
            self.client,
            max_context_tokens=self.config.max_context_tokens
        )
        
        # 专家 Agent 列表（按顺序执行）
        self.expert_agents = [
            self.tech_stack_agent,
            self.data_model_agent,
            self.domain_agent,
            self.security_agent,
            self.api_agent,
        ]
    
    def run(self) -> ProjectContext:
        """执行完整的分析流程
        
        Returns:
            ProjectContext: 项目上下文
        """
        start_time = time.time()
        logger.info(f"Starting project analysis for: {self.workspace}")
        
        # 检查缓存
        if self.config.enable_cache:
            cached = self._load_cache()
            if cached:
                logger.info("Using cached context")
                return cached
        
        # Phase 1: 扫描项目
        logger.info("Phase 1: Scanning project...")
        scan_result = scan_project(self.workspace)
        logger.info(f"  Found {scan_result.total_files} files, languages: {scan_result.languages}")
        
        # Phase 2: 专家分析（支持并行）
        logger.info("Phase 2: Running expert agents...")
        expert_outputs: list[AgentOutput] = []
        
        if self.config.parallel_agents:
            # 并行执行
            expert_outputs = self._run_agents_parallel(scan_result)
        else:
            # 顺序执行
            expert_outputs = self._run_agents_sequential(scan_result)
        
        # Phase 3: 合成
        logger.info("Phase 3: Synthesizing results...")
        synthesis_output = self.synthesizer.synthesize(expert_outputs, scan_result)
        
        # 构建 ProjectContext
        context = ProjectContext(
            repo_id=self.repo_id,
            branch=self.branch,
            commit_sha=self.commit_sha,
            tech_stack=self._find_output(expert_outputs, AgentRole.TECH_STACK),
            data_model=self._find_output(expert_outputs, AgentRole.DATA_MODEL),
            domain=self._find_output(expert_outputs, AgentRole.DOMAIN),
            security=self._find_output(expert_outputs, AgentRole.SECURITY),
            api_structure=self._find_output(expert_outputs, AgentRole.API),
            final_context=synthesis_output.content,
            token_count=self._estimate_tokens(synthesis_output.content),
            analysis_time_ms=int((time.time() - start_time) * 1000)
        )
        
        # Phase 4: 输出
        logger.info("Phase 4: Writing output...")
        self._write_output(context)
        
        # 缓存
        if self.config.enable_cache:
            self._save_cache(context)
        
        elapsed = time.time() - start_time
        logger.info(f"Analysis completed in {elapsed:.2f}s")
        
        return context
    
    def _find_output(
        self,
        outputs: list[AgentOutput],
        role: AgentRole
    ) -> Optional[AgentOutput]:
        """从输出列表中查找指定角色的输出"""
        for output in outputs:
            if output.agent == role:
                return output
        return None
    
    def _run_agents_sequential(self, scan_result: ScanResult) -> list[AgentOutput]:
        """顺序执行专家 Agents"""
        expert_outputs: list[AgentOutput] = []
        
        for agent in self.expert_agents:
            logger.info(f"  Running {agent.role.value}...")
            
            if self.config.enable_review:
                output = agent.analyze_with_review(
                    scan_result,
                    self.reviewer,
                    max_iterations=self.config.max_review_iterations
                )
            else:
                output = agent.analyze(scan_result)
            
            expert_outputs.append(output)
            
            # 立即写入文件
            self._write_agent_output(output)
            
            if output.success:
                logger.info(f"    ✓ {agent.role.value} completed and saved")
            else:
                logger.warning(f"    ✗ {agent.role.value} failed: {output.error}")
        
        return expert_outputs
    
    def _run_agents_parallel(self, scan_result: ScanResult) -> list[AgentOutput]:
        """并行执行专家 Agents"""
        expert_outputs: list[AgentOutput] = []
        
        def run_single_agent(agent) -> AgentOutput:
            """执行单个 Agent"""
            logger.info(f"  [Parallel] Starting {agent.role.value}...")
            try:
                if self.config.enable_review:
                    output = agent.analyze_with_review(
                        scan_result,
                        self.reviewer,
                        max_iterations=self.config.max_review_iterations
                    )
                else:
                    output = agent.analyze(scan_result)
                
                # 立即写入文件（线程安全）
                self._write_agent_output(output)
                
                if output.success:
                    logger.info(f"    ✓ [Parallel] {agent.role.value} completed and saved")
                else:
                    logger.warning(f"    ✗ [Parallel] {agent.role.value} failed: {output.error}")
                
                return output
            except Exception as e:
                logger.exception(f"    ✗ [Parallel] {agent.role.value} exception: {e}")
                return AgentOutput(
                    agent=agent.role,
                    content="",
                    raw_response="",
                    success=False,
                    error=str(e)
                )
        
        # 使用线程池并行执行
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # 提交所有任务
            futures = {
                executor.submit(run_single_agent, agent): agent 
                for agent in self.expert_agents
            }
            
            # 收集结果（按完成顺序）
            for future in as_completed(futures):
                agent = futures[future]
                try:
                    output = future.result()
                    expert_outputs.append(output)
                except Exception as e:
                    logger.error(f"  [Parallel] {agent.role.value} raised exception: {e}")
                    expert_outputs.append(AgentOutput(
                        agent=agent.role,
                        content="",
                        raw_response="",
                        success=False,
                        error=str(e)
                    ))
        
        return expert_outputs
    
    def _write_agent_output(self, output: AgentOutput):
        """写入单个 Agent 的输出（增量保存）"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 每个 Agent 单独的输出文件
        agent_file = self.output_dir / f"agent_{output.agent.value}.md"
        
        with open(agent_file, 'w', encoding='utf-8') as f:
            f.write(f"# {output.agent.value.replace('_', ' ').title()} Analysis\n\n")
            f.write(f"- Status: {'✓ Success' if output.success else '✗ Failed'}\n")
            f.write(f"- Retries: {output.retry_count}\n")
            if output.error:
                f.write(f"- Error: {output.error}\n")
            f.write(f"\n---\n\n")
            if output.content:
                f.write(output.content)
            else:
                f.write("_No content generated_")
        
        logger.debug(f"Agent output written to: {agent_file}")
    
    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数量（粗略估算）"""
        # 简单估算：平均 4 个字符一个 token
        return len(text) // 4
    
    def _write_output(self, context: ProjectContext):
        """写入输出文件"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = self.output_dir / self.config.output_file
        
        # 写入主上下文文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(context.final_context)
        
        logger.info(f"Context written to: {output_path}")
        
        # 写入详细分析（可选）
        details_path = self.output_dir / "context_details.md"
        with open(details_path, 'w', encoding='utf-8') as f:
            f.write("# Project Analysis Details\n\n")
            f.write(f"- Repo: {context.repo_id}\n")
            f.write(f"- Branch: {context.branch}\n")
            f.write(f"- Commit: {context.commit_sha}\n")
            f.write(f"- Analysis Time: {context.analysis_time_ms}ms\n")
            f.write(f"- Token Count: {context.token_count}\n\n")
            
            # 各 Agent 的详细输出
            for name, output in [
                ("Tech Stack", context.tech_stack),
                ("Data Model", context.data_model),
                ("Domain", context.domain),
                ("Security", context.security),
                ("API Structure", context.api_structure),
            ]:
                if output:
                    f.write(f"## {name}\n\n")
                    f.write(f"Status: {'✓' if output.success else '✗'}\n")
                    f.write(f"Retries: {output.retry_count}\n\n")
                    if output.content:
                        f.write(output.content)
                        f.write("\n\n")
    
    def _load_cache(self) -> Optional[ProjectContext]:
        """加载缓存的上下文"""
        cache_file = self.output_dir / "cache_metadata.json"
        context_file = self.output_dir / self.config.output_file
        
        if not cache_file.exists() or not context_file.exists():
            return None
        
        try:
            import json
            from datetime import datetime
            
            with open(cache_file, 'r') as f:
                meta_dict = json.load(f)
            
            # 检查是否是同一个 commit
            if meta_dict.get('commit_sha') != self.commit_sha:
                logger.info("Cache invalidated: commit changed")
                return None
            
            # 检查是否过期
            last_updated = datetime.fromisoformat(meta_dict['last_updated'])
            meta = CacheMetadata(
                repo_id=meta_dict['repo_id'],
                branch=meta_dict['branch'],
                commit_sha=meta_dict['commit_sha'],
                last_updated=last_updated
            )
            
            if meta.is_expired(self.config.cache_max_age_days):
                logger.info("Cache expired")
                return None
            
            # 读取缓存的上下文
            final_context = context_file.read_text(encoding='utf-8')
            
            return ProjectContext(
                repo_id=meta.repo_id,
                branch=meta.branch,
                commit_sha=meta.commit_sha,
                final_context=final_context,
                token_count=self._estimate_tokens(final_context)
            )
            
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            return None
    
    def _save_cache(self, context: ProjectContext):
        """保存缓存"""
        import json
        from datetime import datetime
        
        cache_file = self.output_dir / "cache_metadata.json"
        
        meta = {
            'repo_id': context.repo_id,
            'branch': context.branch,
            'commit_sha': context.commit_sha,
            'last_updated': datetime.now().isoformat(),
            'version': '1.0'
        }
        
        with open(cache_file, 'w') as f:
            json.dump(meta, f, indent=2)
    
    def run_incremental_update(
        self, 
        base_context_dir: Path, 
        changes_json_path: Path,
        update_modules: Optional[list[str]] = None
    ) -> ProjectContext:
        """
        执行增量更新
        
        Args:
            base_context_dir: 基准上下文目录（包含完整的 .copilot 内容）
            changes_json_path: changes.json 文件路径（来自 detect_changes.py）
            update_modules: 要更新的模块列表（None = 自动检测）
            
        Returns:
            更新后的 ProjectContext
        """
        import json
        
        logger.info("Starting incremental update...")
        
        # 1. 加载基准上下文
        base_context_file = base_context_dir / self.config.output_file
        if not base_context_file.exists():
            raise FileNotFoundError(f"Base context not found: {base_context_file}")
        
        base_context_text = base_context_file.read_text(encoding='utf-8')
        logger.info(f"Loaded base context from {base_context_file}")
        
        # 2. 加载变更信息
        with open(changes_json_path, 'r') as f:
            changes = json.load(f)
        
        base_commit = changes['base_commit']
        current_commit = changes['current_commit']
        affected_modules = set(changes['affected_modules'])
        
        logger.info(f"Detected changes: {base_commit[:8]}..{current_commit[:8]}")
        logger.info(f"Affected modules: {', '.join(affected_modules)}")
        
        # 3. 确定要更新的模块
        if update_modules is None:
            update_modules = list(affected_modules)
        else:
            # 确保请求的模块都在受影响列表中
            update_modules = [m for m in update_modules if m in affected_modules]
        
        if not update_modules:
            logger.warning("No modules to update")
            return self._create_context_from_base(base_context_text, base_commit, current_commit)
        
        logger.info(f"Will update modules: {', '.join(update_modules)}")
        
        # 4. 扫描项目（获取最新代码结构）
        scan_result = scan_project(self.workspace)
        
        # 5. 为每个待更新模块执行增量分析
        module_outputs = {}
        
        # 模块名到 Agent 的映射
        module_to_agent = {
            "tech_stack": TechStackAgent,
            "data_model": DataModelAgent,
            "domain": DomainAgent,
            "security": SecurityAgent,
            "api": APIAgent
        }
        
        for module in update_modules:
            if module not in module_to_agent:
                logger.warning(f"Unknown module: {module}, skipping")
                continue
            
            logger.info(f"Updating module: {module}")
            
            agent_class = module_to_agent[module]
            agent = agent_class(
                workspace=self.workspace,
                config=self._create_agent_config(agent_class.role),
                copilot=self.copilot
            )
            
            # 使用增量更新 prompt
            output = self._run_incremental_agent(
                agent=agent,
                scan=scan_result,
                base_context=base_context_text,
                changes=changes,
                module=module
            )
            
            module_outputs[module] = output
        
        # 6. 合并：未更新的模块复用 base_context，更新的模块使用新输出
        final_context = self._merge_contexts(
            base_context=base_context_text,
            updated_modules=module_outputs,
            update_list=update_modules
        )
        
        # 7. 构建 ProjectContext
        context = ProjectContext(
            repo_id=self.repo_id,
            branch=self.branch,
            commit_sha=current_commit,
            scan=scan_result,
            final_context=final_context,
            token_count=self._estimate_tokens(final_context)
        )
        
        # 更新各模块的输出
        for module, output in module_outputs.items():
            setattr(context, module, output)
        
        # 8. 保存输出
        self._save_outputs(context)
        self._save_cache(context)
        
        logger.info(f"Incremental update completed in {time.time() - context.scan.start_time:.2f}s")
        logger.info(f"Updated modules: {', '.join(update_modules)}")
        
        return context
    
    def _run_incremental_agent(
        self,
        agent,
        scan: ScanResult,
        base_context: str,
        changes: dict,
        module: str
    ) -> AgentOutput:
        """
        运行单个 Agent 的增量更新
        
        Args:
            agent: Agent 实例
            scan: 扫描结果
            base_context: 基准上下文文本
            changes: 变更字典
            module: 模块名
            
        Returns:
            Agent 输出
        """
        # 加载增量更新 prompt
        prompt_path = Path(__file__).parent.parent.parent.parent / "prompts" / "en" / "project_update.txt"
        
        if not prompt_path.exists():
            logger.warning(f"Incremental prompt not found, falling back to full analysis")
            return agent.analyze(scan)
        
        prompt_template = prompt_path.read_text(encoding='utf-8')
        
        # 填充 prompt 变量
        prompt = prompt_template.format(
            base_commit=changes['base_commit'],
            current_commit=changes['current_commit'],
            base_context=base_context,
            added_files='\n'.join(changes.get('added_files', [])),
            modified_files='\n'.join(changes.get('modified_files', [])),
            deleted_files='\n'.join(changes.get('deleted_files', [])),
            affected_modules=', '.join(changes['affected_modules']),
            current_module=module,
            impact_level=changes['estimated_impact'].get(module, 'unknown')
        )
        
        # 执行增量分析（复用 Agent 的 _call_copilot 方法）
        try:
            start_time = time.time()
            result = agent._call_copilot(prompt, temperature=0.3)
            duration = time.time() - start_time
            
            return AgentOutput(
                role=agent.role,
                content=result,
                success=True,
                duration=duration,
                retry_count=0
            )
        except Exception as e:
            logger.error(f"Incremental analysis failed for {module}: {e}")
            return AgentOutput(
                role=agent.role,
                error=str(e),
                success=False,
                duration=0,
                retry_count=0
            )
    
    def _merge_contexts(
        self,
        base_context: str,
        updated_modules: dict,
        update_list: list[str]
    ) -> str:
        """
        合并基准上下文和更新的模块
        
        Args:
            base_context: 基准上下文文本
            updated_modules: 更新的模块输出字典
            update_list: 更新的模块列表
            
        Returns:
            合并后的上下文文本
        """
        # 简单策略：完整替换
        # TODO: 更智能的合并策略（保留未变化部分）
        
        merged = f"# Project Context (Incremental Update)\n\n"
        merged += f"Updated modules: {', '.join(update_list)}\n\n"
        merged += "---\n\n"
        
        for module, output in updated_modules.items():
            if output.success and output.content:
                merged += f"## {module.replace('_', ' ').title()}\n\n"
                merged += output.content
                merged += "\n\n---\n\n"
        
        return merged
    
    def _create_context_from_base(
        self, 
        base_context: str, 
        base_commit: str, 
        current_commit: str
    ) -> ProjectContext:
        """
        从基准上下文创建 ProjectContext（无变更场景）
        
        Args:
            base_context: 基准上下文文本
            base_commit: 基准 commit
            current_commit: 当前 commit
            
        Returns:
            ProjectContext
        """
        return ProjectContext(
            repo_id=self.repo_id,
            branch=self.branch,
            commit_sha=current_commit,
            final_context=base_context,
            token_count=self._estimate_tokens(base_context)
        )
