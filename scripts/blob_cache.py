#!/usr/bin/env python3
"""
Azure Blob Storage 缓存工具
用于存储和检索项目理解上下文

存储路径格式: code/{project_id}/{branch}/{commit_sha}/.copilot/
"""
import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient


def log_info(msg: str):
    """输出到 stderr，保持 stdout 干净用于 JSON"""
    print(f"[INFO] {msg}", file=sys.stderr)


def log_warn(msg: str):
    """输出到 stderr"""
    print(f"[WARN] {msg}", file=sys.stderr)


def log_error(msg: str):
    """输出到 stderr"""
    print(f"[ERROR] {msg}", file=sys.stderr)


def log_debug(msg: str):
    """输出到 stderr"""
    print(f"[DEBUG] {msg}", file=sys.stderr)



class BlobCache:
    """Azure Blob Storage 缓存管理器"""
    
    def __init__(self, connection_string: str, container_name: str = "code"):
        """
        初始化
        
        Args:
            connection_string: Azure Storage 连接字符串
            container_name: 容器名称（默认: code）
        """
        # Debug: 打印连接字符串信息（隐藏敏感信息）
        log_debug(f"Connection string length: {len(connection_string)}")
        log_debug(f"Connection string preview: {connection_string[:50]}...{connection_string[-20:]}")
        
        # 检查连接字符串是否包含必要的组件
        required_parts = ['AccountName=', 'AccountKey=', 'DefaultEndpointsProtocol=']
        for part in required_parts:
            if part in connection_string:
                log_debug(f"✓ Found {part}")
            else:
                log_error(f"✗ Missing {part}")
        
        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        except Exception as e:
            log_error(f"Failed to create BlobServiceClient: {e}")
            raise
            
        self.container_name = container_name
        
        try:
            self.container_client = self.blob_service_client.get_container_client(container_name)
        except Exception as e:
            log_error(f"Failed to get container client: {e}")
            raise
        
        # 确保容器存在
        try:
            self.container_client.get_container_properties()
            log_debug(f"Container '{container_name}' exists")
        except Exception as e:
            log_info(f"Creating container: {container_name} (reason: {e})")
            try:
                self.container_client.create_container()
                log_info(f"Container '{container_name}' created successfully")
            except Exception as create_err:
                log_error(f"Failed to create container: {create_err}")
                raise
    
    def _compute_file_hash(self, file_path: Path, chunk_size: int = 8192) -> str:
        """
        计算文件的 SHA-256 hash
        
        Args:
            file_path: 文件路径
            chunk_size: 读取块大小（字节），默认 8KB
            
        Returns:
            格式：sha256-{hex_digest}
        """
        sha256_hash = hashlib.sha256()
        
        try:
            with open(file_path, "rb") as f:
                # 流式读取，支持大文件
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    sha256_hash.update(chunk)
            
            hex_digest = sha256_hash.hexdigest()
            return f"sha256-{hex_digest}"
        except Exception as e:
            log_error(f"Failed to compute hash for {file_path}: {e}")
            raise
    
    def _sanitize_branch_name(self, branch: str) -> str:
        """清理分支名中的特殊字符"""
        return branch.replace('/', '_').replace('\\', '_')
    
    def _get_blob_prefix(self, project_id: str, branch: str) -> str:
        """
        生成 blob 路径前缀（旧格式，保持向后兼容）
        
        格式: {project_id}/{branch}/
        """
        safe_branch = self._sanitize_branch_name(branch)
        return f"{project_id}/{safe_branch}"
    
    def _get_branch_path(self, project_id: str, branch: str) -> str:
        """
        生成分支路径（新格式）
        
        格式: projects/{project_id}/branches/{branch}/
        """
        safe_branch = self._sanitize_branch_name(branch)
        return f"projects/{project_id}/branches/{safe_branch}"
    
    def _get_commit_path(self, project_id: str, branch: str, commit_sha: str) -> str:
        """
        生成 commit 路径（新格式）
        
        格式: projects/{project_id}/branches/{branch}/commits/{commit_sha}/
        """
        branch_path = self._get_branch_path(project_id, branch)
        return f"{branch_path}/commits/{commit_sha}"
    
    def _get_metadata_path(self, project_id: str, branch: str, commit_sha: str) -> str:
        """
        生成 metadata.json 路径（新格式）
        
        格式: projects/{project_id}/branches/{branch}/commits/{commit_sha}/metadata.json
        """
        commit_path = self._get_commit_path(project_id, branch, commit_sha)
        return f"{commit_path}/metadata.json"
    
    def _get_blob_path(self, project_id: str, branch: str, commit_sha: str, filename: str) -> str:
        """
        生成完整的 blob 路径
        
        格式: {project_id}/{branch}/{commit_sha}/{filename}
        """
        prefix = self._get_blob_prefix(project_id, branch)
        return f"{prefix}/{commit_sha}/{filename}"
    
    def _get_content_object_path(self, content_hash: str) -> str:
        """
        生成内容对象的 blob 路径
        
        格式: objects/content/{content_hash}
        """
        return f"objects/content/{content_hash}"
    
    def _content_exists(self, content_hash: str) -> bool:
        """
        检查内容对象是否已存在
        
        Args:
            content_hash: 内容 hash (sha256-xxx)
            
        Returns:
            存在返回 True
        """
        blob_path = self._get_content_object_path(content_hash)
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_path
        )
        
        try:
            blob_client.get_blob_properties()
            return True
        except Exception:
            return False
    
    def _upload_content_object(self, file_path: Path, content_hash: str) -> bool:
        """
        上传内容对象到 objects/content/
        
        Args:
            file_path: 本地文件路径
            content_hash: 内容 hash
            
        Returns:
            成功返回 True
        """
        # 检查是否已存在（去重）
        if self._content_exists(content_hash):
            log_info(f"Content object already exists: {content_hash} (deduplicated)")
            return True
        
        blob_path = self._get_content_object_path(content_hash)
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_path
        )
        
        try:
            with open(file_path, 'rb') as data:
                blob_client.upload_blob(data, overwrite=False)
            log_info(f"Uploaded content object: {content_hash}")
            return True
        except Exception as e:
            log_error(f"Failed to upload content object {content_hash}: {e}")
            return False
    
    def _download_content_object(self, content_hash: str, local_path: Path) -> bool:
        """
        从 objects/content/ 下载内容对象
        
        Args:
            content_hash: 内容 hash
            local_path: 本地保存路径
            
        Returns:
            成功返回 True
        """
        blob_path = self._get_content_object_path(content_hash)
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_path
        )
        
        try:
            # 创建父目录
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(local_path, 'wb') as f:
                data = blob_client.download_blob()
                f.write(data.readall())
            return True
        except Exception as e:
            log_error(f"Failed to download content object {content_hash}: {e}")
            return False
    
    def _update_branch_latest(self, project_id: str, branch: str, commit_sha: str, metadata: dict) -> bool:
        """
        更新分支的 latest.json 索引
        
        Args:
            project_id: 项目 ID
            branch: 分支名
            commit_sha: Commit SHA
            metadata: metadata 字典
            
        Returns:
            成功返回 True
        """
        branch_path = self._get_branch_path(project_id, branch)
        latest_path = f"{branch_path}/latest.json"
        
        latest_info = {
            "commit_sha": commit_sha,
            "created_at": metadata.get("analysis", {}).get("created_at", datetime.now().isoformat()),
            "analysis_type": metadata.get("analysis", {}).get("type", "full")
        }
        
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=latest_path
        )
        
        try:
            blob_client.upload_blob(
                json.dumps(latest_info, indent=2),
                overwrite=True
            )
            log_info(f"Updated latest.json for {branch}: {commit_sha}")
            return True
        except Exception as e:
            log_error(f"Failed to update latest.json: {e}")
            return False
    
    def _get_branch_latest(self, project_id: str, branch: str) -> Optional[dict]:
        """
        获取分支的最新 commit 信息
        
        Args:
            project_id: 项目 ID
            branch: 分支名
            
        Returns:
            latest.json 内容，未找到返回 None
        """
        branch_path = self._get_branch_path(project_id, branch)
        latest_path = f"{branch_path}/latest.json"
        
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=latest_path
        )
        
        try:
            data = blob_client.download_blob().readall()
            return json.loads(data)
        except Exception:
            return None
    
    def record_branch_fork(
        self,
        project_id: str,
        new_branch: str,
        base_branch: str,
        base_commit: str,
        fork_type: str = "branch",
        created_by: Optional[str] = None
    ) -> bool:
        """
        记录分支派生关系
        
        Args:
            project_id: 项目 ID
            new_branch: 新分支名
            base_branch: 基准分支名
            base_commit: 基准 commit SHA
            fork_type: 派生类型 (branch/merge/rebase)
            created_by: 创建者
            
        Returns:
            成功返回 True
        """
        branch_path = self._get_branch_path(project_id, new_branch)
        parent_path = f"{branch_path}/parent_branch.json"
        
        fork_info = {
            "base_branch": base_branch,
            "base_commit": base_commit,
            "created_at": datetime.now().isoformat(),
            "fork_type": fork_type,
            "created_by": created_by
        }
        
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=parent_path
        )
        
        try:
            blob_client.upload_blob(
                json.dumps(fork_info, indent=2),
                overwrite=True
            )
            log_info(f"Recorded branch fork: {new_branch} <- {base_branch}@{base_commit[:8]}")
            return True
        except Exception as e:
            log_error(f"Failed to record branch fork: {e}")
            return False
    
    def _get_base_branch_info(self, project_id: str, branch: str) -> Optional[dict]:
        """
        获取分支的基准分支信息
        
        Args:
            project_id: 项目 ID
            branch: 分支名
            
        Returns:
            parent_branch.json 内容，未找到返回 None
        """
        branch_path = self._get_branch_path(project_id, branch)
        parent_path = f"{branch_path}/parent_branch.json"
        
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=parent_path
        )
        
        try:
            data = blob_client.download_blob().readall()
            return json.loads(data)
        except Exception:
            return None
    
    def _get_metadata(self, project_id: str, branch: str, commit_sha: str) -> Optional[dict]:
        """
        获取指定 commit 的 metadata.json
        
        Args:
            project_id: 项目 ID
            branch: 分支名
            commit_sha: Commit SHA
            
        Returns:
            metadata 字典，未找到返回 None
        """
        metadata_path = self._get_metadata_path(project_id, branch, commit_sha)
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=metadata_path
        )
        
        try:
            data = blob_client.download_blob().readall()
            return json.loads(data)
        except Exception:
            return None
    
    def _find_commit_in_other_branches(
        self, 
        project_id: str, 
        current_branch: str, 
        commit_sha: str
    ) -> Optional[dict]:
        """
        在其他分支中查找相同 commit 的上下文
        
        用于新分支场景：如果从 main 创建 feature-x，且 commit 相同，
        可以直接复用 main 分支的上下文，无需重新上传。
        
        Args:
            project_id: 项目 ID
            current_branch: 当前分支（排除）
            commit_sha: 要查找的 commit SHA
            
        Returns:
            找到返回 metadata 字典，否则返回 None
        """
        log_info(f"Searching for commit {commit_sha[:8]} in other branches...")
        
        # 常见的基准分支列表
        common_branches = ['main', 'master', 'develop', 'dev']
        
        for branch in common_branches:
            if branch == current_branch:
                continue
            
            metadata = self._get_metadata(project_id, branch, commit_sha)
            if metadata:
                log_info(f"✓ Found commit in branch '{branch}'")
                return metadata
        
        # 尝试从 base_branches.json 获取更多分支信息
        try:
            blob_path = f"{project_id}/_base_branches.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_path
            )
            data = blob_client.download_blob().readall()
            base_branches = json.loads(data)
            
            # 检查所有记录的分支
            for branch_name in base_branches.keys():
                if branch_name == current_branch:
                    continue
                if branch_name in common_branches:  # 已检查过
                    continue
                    
                metadata = self._get_metadata(project_id, branch_name, commit_sha)
                if metadata:
                    log_info(f"✓ Found commit in branch '{branch_name}'")
                    return metadata
        except Exception:
            pass  # base_branches.json 不存在，跳过
        
        log_info(f"Commit {commit_sha[:8]} not found in other branches")
        return None
    
    def find_best_context(
        self,
        project_id: str,
        branch: str,
        commit_sha: str,
        parent_commit: Optional[str] = None
    ) -> Optional[dict]:
        """
        智能查找最佳可用缓存（Level 1-4）
        
        查找优先级：
        1. 当前 commit（精确匹配）
        2. 父 commit（增量更新）
        3. 分支最新 commit（增量更新）
        4. 基准分支的 base_commit（跨分支复用）
        
        Args:
            project_id: 项目 ID
            branch: 分支名
            commit_sha: 当前 commit SHA
            parent_commit: 父 commit SHA（可选）
            
        Returns:
            {
                "found": True/False,
                "commit_sha": "...",
                "metadata": {...},
                "reuse_strategy": "exact|incremental|cross-branch|full_analysis",
                "base_branch": "..." (仅跨分支时)
            }
        """
        log_info(f"Searching for best cache: {project_id}/{branch}@{commit_sha[:8]}")
        
        # === Level 1: 精确匹配（当前 commit） ===
        log_info("Level 1: Checking exact match...")
        metadata = self._get_metadata(project_id, branch, commit_sha)
        if metadata:
            log_info(f"✓ Found exact match: {commit_sha[:8]}")
            return {
                "found": True,
                "commit_sha": commit_sha,
                "metadata": metadata,
                "reuse_strategy": "exact"
            }
        
        # === Level 2: 父 commit（增量更新） ===
        if parent_commit:
            log_info(f"Level 2: Checking parent commit {parent_commit[:8]}...")
            metadata = self._get_metadata(project_id, branch, parent_commit)
            if metadata:
                log_info(f"✓ Found parent commit: {parent_commit[:8]}")
                return {
                    "found": True,
                    "commit_sha": parent_commit,
                    "metadata": metadata,
                    "reuse_strategy": "incremental"
                }
        
        # === Level 3: 分支最新 commit ===
        log_info("Level 3: Checking branch latest...")
        latest_info = self._get_branch_latest(project_id, branch)
        if latest_info and latest_info.get("commit_sha") != commit_sha:
            latest_commit = latest_info["commit_sha"]
            metadata = self._get_metadata(project_id, branch, latest_commit)
            if metadata:
                log_info(f"✓ Found branch latest: {latest_commit[:8]}")
                return {
                    "found": True,
                    "commit_sha": latest_commit,
                    "metadata": metadata,
                    "reuse_strategy": "incremental"
                }
        
        # === Level 4: 基准分支（跨分支复用） ===
        log_info("Level 4: Checking base branch...")
        base_branch_info = self._get_base_branch_info(project_id, branch)
        if base_branch_info:
            base_branch = base_branch_info["base_branch"]
            base_commit = base_branch_info["base_commit"]
            log_info(f"Found base branch: {base_branch}@{base_commit[:8]}")
            
            metadata = self._get_metadata(project_id, base_branch, base_commit)
            if metadata:
                log_info(f"✓ Found base branch context: {base_branch}@{base_commit[:8]}")
                return {
                    "found": True,
                    "commit_sha": base_commit,
                    "metadata": metadata,
                    "reuse_strategy": "cross-branch",
                    "base_branch": base_branch
                }
        
        # === Level 5: 内容相似（rebase 场景） ===
        # 注意：Level 5 需要 git 仓库访问，暂时跳过
        # TODO: 实现 _find_content_similar_commit()
        
        # === Level 6: 未找到任何缓存 ===
        log_info("✗ No cache found, will perform full analysis")
        return {
            "found": False,
            "reuse_strategy": "full_analysis"
        }
    
    def _calculate_similarity(self, tree1: set, tree2: set) -> float:
        """
        计算两个文件树的 Jaccard 相似度
        
        Args:
            tree1: 文件集合 1
            tree2: 文件集合 2
            
        Returns:
            相似度（0-1）
        """
        if not tree1 and not tree2:
            return 1.0
        if not tree1 or not tree2:
            return 0.0
        
        intersection = len(tree1 & tree2)
        union = len(tree1 | tree2)
        return intersection / union if union > 0 else 0.0
    
    def upload_context_with_dedup(self, local_dir: Path, project_id: str, branch: str, 
                                   commit_sha: str, parent_metadata: Optional[dict] = None) -> bool:
        """
        使用去重上传项目理解上下文到 Blob Storage
        
        Args:
            local_dir: 本地 .copilot 目录路径
            project_id: GitLab 项目 ID
            branch: 分支名
            commit_sha: Commit SHA
            parent_metadata: 父 commit 的 metadata（用于增量去重）
            
        Returns:
            成功返回 True
        """
        if not local_dir.exists():
            log_error(f"Directory not found: {local_dir}")
            return False
        
        # === 优化：检查当前分支是否已存在该 commit 的上下文 ===
        existing_metadata = self._get_metadata(project_id, branch, commit_sha)
        if existing_metadata:
            log_info(f"✓ Context already exists for {branch}@{commit_sha[:8]}, skipping upload")
            return True
        
        # === 优化：检查其他分支是否存在相同 commit 的上下文 ===
        # 如果 commit 相同，可以直接创建引用（metadata 指向相同的 content objects）
        cross_branch_metadata = self._find_commit_in_other_branches(project_id, branch, commit_sha)
        if cross_branch_metadata:
            source_branch = cross_branch_metadata.get("branch", "unknown")
            log_info(f"✓ Found same commit in branch '{source_branch}', creating reference...")
            
            # 创建引用 metadata（复用 content_objects）
            reference_metadata = {
                "commit_sha": commit_sha,
                "branch": branch,
                "project_id": project_id,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "content_objects": cross_branch_metadata.get("content_objects", []),
                "stats": cross_branch_metadata.get("stats", {}),
                "reference_from": {
                    "branch": source_branch,
                    "commit_sha": commit_sha
                }
            }
            
            # 上传引用 metadata
            metadata_path = self._get_metadata_path(project_id, branch, commit_sha)
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=metadata_path
            )
            try:
                blob_client.upload_blob(json.dumps(reference_metadata, indent=2), overwrite=True)
                log_info(f"✓ Created reference metadata: {metadata_path}")
                self._update_branch_latest(project_id, branch, commit_sha, reference_metadata)
                return True
            except Exception as e:
                log_error(f"Failed to create reference metadata: {e}")
                # Fall through to normal upload
        
        # 构建 parent 的 content_objects 索引（路径 → hash）
        parent_objects = {}
        if parent_metadata and "content_objects" in parent_metadata:
            parent_objects = {
                obj["file_path"]: obj["content_hash"] 
                for obj in parent_metadata["content_objects"]
            }
        
        # 统计信息
        stats = {
            "total_files": 0,
            "inherited_files": 0,
            "updated_files": 0,
            "new_files": 0,
            "uploaded_objects": 0
        }
        
        # 扫描所有文件并计算 hash
        content_objects = []
        for file_path in local_dir.rglob('*'):
            if not file_path.is_file():
                continue
            
            stats["total_files"] += 1
            
            # 计算相对路径（相对于 local_dir 的父目录，保持兼容性）
            rel_path = str(file_path.relative_to(local_dir.parent))
            
            # 计算 content hash
            content_hash = self._compute_file_hash(file_path)
            file_size = file_path.stat().st_size
            
            # 判断来源
            source = "new"
            source_commit = commit_sha
            
            if rel_path in parent_objects:
                parent_hash = parent_objects[rel_path]
                if content_hash == parent_hash:
                    # 内容未变，直接复用
                    source = "inherited"
                    source_commit = parent_metadata.get("commit_sha", "unknown")
                    stats["inherited_files"] += 1
                    log_info(f"✓ Inherited: {rel_path} (hash: {content_hash[:12]})")
                else:
                    # 内容已更新
                    source = "updated"
                    stats["updated_files"] += 1
                    log_info(f"↻ Updated: {rel_path} (hash: {content_hash[:12]})")
            else:
                stats["new_files"] += 1
                log_info(f"+ New: {rel_path} (hash: {content_hash[:12]})")
            
            # 记录 content object 信息
            content_objects.append({
                "file_path": rel_path,
                "content_hash": content_hash,
                "size": file_size,
                "source": source,
                "source_commit": source_commit
            })
            
            # 检查 content object 是否已存在
            if not self._content_exists(content_hash):
                # 上传 content object
                success = self._upload_content_object(file_path, content_hash)
                if not success:
                    log_error(f"Failed to upload content object: {content_hash}")
                    return False
                stats["uploaded_objects"] += 1
            else:
                log_info(f"✓ Content exists: {content_hash[:12]} (skipped upload)")
        
        # 计算去重比率
        dedup_ratio = stats["inherited_files"] / stats["total_files"] if stats["total_files"] > 0 else 0
        
        # 构建 metadata.json
        metadata = {
            "commit_sha": commit_sha,
            "branch": branch,
            "project_id": project_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "content_objects": content_objects,
            "stats": {
                "total_files": stats["total_files"],
                "inherited_files": stats["inherited_files"],
                "updated_files": stats["updated_files"],
                "new_files": stats["new_files"],
                "deduplication_ratio": round(dedup_ratio, 4)
            }
        }
        
        # 上传 metadata.json
        metadata_path = self._get_metadata_path(project_id, branch, commit_sha)
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=metadata_path
        )
        
        try:
            blob_client.upload_blob(
                json.dumps(metadata, indent=2),
                overwrite=True
            )
            log_info(f"✓ Uploaded metadata: {metadata_path}")
        except Exception as e:
            log_error(f"Failed to upload metadata: {e}")
            return False
        
        # 更新 branch latest.json
        self._update_branch_latest(project_id, branch, commit_sha, metadata)
        
        # 输出统计信息
        log_info(f"\nSUCCESS: Upload completed with deduplication:")
        log_info(f"  Total files: {stats['total_files']}")
        log_info(f"  Inherited: {stats['inherited_files']} (reused)")
        log_info(f"  Updated: {stats['updated_files']}")
        log_info(f"  New: {stats['new_files']}")
        log_info(f"  Uploaded objects: {stats['uploaded_objects']}")
        log_info(f"  Deduplication ratio: {dedup_ratio:.2%}")
        
        return True
    
    def upload_context(self, local_dir: Path, project_id: str, branch: str, commit_sha: str) -> bool:
        """
        上传项目理解上下文到 Blob Storage（兼容旧版）
        
        已废弃，建议使用 upload_context_with_dedup()
        
        Args:
            local_dir: 本地 .copilot 目录路径
            project_id: GitLab 项目 ID
            branch: 分支名
            commit_sha: Commit SHA
            
        Returns:
            成功返回 True
        """
        log_warn("Using deprecated upload_context(), consider using upload_context_with_dedup()")
        return self.upload_context_with_dedup(local_dir, project_id, branch, commit_sha)
    
    def download_context(self, local_dir: Path, project_id: str, branch: str, commit_sha: str) -> bool:
        """
        从 Blob Storage 下载项目理解上下文（基于 metadata.json）
        
        Args:
            local_dir: 本地目标目录（通常是 repo-xxx/.copilot）
            project_id: GitLab 项目 ID
            branch: 分支名
            commit_sha: Commit SHA
            
        Returns:
            成功返回 True
        """
        local_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 下载 metadata.json
        metadata = self._get_metadata(project_id, branch, commit_sha)
        if not metadata:
            log_error(f"No metadata found for {project_id}/{branch}/{commit_sha}")
            return False
        
        if "content_objects" not in metadata:
            log_warn("Metadata does not contain content_objects, falling back to legacy download")
            return self._download_context_legacy(local_dir, project_id, branch, commit_sha)
        
        # 2. 批量下载 content objects
        content_objects = metadata["content_objects"]
        log_info(f"Downloading {len(content_objects)} files...")
        
        downloaded_count = 0
        failed_count = 0
        
        for obj in content_objects:
            file_path = obj["file_path"]
            content_hash = obj["content_hash"]
            
            # 兼容性处理：如果 file_path 以 .copilot/ 开头，去掉这个前缀
            # 因为上传时 rel_path 是相对于 local_dir.parent 的
            if file_path.startswith(".copilot/"):
                file_path = file_path[len(".copilot/"):]
            
            # 目标本地文件路径
            local_file = local_dir / file_path
            local_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 下载 content object
            success = self._download_content_object(content_hash, local_file)
            if success:
                log_info(f"✓ {file_path} (hash: {content_hash[:12]})")
                downloaded_count += 1
            else:
                log_error(f"✗ Failed to download: {file_path}")
                failed_count += 1
        
        if failed_count > 0:
            log_warn(f"Downloaded {downloaded_count}/{len(content_objects)} files ({failed_count} failed)")
            return False
        
        log_info(f"SUCCESS Downloaded {downloaded_count} files")
        return True
    
    def _download_context_legacy(self, local_dir: Path, project_id: str, branch: str, commit_sha: str) -> bool:
        """
        旧版下载方法（兼容性）
        
        Args:
            local_dir: 本地目标目录
            project_id: GitLab 项目 ID
            branch: 分支名
            commit_sha: Commit SHA
            
        Returns:
            成功返回 True
        """
        # 查找该 commit 的所有 blob
        prefix = self._get_blob_path(project_id, branch, commit_sha, "")
        
        try:
            blob_list = self.container_client.list_blobs(name_starts_with=prefix)
            
            downloaded_count = 0
            for blob in blob_list:
                # 提取文件相对路径
                rel_path = blob.name[len(prefix):]
                local_file = local_dir.parent / rel_path
                
                # 创建父目录
                local_file.parent.mkdir(parents=True, exist_ok=True)
                
                # 下载文件
                blob_client = self.blob_service_client.get_blob_client(
                    container=self.container_name,
                    blob=blob.name
                )
                
                with open(local_file, 'wb') as f:
                    data = blob_client.download_blob()
                    f.write(data.readall())
                
                log_info(f"Downloaded: {rel_path}")
                downloaded_count += 1
            
            if downloaded_count == 0:
                log_info(f"No cached context found for {project_id}/{branch}/{commit_sha}")
                return False
            
            log_info(f"SUCCESS: Downloaded {downloaded_count} files")
            return True
            
        except Exception as e:
            log_error(f"Failed to download context: {e}")
            return False
    
    def find_latest_context(self, project_id: str, branch: str) -> Optional[str]:
        """
        查找指定项目和分支的最新缓存
        
        Args:
            project_id: GitLab 项目 ID
            branch: 分支名
            
        Returns:
            最新的 commit SHA，如果没有缓存返回 None
        """
        prefix = self._get_blob_prefix(project_id, branch) + "/"
        
        try:
            # 列出所有 commit 目录
            blob_list = self.container_client.list_blobs(name_starts_with=prefix)
            
            commits = set()
            for blob in blob_list:
                # 从路径中提取 commit SHA
                # blob.name 格式: {project_id}/{branch}/{commit_sha}/.copilot/xxx
                parts = blob.name[len(prefix):].split('/')
                if len(parts) > 0:
                    commits.add(parts[0])
            
            if not commits:
                return None
            
            # 返回最新的（按字母序，通常 SHA 越大越新）
            return sorted(commits)[-1]
            
        except Exception as e:
            log_error(f"Failed to find latest context: {e}")
            return None


def main():
    """CLI 入口"""
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description='Azure Blob Storage cache manager for project context')
    parser.add_argument('action', choices=['upload', 'download', 'find', 'find-best', 'record-fork'], help='Action to perform')
    parser.add_argument('--connection-string', help='Azure Storage connection string (or set AZURE_STORAGE_CONNECTION_STRING env var)')
    parser.add_argument('--container', default='code', help='Container name (default: code)')
    parser.add_argument('--project-id', required=True, help='GitLab project ID')
    parser.add_argument('--branch', required=True, help='Branch name')
    parser.add_argument('--commit', help='Commit SHA')
    parser.add_argument('--local-dir', help='Local directory path')
    parser.add_argument('--parent-commit', help='Parent commit SHA for find-best')
    parser.add_argument('--base-branch', help='Base branch name (for record-fork)')
    parser.add_argument('--base-commit', help='Base commit SHA (for record-fork)')
    parser.add_argument('--fork-type', default='branch', help='Fork type: branch/merge/rebase')
    parser.add_argument('--created-by', help='Creator username')
    
    args = parser.parse_args()
    
    # 优先使用命令行参数，否则从环境变量读取
    connection_string = args.connection_string or os.getenv('AZURE_STORAGE_CONNECTION_STRING')
    if not connection_string:
        log_error("Azure Storage connection string not provided. Use --connection-string or set AZURE_STORAGE_CONNECTION_STRING env var")
        sys.exit(1)
    
    cache = BlobCache(connection_string, args.container)
    
    if args.action == 'upload':
        if not args.local_dir or not args.commit:
            log_error(" --local-dir and --commit are required for upload")
            sys.exit(1)
        
        # 查找父 commit 的 metadata（用于去重）
        parent_metadata = None
        if args.parent_commit:
            parent_metadata = cache._get_metadata(args.project_id, args.branch, args.parent_commit)
            if parent_metadata:
                log_info(f"Found parent metadata: {args.parent_commit[:8]}")
        
        success = cache.upload_context_with_dedup(
            Path(args.local_dir),
            args.project_id,
            args.branch,
            args.commit,
            parent_metadata
        )
        sys.exit(0 if success else 1)
    
    elif args.action == 'download':
        if not args.local_dir or not args.commit:
            log_error(" --local-dir and --commit are required for download")
            sys.exit(1)
        
        success = cache.download_context(
            Path(args.local_dir),
            args.project_id,
            args.branch,
            args.commit
        )
        sys.exit(0 if success else 1)
    
    elif args.action == 'find':
        commit = cache.find_latest_context(args.project_id, args.branch)
        if commit:
            print(commit, file=sys.stderr)
            sys.exit(0)
        else:
            log_info(f"No cache found for {args.project_id}/{args.branch}")
            sys.exit(1)
    
    elif args.action == 'find-best':
        if not args.commit:
            log_error(" --commit is required for find-best")
            sys.exit(1)
        
        result = cache.find_best_context(
            args.project_id,
            args.branch,
            args.commit,
            args.parent_commit
        )
        
        # 输出 JSON 格式结果（单行，方便 shell 解析）
        print(json.dumps(result))
        # find-best 总是 exit 0，因为 "未找到缓存" 不是错误
        sys.exit(0)
    
    elif args.action == 'record-fork':
        if not args.base_branch or not args.base_commit:
            log_error(" --base-branch and --base-commit are required for record-fork")
            sys.exit(1)
        
        success = cache.record_branch_fork(
            args.project_id,
            args.branch,  # new_branch
            args.base_branch,
            args.base_commit,
            args.fork_type,
            args.created_by
        )
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
