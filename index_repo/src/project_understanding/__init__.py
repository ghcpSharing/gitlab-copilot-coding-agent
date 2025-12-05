# Project Understanding Module
# 使用 Copilot CLI 实现多 Agent 协作分析项目

__version__ = "0.1.0"

from .models import (
    AgentRole,
    ReviewStatus,
    FileInfo,
    ScanResult,
    AgentOutput,
    ReviewResult,
    ProjectContext,
    CacheMetadata,
)

from .scanner import scan_project
from .copilot import CopilotClient, CopilotResponse, call_copilot
from .orchestrator import Orchestrator, OrchestratorConfig

__all__ = [
    # Models
    "AgentRole",
    "ReviewStatus",
    "FileInfo",
    "ScanResult",
    "AgentOutput",
    "ReviewResult",
    "ProjectContext",
    "CacheMetadata",
    # Functions
    "scan_project",
    "call_copilot",
    # Classes
    "CopilotClient",
    "CopilotResponse",
    "Orchestrator",
    "OrchestratorConfig",
]
