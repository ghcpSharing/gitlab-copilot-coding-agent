"""Agent 基类和工具函数"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import logging

from ..models import AgentRole, AgentOutput, ReviewStatus, ScanResult
from ..copilot import CopilotClient, CopilotResponse

logger = logging.getLogger(__name__)


# Prompt 模板目录
PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts" / "project_understanding"


@dataclass
class AgentConfig:
    """Agent 配置"""
    max_retries: int = 2
    timeout: int = 120
    model: str = "claude-sonnet-4"
    max_output_tokens: int = 4096


class BaseAgent(ABC):
    """Agent 基类
    
    所有专家 Agent 都继承此类
    """
    
    # 子类必须定义
    role: AgentRole
    prompt_file: str  # prompt 文件名（不含路径）
    
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        client: Optional[CopilotClient] = None
    ):
        """初始化 Agent
        
        Args:
            config: Agent 配置
            client: Copilot 客户端（可共享）
        """
        self.config = config or AgentConfig()
        self.client = client or CopilotClient(
            timeout=self.config.timeout,
            model=self.config.model,
            max_retries=self.config.max_retries
        )
        self._prompt_template: Optional[str] = None
    
    @property
    def prompt_template(self) -> str:
        """获取 prompt 模板"""
        if self._prompt_template is None:
            prompt_path = PROMPTS_DIR / self.prompt_file
            if prompt_path.exists():
                self._prompt_template = prompt_path.read_text()
            else:
                # 使用默认 prompt
                self._prompt_template = self.get_default_prompt()
        return self._prompt_template
    
    @abstractmethod
    def get_default_prompt(self) -> str:
        """获取默认 prompt（子类实现）"""
        pass
    
    @abstractmethod
    def build_context(self, scan_result: ScanResult) -> str:
        """构建上下文（子类实现）
        
        Args:
            scan_result: 扫描结果
            
        Returns:
            str: 格式化的上下文字符串
        """
        pass
    
    def analyze(self, scan_result: ScanResult) -> AgentOutput:
        """执行分析
        
        Args:
            scan_result: 扫描结果
            
        Returns:
            AgentOutput: 分析输出
        """
        logger.info(f"[{self.role.value}] Starting analysis...")
        
        # 构建 prompt 和 context
        prompt = self.prompt_template
        context = self.build_context(scan_result)
        
        # 调用 Copilot
        response = self.client.call_with_retry(
            prompt=prompt,
            context=context,
            max_retries=self.config.max_retries
        )
        
        if response.success:
            logger.info(f"[{self.role.value}] Analysis completed successfully")
            return AgentOutput(
                agent=self.role,
                content=self.post_process(response.content),
                raw_response=response.content,
                success=True
            )
        else:
            logger.error(f"[{self.role.value}] Analysis failed: {response.error}")
            return AgentOutput(
                agent=self.role,
                content="",
                raw_response="",
                success=False,
                error=response.error
            )
    
    def post_process(self, content: str) -> str:
        """后处理输出（子类可覆盖）
        
        Args:
            content: 原始输出
            
        Returns:
            str: 处理后的输出
        """
        return content.strip()
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(role={self.role.value})"


class ReviewableAgent(BaseAgent):
    """可被 Review 的 Agent
    
    添加 review 相关的接口
    """
    
    def analyze_with_review(
        self,
        scan_result: ScanResult,
        reviewer: 'ReviewerAgent',
        max_iterations: int = 2
    ) -> AgentOutput:
        """执行分析并接受 review
        
        Args:
            scan_result: 扫描结果
            reviewer: Reviewer Agent
            max_iterations: 最大迭代次数
            
        Returns:
            AgentOutput: 最终输出
        """
        output = self.analyze(scan_result)
        
        if not output.success:
            return output
        
        for iteration in range(max_iterations):
            # 请求 review
            review_result = reviewer.review(output)
            
            if review_result.status == ReviewStatus.PASSED:
                logger.info(f"[{self.role.value}] Passed review on iteration {iteration + 1}")
                return output
            
            if review_result.status == ReviewStatus.FAILED:
                logger.warning(f"[{self.role.value}] Failed review, retrying...")
                
                # 根据 review 建议重新分析
                output = self._retry_with_feedback(
                    scan_result,
                    output,
                    review_result.suggestions
                )
                
                if not output.success:
                    return output
                
                output.retry_count += 1
        
        logger.warning(f"[{self.role.value}] Max review iterations reached")
        return output
    
    def _retry_with_feedback(
        self,
        scan_result: ScanResult,
        previous_output: AgentOutput,
        suggestions: list[str]
    ) -> AgentOutput:
        """根据反馈重试
        
        Args:
            scan_result: 扫描结果
            previous_output: 上次输出
            suggestions: Review 建议
            
        Returns:
            AgentOutput: 新的输出
        """
        # 构建带反馈的 prompt
        feedback_prompt = f"""
{self.prompt_template}

---
Previous Analysis (needs improvement):
{previous_output.content}

---
Review Feedback:
{chr(10).join(f'- {s}' for s in suggestions)}

Please improve your analysis based on the feedback above.
"""
        
        context = self.build_context(scan_result)
        
        response = self.client.call_with_retry(
            prompt=feedback_prompt,
            context=context
        )
        
        if response.success:
            return AgentOutput(
                agent=self.role,
                content=self.post_process(response.content),
                raw_response=response.content,
                success=True,
                retry_count=previous_output.retry_count + 1
            )
        else:
            return AgentOutput(
                agent=self.role,
                content="",
                raw_response="",
                success=False,
                error=response.error,
                retry_count=previous_output.retry_count + 1
            )


# 类型注解用，避免循环导入
class ReviewerAgent:
    """Reviewer Agent 的类型注解占位"""
    pass
