"""业务领域分析 Agent"""

from ..models import AgentRole, ScanResult
from . import ReviewableAgent


class DomainAgent(ReviewableAgent):
    """分析项目业务领域
    
    识别：
    - 核心业务概念和术语
    - 业务规则和约束
    - 领域服务和用例
    - 业务流程和状态机
    """
    
    role = AgentRole.DOMAIN
    prompt_file = "domain.txt"
    
    def get_default_prompt(self) -> str:
        return """You are a Domain Expert Analyst. Analyze the project's business domain:

1. **Core Concepts**: Key business entities and terminology
2. **Business Rules**: Important constraints and validations
3. **Services/Use Cases**: Main business operations
4. **Workflows**: State machines, process flows

Output format:
```markdown
## Core Domain Concepts
- [Concept]: [description]

## Business Rules
- [Rule]: [description and rationale]

## Main Use Cases
- [Use Case]: [actors, trigger, outcome]

## Workflows
- [Workflow name]: [states and transitions]
```

Use domain-driven design terminology where appropriate.
"""
    
    def build_context(self, scan_result: ScanResult) -> str:
        """构建上下文"""
        parts = [
            "# Project Information\n",
            f"Languages: {', '.join(scan_result.languages)}",
            "",
            "# File Structure (focus on business logic)",
            scan_result.file_tree,
            "",
            "# Documentation"
        ]
        
        # 添加文档内容
        if 'doc' in scan_result.key_files:
            file_info = scan_result.key_files['doc']
            if file_info.content:
                parts.extend([
                    f"\n## {file_info.path}",
                    file_info.content[:3000]
                ])
        
        # 添加源代码中的 service/domain 文件
        if 'source' in scan_result.key_files:
            file_info = scan_result.key_files['source']
            if file_info.content:
                if any(keyword in file_info.path.lower() 
                       for keyword in ['service', 'domain', 'business', 'use_case', 'usecase']):
                    parts.extend([
                        f"\n## {file_info.path}",
                        "```",
                        file_info.content[:2000],
                        "```"
                    ])
        
        return "\n".join(parts)
