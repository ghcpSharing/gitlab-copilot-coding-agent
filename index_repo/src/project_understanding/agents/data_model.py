"""数据模型分析 Agent"""

from ..models import AgentRole, ScanResult
from . import ReviewableAgent


class DataModelAgent(ReviewableAgent):
    """分析项目数据模型
    
    识别：
    - 数据库类型和表结构
    - ORM 实体和关系
    - API 数据传输对象 (DTO)
    - 数据验证规则
    """
    
    role = AgentRole.DATA_MODEL
    prompt_file = "data_model.txt"
    
    def get_default_prompt(self) -> str:
        return """You are a Data Model Analyst. Analyze the project's data structures:

1. **Database**: Type (SQL/NoSQL), schemas, tables
2. **Entities**: ORM models, relationships (1:1, 1:N, M:N)
3. **DTOs**: Request/Response objects, validation rules
4. **Data Flow**: How data moves between layers

Output format:
```markdown
## Database Schema
- [table/collection]: [description]
  - [field]: [type] - [constraints]

## Entity Relationships
- [Entity A] --[relation]--> [Entity B]

## Data Transfer Objects
- [DTO name]: [purpose]
  - [field]: [type]

## Validation Rules
- [rule]: [description]
```

Focus on the core data model, not every detail.
"""
    
    def build_context(self, scan_result: ScanResult) -> str:
        """构建上下文"""
        parts = [
            "# Project Information\n",
            f"Languages: {', '.join(scan_result.languages)}",
            "",
            "# File Structure",
            scan_result.file_tree,
            "",
            "# Schema and Model Files"
        ]
        
        # 添加 schema 和 model 相关文件
        for category in ['schema', 'source']:
            if category in scan_result.key_files:
                file_info = scan_result.key_files[category]
                if file_info.content:
                    # 优先包含 model/schema 相关文件
                    if any(keyword in file_info.path.lower() 
                           for keyword in ['model', 'schema', 'entity', 'migration']):
                        parts.extend([
                            f"\n## {file_info.path}",
                            "```",
                            file_info.content[:3000],
                            "```"
                        ])
        
        return "\n".join(parts)
