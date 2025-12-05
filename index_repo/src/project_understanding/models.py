"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from pathlib import Path


class AgentRole(Enum):
    """Agent 角色"""
    SCANNER = "scanner"
    TECH_STACK = "tech_stack"
    DATA_MODEL = "data_model"
    DOMAIN = "domain"
    SECURITY = "security"
    API = "api"
    REVIEWER = "reviewer"
    SYNTHESIZER = "synthesizer"


class ReviewStatus(Enum):
    """Review 状态"""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    RETRY = "retry"


@dataclass
class FileInfo:
    """文件信息"""
    path: str
    category: str  # config, schema, source, doc, test
    size: int
    content: Optional[str] = None  # 关键文件的内容


@dataclass
class ScanResult:
    """扫描结果"""
    file_tree: str
    key_files: dict[str, FileInfo]  # category -> FileInfo
    total_files: int
    languages: list[str]


@dataclass
class AgentOutput:
    """Agent 输出"""
    agent: AgentRole
    content: str
    raw_response: str
    success: bool
    error: Optional[str] = None
    retry_count: int = 0


@dataclass
class ReviewResult:
    """Review 结果"""
    agent: AgentRole
    status: ReviewStatus
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class ProjectContext:
    """最终的项目上下文"""
    repo_id: str
    branch: str
    commit_sha: str
    
    # 各 Agent 的分析结果
    tech_stack: Optional[AgentOutput] = None
    data_model: Optional[AgentOutput] = None
    domain: Optional[AgentOutput] = None
    security: Optional[AgentOutput] = None
    api_structure: Optional[AgentOutput] = None
    
    # Review 结果
    reviews: list[ReviewResult] = field(default_factory=list)
    
    # 最终上下文
    final_context: str = ""
    token_count: int = 0
    
    # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    analysis_time_ms: int = 0


@dataclass
class CacheMetadata:
    """缓存元数据"""
    repo_id: str
    branch: str
    commit_sha: str
    last_updated: datetime
    version: str = "1.0"
    
    def is_expired(self, max_age_days: int = 7) -> bool:
        """检查是否过期"""
        age = datetime.now() - self.last_updated
        return age.days > max_age_days
