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


class BlobCache:
    """Azure Blob Storage 缓存管理器"""
    
    def __init__(self, connection_string: str, container_name: str = "code"):
        """
        初始化
        
        Args:
            connection_string: Azure Storage 连接字符串
            container_name: 容器名称（默认: code）
        """
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_name = container_name
        self.container_client = self.blob_service_client.get_container_client(container_name)
        
        # 确保容器存在
        try:
            self.container_client.get_container_properties()
        except Exception:
            print(f"[INFO] Creating container: {container_name}")
            self.container_client.create_container()
    
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
            print(f"[ERROR] Failed to compute hash for {file_path}: {e}")
            raise
    
    def _get_blob_prefix(self, project_id: str, branch: str) -> str:
        """
        生成 blob 路径前缀
        
        格式: {project_id}/{branch}/
        """
        # 清理分支名中的特殊字符
        safe_branch = branch.replace('/', '_').replace('\\', '_')
        return f"{project_id}/{safe_branch}"
    
    def _get_blob_path(self, project_id: str, branch: str, commit_sha: str, filename: str) -> str:
        """
        生成完整的 blob 路径
        
        格式: {project_id}/{branch}/{commit_sha}/{filename}
        """
        prefix = self._get_blob_prefix(project_id, branch)
        return f"{prefix}/{commit_sha}/{filename}"
    
    def upload_context(self, local_dir: Path, project_id: str, branch: str, commit_sha: str) -> bool:
        """
        上传项目理解上下文到 Blob Storage
        
        Args:
            local_dir: 本地 .copilot 目录路径
            project_id: GitLab 项目 ID
            branch: 分支名
            commit_sha: Commit SHA
            
        Returns:
            成功返回 True
        """
        if not local_dir.exists():
            print(f"[ERROR] Directory not found: {local_dir}")
            return False
        
        # 上传所有文件
        uploaded_count = 0
        for file_path in local_dir.rglob('*'):
            if not file_path.is_file():
                continue
            
            # 计算相对路径
            rel_path = file_path.relative_to(local_dir.parent)
            blob_path = self._get_blob_path(project_id, branch, commit_sha, str(rel_path))
            
            try:
                blob_client = self.blob_service_client.get_blob_client(
                    container=self.container_name,
                    blob=blob_path
                )
                
                with open(file_path, 'rb') as data:
                    blob_client.upload_blob(data, overwrite=True)
                
                print(f"[INFO] Uploaded: {blob_path}")
                uploaded_count += 1
                
            except Exception as e:
                print(f"[ERROR] Failed to upload {file_path}: {e}")
                return False
        
        print(f"[SUCCESS] Uploaded {uploaded_count} files to {self._get_blob_prefix(project_id, branch)}/{commit_sha}")
        return True
    
    def download_context(self, local_dir: Path, project_id: str, branch: str, commit_sha: str) -> bool:
        """
        从 Blob Storage 下载项目理解上下文
        
        Args:
            local_dir: 本地目标目录（通常是 repo-xxx/.copilot）
            project_id: GitLab 项目 ID
            branch: 分支名
            commit_sha: Commit SHA
            
        Returns:
            成功返回 True
        """
        local_dir.mkdir(parents=True, exist_ok=True)
        
        # 查找该 commit 的所有 blob
        prefix = self._get_blob_path(project_id, branch, commit_sha, "")
        
        try:
            blob_list = self.container_client.list_blobs(name_starts_with=prefix)
            
            downloaded_count = 0
            for blob in blob_list:
                # 提取文件相对路径
                # blob.name 格式: {project_id}/{branch}/{commit_sha}/.copilot/xxx
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
                
                print(f"[INFO] Downloaded: {rel_path}")
                downloaded_count += 1
            
            if downloaded_count == 0:
                print(f"[INFO] No cached context found for {project_id}/{branch}/{commit_sha}")
                return False
            
            print(f"[SUCCESS] Downloaded {downloaded_count} files")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to download context: {e}")
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
            print(f"[ERROR] Failed to find latest context: {e}")
            return None


def main():
    """CLI 入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Azure Blob Storage cache manager for project context')
    parser.add_argument('action', choices=['upload', 'download', 'find'], help='Action to perform')
    parser.add_argument('--connection-string', required=True, help='Azure Storage connection string')
    parser.add_argument('--container', default='code', help='Container name (default: code)')
    parser.add_argument('--project-id', required=True, help='GitLab project ID')
    parser.add_argument('--branch', required=True, help='Branch name')
    parser.add_argument('--commit', help='Commit SHA')
    parser.add_argument('--local-dir', help='Local directory path')
    
    args = parser.parse_args()
    
    cache = BlobCache(args.connection_string, args.container)
    
    if args.action == 'upload':
        if not args.local_dir or not args.commit:
            print("[ERROR] --local-dir and --commit are required for upload")
            sys.exit(1)
        
        success = cache.upload_context(
            Path(args.local_dir),
            args.project_id,
            args.branch,
            args.commit
        )
        sys.exit(0 if success else 1)
    
    elif args.action == 'download':
        if not args.local_dir or not args.commit:
            print("[ERROR] --local-dir and --commit are required for download")
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
            print(commit)
            sys.exit(0)
        else:
            print(f"[INFO] No cache found for {args.project_id}/{args.branch}")
            sys.exit(1)


if __name__ == '__main__':
    main()
