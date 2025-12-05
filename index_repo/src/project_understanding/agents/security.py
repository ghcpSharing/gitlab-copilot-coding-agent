"""安全分析 Agent"""

from ..models import AgentRole, ScanResult
from . import ReviewableAgent


class SecurityAgent(ReviewableAgent):
    """分析项目安全相关
    
    识别：
    - 认证和授权机制
    - 敏感数据处理
    - 安全配置和依赖
    - 潜在安全风险
    """
    
    role = AgentRole.SECURITY
    prompt_file = "security.txt"
    
    def get_default_prompt(self) -> str:
        return """You are a Security Analyst. Analyze the project's security aspects:

1. **Authentication**: How users are authenticated (JWT, OAuth, Session, etc.)
2. **Authorization**: Permission models, RBAC, access control
3. **Data Protection**: Encryption, sensitive data handling, secrets management
4. **Security Configuration**: CORS, CSP, security headers
5. **Dependencies**: Known vulnerable packages (if detectable)

Output format:
```markdown
## Authentication
- Method: [auth method]
- Implementation: [brief description]

## Authorization
- Model: [RBAC/ABAC/etc]
- Key Roles: [list of roles]

## Data Protection
- Encryption: [methods used]
- Secrets: [how secrets are managed]

## Security Configuration
- [config]: [setting]

## Security Considerations
- [consideration]: [recommendation]
```

Focus on what's implemented, not exhaustive security audit.
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
            "# Configuration Files (security relevant)"
        ]
        
        # 查找安全相关文件
        security_keywords = [
            'auth', 'security', 'permission', 'role', 'jwt', 'oauth',
            'login', 'password', 'token', 'secret', 'encrypt', 'cors'
        ]
        
        for category, file_info in scan_result.key_files.items():
            if file_info.content:
                path_lower = file_info.path.lower()
                if any(kw in path_lower for kw in security_keywords):
                    parts.extend([
                        f"\n## {file_info.path}",
                        "```",
                        file_info.content[:2000],
                        "```"
                    ])
        
        # 添加配置文件
        if 'config' in scan_result.key_files:
            file_info = scan_result.key_files['config']
            if file_info.content:
                parts.extend([
                    f"\n## {file_info.path}",
                    "```",
                    file_info.content[:1500],
                    "```"
                ])
        
        return "\n".join(parts)
