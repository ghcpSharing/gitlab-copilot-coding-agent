"""数据模型定义"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pathlib import Path
import json


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


class AgentStatus(Enum):
    """Agent 执行状态"""
    INHERITED = "inherited"  # 继承自父 commit
    SUCCESS = "success"      # 本次成功执行
    FAILED = "failed"        # 执行失败
    SKIPPED = "skipped"      # 跳过执行


class AnalysisType(Enum):
    """分析类型"""
    FULL = "full"                      # 完整分析
    INCREMENTAL = "incremental"        # 增量更新
    INHERITED = "inherited"            # 完全继承
    CROSS_BRANCH = "cross-branch"      # 跨分支复用


class ContentSource(Enum):
    """内容来源"""
    INHERITED = "inherited"  # 继承自父 commit
    UPDATED = "updated"      # 本次更新
    NEW = "new"              # 本次新增


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
class ContentObjectInfo:
    """内容对象信息"""
    hash: str                           # SHA-256 hash
    size: int                           # 文件大小（字节）
    source: ContentSource               # 来源类型
    source_commit: str                  # 来源 commit SHA
    last_modified: Optional[str] = None # 最后修改时间（ISO 8601）
    previous_hash: Optional[str] = None # 更新前的 hash（用于 diff）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "hash": self.hash,
            "size": self.size,
            "source": self.source.value if isinstance(self.source, ContentSource) else self.source,
            "source_commit": self.source_commit,
            "last_modified": self.last_modified,
            "previous_hash": self.previous_hash
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContentObjectInfo':
        """从字典创建"""
        return cls(
            hash=data["hash"],
            size=data["size"],
            source=ContentSource(data["source"]) if isinstance(data["source"], str) else data["source"],
            source_commit=data["source_commit"],
            last_modified=data.get("last_modified"),
            previous_hash=data.get("previous_hash")
        )


@dataclass
class LineageInfo:
    """血缘关系信息"""
    parent_commit: Optional[str] = None      # Git 父 commit
    base_branch: Optional[str] = None        # 基于哪个分支创建
    base_commit: Optional[str] = None        # 分支创建时的基准 commit
    merge_from: Optional[str] = None         # 如果是 merge commit，记录来源分支
    fork_type: str = "branch"                # branch | merge | rebase
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "parent_commit": self.parent_commit,
            "base_branch": self.base_branch,
            "base_commit": self.base_commit,
            "merge_from": self.merge_from,
            "fork_type": self.fork_type
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LineageInfo':
        """从字典创建"""
        return cls(**data)


@dataclass
class AnalysisInfo:
    """分析信息"""
    created_at: str                          # ISO 8601 时间戳
    type: AnalysisType                       # 分析类型
    incremental_from: Optional[str] = None   # 增量更新的基准 commit
    incremental_count: int = 0               # 增量更新次数
    duration_ms: int = 0                     # 分析耗时（毫秒）
    estimated_full_duration_ms: int = 0      # 完整分析预计耗时
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "created_at": self.created_at,
            "type": self.type.value if isinstance(self.type, AnalysisType) else self.type,
            "incremental_from": self.incremental_from,
            "incremental_count": self.incremental_count,
            "duration_ms": self.duration_ms,
            "estimated_full_duration_ms": self.estimated_full_duration_ms
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisInfo':
        """从字典创建"""
        data_copy = data.copy()
        if "type" in data_copy and isinstance(data_copy["type"], str):
            data_copy["type"] = AnalysisType(data_copy["type"])
        return cls(**data_copy)


@dataclass
class AgentExecutionInfo:
    """Agent 执行信息"""
    status: AgentStatus                      # 执行状态
    duration_ms: int = 0                     # 执行时长
    retry_count: int = 0                     # 重试次数
    source_commit: Optional[str] = None      # 如果是 inherited，记录来源 commit
    error: Optional[str] = None              # 错误信息
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "status": self.status.value if isinstance(self.status, AgentStatus) else self.status,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "source_commit": self.source_commit,
            "error": self.error
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentExecutionInfo':
        """从字典创建"""
        data_copy = data.copy()
        if "status" in data_copy and isinstance(data_copy["status"], str):
            data_copy["status"] = AgentStatus(data_copy["status"])
        return cls(**data_copy)


@dataclass
class StatsInfo:
    """统计信息"""
    total_files: int = 0                     # 总文件数
    inherited_files: int = 0                 # 复用的文件数
    updated_files: int = 0                   # 更新的文件数
    new_files: int = 0                       # 新增的文件数
    deleted_files: int = 0                   # 删除的文件数
    deduplication_ratio: float = 0.0         # 去重率（0-1）
    storage_saved_bytes: int = 0             # 相比完整存储节省的字节数
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StatsInfo':
        """从字典创建"""
        return cls(**data)


@dataclass
class GitInfo:
    """Git 信息"""
    author: Optional[str] = None             # 提交作者
    message: Optional[str] = None            # 提交信息
    changed_files: list[str] = field(default_factory=list)  # 变更文件列表
    additions: int = 0                       # 新增行数
    deletions: int = 0                       # 删除行数
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GitInfo':
        """从字典创建"""
        return cls(**data)


@dataclass
class BranchForkInfo:
    """分支派生关系信息"""
    base_branch: str                         # 基准分支名
    base_commit: str                         # 基准 commit SHA
    created_at: str                          # 创建时间（ISO 8601）
    fork_type: str = "branch"                # branch | merge | rebase
    created_by: Optional[str] = None         # 创建者
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BranchForkInfo':
        """从字典创建"""
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'BranchForkInfo':
        """从 JSON 字符串创建"""
        return cls.from_dict(json.loads(json_str))


@dataclass
class CacheSearchResult:
    """缓存查找结果"""
    found: bool                              # 是否找到缓存
    commit_sha: Optional[str] = None         # 缓存的 commit SHA
    metadata: Optional[CacheMetadata] = None # 缓存元数据
    reuse_strategy: str = "none"             # exact | incremental | cross-branch | content-similar | full_analysis
    base_branch: Optional[str] = None        # 跨分支复用时的基准分支
    similarity: float = 0.0                  # 内容相似度（0-1）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "found": self.found,
            "commit_sha": self.commit_sha,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "reuse_strategy": self.reuse_strategy,
            "base_branch": self.base_branch,
            "similarity": self.similarity
        }
    
    def to_json(self, indent: int = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheSearchResult':
        """从字典创建"""
        metadata = None
        if data.get("metadata"):
            metadata = CacheMetadata.from_dict(data["metadata"])
        
        return cls(
            found=data["found"],
            commit_sha=data.get("commit_sha"),
            metadata=metadata,
            reuse_strategy=data.get("reuse_strategy", "none"),
            base_branch=data.get("base_branch"),
            similarity=data.get("similarity", 0.0)
        )


@dataclass
class CacheMetadata:
    """缓存元数据（增强版）"""
    version: str                             # 元数据版本
    project_id: str                          # GitLab 项目 ID
    branch: str                              # 分支名
    commit_sha: str                          # Commit SHA
    
    # 血缘关系
    lineage: LineageInfo = field(default_factory=LineageInfo)
    
    # 分析信息
    analysis: AnalysisInfo = field(default_factory=lambda: AnalysisInfo(
        created_at=datetime.now().isoformat(),
        type=AnalysisType.FULL
    ))
    
    # 内容对象索引（文件路径 → 内容信息）
    content_objects: Dict[str, ContentObjectInfo] = field(default_factory=dict)
    
    # Agent 执行记录
    agents: Dict[str, AgentExecutionInfo] = field(default_factory=dict)
    
    # 统计信息
    stats: StatsInfo = field(default_factory=StatsInfo)
    
    # Git 信息
    git: GitInfo = field(default_factory=GitInfo)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "project_id": self.project_id,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "lineage": self.lineage.to_dict(),
            "analysis": self.analysis.to_dict(),
            "content_objects": {
                path: obj.to_dict() for path, obj in self.content_objects.items()
            },
            "agents": {
                name: info.to_dict() for name, info in self.agents.items()
            },
            "stats": self.stats.to_dict(),
            "git": self.git.to_dict()
        }
    
    def to_json(self, indent: int = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheMetadata':
        """从字典创建"""
        return cls(
            version=data.get("version", "2.0"),
            project_id=data["project_id"],
            branch=data["branch"],
            commit_sha=data["commit_sha"],
            lineage=LineageInfo.from_dict(data.get("lineage", {})),
            analysis=AnalysisInfo.from_dict(data.get("analysis", {
                "created_at": datetime.now().isoformat(),
                "type": "full"
            })),
            content_objects={
                path: ContentObjectInfo.from_dict(obj_data)
                for path, obj_data in data.get("content_objects", {}).items()
            },
            agents={
                name: AgentExecutionInfo.from_dict(info_data)
                for name, info_data in data.get("agents", {}).items()
            },
            stats=StatsInfo.from_dict(data.get("stats", {})),
            git=GitInfo.from_dict(data.get("git", {}))
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'CacheMetadata':
        """从 JSON 字符串创建"""
        return cls.from_dict(json.loads(json_str))
    
    def is_expired(self, max_age_days: int = 7) -> bool:
        """检查是否过期"""
        created_at = datetime.fromisoformat(self.analysis.created_at)
        age = datetime.now() - created_at
        return age.days > max_age_days
