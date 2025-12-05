"""API 结构分析 Agent"""

from ..models import AgentRole, ScanResult
from . import ReviewableAgent


class APIAgent(ReviewableAgent):
    """分析项目 API 结构
    
    识别：
    - API 端点和路由
    - 请求/响应格式
    - API 版本控制
    - 错误处理模式
    """
    
    role = AgentRole.API
    prompt_file = "api.txt"
    
    def get_default_prompt(self) -> str:
        return """You are an API Analyst. Analyze the project's API structure:

1. **Endpoints**: REST routes, GraphQL queries/mutations, gRPC services
2. **Request/Response**: Payload formats, content types
3. **Versioning**: API versioning strategy
4. **Error Handling**: Error response format, status codes used

Output format:
```markdown
## API Type
- Type: [REST/GraphQL/gRPC/Mixed]
- Base Path: [base URL path]

## Main Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/v1/users | List users |

## Request/Response Patterns
- Authentication: [header/body]
- Pagination: [pattern]
- Error Format: [format]

## Versioning
- Strategy: [URL/Header/Query]
- Current Version: [version]
```

Focus on the API design patterns, not every endpoint.
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
            "# API Related Files"
        ]
        
        # 查找 API 相关文件
        api_keywords = [
            'route', 'router', 'controller', 'endpoint', 'api',
            'handler', 'view', 'resource', 'graphql', 'schema',
            'openapi', 'swagger', 'proto'
        ]
        
        for category, file_info in scan_result.key_files.items():
            if file_info.content:
                path_lower = file_info.path.lower()
                if any(kw in path_lower for kw in api_keywords):
                    parts.extend([
                        f"\n## {file_info.path}",
                        "```",
                        file_info.content[:2500],
                        "```"
                    ])
        
        # 添加 schema 文件（可能包含 OpenAPI/GraphQL schema）
        if 'schema' in scan_result.key_files:
            file_info = scan_result.key_files['schema']
            if file_info.content:
                parts.extend([
                    f"\n## {file_info.path}",
                    "```",
                    file_info.content[:2000],
                    "```"
                ])
        
        return "\n".join(parts)
