"""技术栈分析 Agent"""

from ..models import AgentRole, ScanResult
from . import ReviewableAgent


class TechStackAgent(ReviewableAgent):
    """分析项目技术栈
    
    识别：
    - 编程语言和版本
    - 框架（Web、测试、ORM 等）
    - 构建工具和包管理器
    - 主要依赖库
    """
    
    role = AgentRole.TECH_STACK
    prompt_file = "tech_stack.txt"
    
    def get_default_prompt(self) -> str:
        return """You are a Technical Stack Analyst. Analyze the project and identify:

1. **Languages**: Programming languages and versions used
2. **Frameworks**: Web frameworks, testing frameworks, ORMs, etc.
3. **Build Tools**: Build systems, package managers, task runners
4. **Key Dependencies**: Important libraries and their purposes

Output format:
```markdown
## Languages
- [language] ([version if known])

## Frameworks
- [framework]: [purpose]

## Build Tools
- [tool]: [usage]

## Key Dependencies
- [dependency]: [purpose]
```

Be concise and focus on the most important aspects.
"""
    
    def build_context(self, scan_result: ScanResult) -> str:
        """构建上下文"""
        parts = [
            "# Project Information\n",
            f"Languages detected: {', '.join(scan_result.languages)}",
            f"Total files: {scan_result.total_files}",
            "",
            "# File Structure",
            scan_result.file_tree,
            "",
            "# Key Configuration Files"
        ]
        
        # 添加配置文件内容
        for category in ['config', 'schema']:
            if category in scan_result.key_files:
                file_info = scan_result.key_files[category]
                if file_info.content:
                    parts.extend([
                        f"\n## {file_info.path}",
                        "```",
                        file_info.content[:2000],  # 限制长度
                        "```"
                    ])
        
        return "\n".join(parts)
