"""Synthesizer Agent - 合并压缩所有分析结果"""

from typing import Optional
import logging

from ..models import AgentRole, AgentOutput, ScanResult
from . import BaseAgent, AgentConfig
from ..copilot import CopilotClient

logger = logging.getLogger(__name__)


class SynthesizerAgent(BaseAgent):
    """合成所有 Agent 的分析结果
    
    职责：
    - 去重和整合信息
    - 压缩到 token 限制内
    - 生成结构化的项目上下文
    """
    
    role = AgentRole.SYNTHESIZER
    prompt_file = "synthesizer.txt"
    
    # 默认 token 限制
    DEFAULT_MAX_TOKENS = 4000
    
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        client: Optional[CopilotClient] = None,
        max_context_tokens: int = DEFAULT_MAX_TOKENS
    ):
        super().__init__(config, client)
        self.max_context_tokens = max_context_tokens
    
    def get_default_prompt(self) -> str:
        return """You are a Technical Synthesizer. Combine multiple analysis outputs into a coherent project context.

Goals:
1. **Remove Redundancy**: Eliminate duplicate information across analyses
2. **Prioritize**: Focus on information most useful for code review
3. **Structure**: Organize into clear, scannable sections
4. **Compress**: Keep output concise (target: 1500-2000 words)

Output format:
```markdown
# Project Context

## Overview
[1-2 sentence project description]

## Tech Stack
- Languages: [list]
- Frameworks: [key frameworks]
- Key Dependencies: [important libs]

## Architecture
- Pattern: [MVC/Clean/etc]
- Layers: [presentation, business, data]

## Data Model
[Key entities and relationships]

## API Structure
[Main endpoints and patterns]

## Security
[Auth method, key security aspects]

## Code Review Focus Areas
[Specific areas to pay attention to during review]
```

Be concise. This context will be used by reviewers who need quick understanding.
"""
    
    def build_context(self, scan_result: ScanResult) -> str:
        """构建基础上下文"""
        return f"""
# Scan Information
- Languages: {', '.join(scan_result.languages)}
- Total Files: {scan_result.total_files}

# File Structure
{scan_result.file_tree}
"""
    
    def synthesize(
        self,
        outputs: list[AgentOutput],
        scan_result: ScanResult
    ) -> AgentOutput:
        """合成多个 Agent 的输出
        
        Args:
            outputs: 各专家 Agent 的输出列表
            scan_result: 扫描结果
            
        Returns:
            AgentOutput: 合成后的输出
        """
        logger.info(f"[{self.role.value}] Synthesizing {len(outputs)} agent outputs...")
        
        # 构建合成 prompt
        synthesis_prompt = f"""
{self.prompt_template}

---
Maximum output length: approximately {self.max_context_tokens} tokens

---
Agent Analysis Results:
"""
        
        # 添加各 Agent 的输出
        for output in outputs:
            if output.success and output.content:
                synthesis_prompt += f"""
## {output.agent.value.upper()} Analysis
{output.content}

"""
        
        # 添加基础上下文
        base_context = self.build_context(scan_result)
        
        # 调用 Copilot
        response = self.client.call_with_retry(
            prompt=synthesis_prompt,
            context=base_context
        )
        
        if response.success:
            logger.info(f"[{self.role.value}] Synthesis completed")
            return AgentOutput(
                agent=self.role,
                content=self._post_process_synthesis(response.content),
                raw_response=response.content,
                success=True
            )
        else:
            logger.error(f"[{self.role.value}] Synthesis failed: {response.error}")
            # 降级方案：简单拼接
            return self._fallback_synthesis(outputs, scan_result)
    
    def _post_process_synthesis(self, content: str) -> str:
        """后处理合成结果"""
        # 移除可能的 markdown 代码块标记
        content = content.strip()
        if content.startswith('```markdown'):
            content = content[11:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        return content.strip()
    
    def _fallback_synthesis(
        self,
        outputs: list[AgentOutput],
        scan_result: ScanResult
    ) -> AgentOutput:
        """降级合成方案 - 简单拼接"""
        logger.warning("Using fallback synthesis (simple concatenation)")
        
        parts = [
            "# Project Context (Fallback)",
            "",
            "## Overview",
            f"- Languages: {', '.join(scan_result.languages)}",
            f"- Total Files: {scan_result.total_files}",
            ""
        ]
        
        for output in outputs:
            if output.success and output.content:
                parts.append(f"## {output.agent.value.replace('_', ' ').title()}")
                # 截取前 500 字符
                content = output.content[:500]
                if len(output.content) > 500:
                    content += "..."
                parts.append(content)
                parts.append("")
        
        return AgentOutput(
            agent=self.role,
            content="\n".join(parts),
            raw_response="",
            success=True,
            error="Used fallback synthesis"
        )
    
    def analyze(self, scan_result: ScanResult) -> AgentOutput:
        """Synthesizer 不执行 analyze，使用 synthesize() 方法"""
        raise NotImplementedError("Synthesizer uses synthesize() method, not analyze()")
