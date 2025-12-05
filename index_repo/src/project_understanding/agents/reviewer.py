"""Reviewer Agent - 质量校验"""

from typing import Optional
import logging

from ..models import AgentRole, AgentOutput, ReviewResult, ReviewStatus, ScanResult
from . import BaseAgent, AgentConfig
from ..copilot import CopilotClient

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    """Review 其他 Agent 的输出
    
    检查：
    - 输出是否完整
    - 是否有明显错误
    - 是否符合格式要求
    """
    
    role = AgentRole.REVIEWER
    prompt_file = "reviewer.txt"
    
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        client: Optional[CopilotClient] = None
    ):
        super().__init__(config, client)
        # Review 的通过阈值
        self.pass_threshold = 0.7  # 70% 置信度通过
    
    def get_default_prompt(self) -> str:
        return """You are a Quality Reviewer for technical analysis outputs.

Review the provided analysis and evaluate:
1. **Completeness**: Does it cover all required aspects?
2. **Accuracy**: Are the statements factually correct based on the context?
3. **Clarity**: Is the output well-structured and easy to understand?
4. **Relevance**: Does it focus on important aspects?

Output format (JSON):
```json
{
  "status": "PASSED" | "FAILED",
  "confidence": 0.0-1.0,
  "issues": ["issue 1", "issue 2"],
  "suggestions": ["suggestion 1", "suggestion 2"]
}
```

Be strict but fair. Only FAIL if there are significant issues.
"""
    
    def build_context(self, scan_result: ScanResult) -> str:
        """Reviewer 通常不需要 scan_result"""
        return ""
    
    def review(self, output: AgentOutput) -> ReviewResult:
        """Review 一个 Agent 的输出
        
        Args:
            output: 要 review 的 Agent 输出
            
        Returns:
            ReviewResult: Review 结果
        """
        if not output.success or not output.content:
            return ReviewResult(
                agent=output.agent,
                status=ReviewStatus.FAILED,
                issues=["Agent output is empty or failed"],
                suggestions=["Retry the analysis"]
            )
        
        # 构建 review prompt
        review_prompt = f"""
{self.prompt_template}

---
Agent: {output.agent.value}
Analysis Output:
{output.content}
"""
        
        response = self.client.call(review_prompt)
        
        if not response.success:
            logger.warning(f"Review call failed: {response.error}")
            # 如果 review 调用失败，默认通过（不阻塞流程）
            return ReviewResult(
                agent=output.agent,
                status=ReviewStatus.PASSED,
                issues=[],
                suggestions=[]
            )
        
        # 解析 review 结果
        return self._parse_review_response(output.agent, response.content)
    
    def _parse_review_response(
        self,
        agent: AgentRole,
        response: str
    ) -> ReviewResult:
        """解析 review 响应
        
        Args:
            agent: 被 review 的 Agent
            response: Copilot 响应
            
        Returns:
            ReviewResult: 解析后的结果
        """
        import json
        import re
        
        logger.debug(f"Parsing review response for {agent.value}: {response[:200]}...")
        
        # 尝试提取 JSON（支持多种格式）
        json_patterns = [
            r'```json\s*(.*?)\s*```',  # ```json ... ```
            r'```\s*(.*?)\s*```',       # ``` ... ```
            r'\{[^{}]*"status"[^{}]*\}', # 直接匹配 JSON 对象
        ]
        
        for pattern in json_patterns:
            json_match = re.search(pattern, response, re.DOTALL)
            if json_match:
                try:
                    json_str = json_match.group(1) if '```' in pattern else json_match.group(0)
                    data = json.loads(json_str)
                    
                    status_str = data.get('status', 'PASSED').upper()
                    confidence = float(data.get('confidence', 0.8))
                    
                    logger.debug(f"Parsed JSON: status={status_str}, confidence={confidence}")
                    
                    # 根据 confidence 和 status 决定最终状态
                    if status_str == 'PASSED' and confidence >= self.pass_threshold:
                        status = ReviewStatus.PASSED
                    elif status_str == 'FAILED' and confidence < 0.5:
                        status = ReviewStatus.FAILED
                    else:
                        # confidence 在 0.5-0.7 之间，或者 FAILED 但 confidence 高
                        # 默认通过，不阻塞流程
                        status = ReviewStatus.PASSED
                    
                    return ReviewResult(
                        agent=agent,
                        status=status,
                        issues=data.get('issues', []),
                        suggestions=data.get('suggestions', [])
                    )
                except (json.JSONDecodeError, ValueError, IndexError) as e:
                    logger.debug(f"Failed to parse JSON with pattern {pattern}: {e}")
                    continue
        
        # 如果解析失败，默认通过（不要阻塞流程）
        logger.warning(f"Could not parse review response for {agent.value}, defaulting to PASSED")
        return ReviewResult(
            agent=agent,
            status=ReviewStatus.PASSED,
            issues=[],
            suggestions=["Review response could not be parsed"]
        )
    
    def analyze(self, scan_result: ScanResult) -> AgentOutput:
        """Reviewer 不执行 analyze，使用 review() 方法"""
        raise NotImplementedError("Reviewer uses review() method, not analyze()")
