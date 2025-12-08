#!/usr/bin/env python3
"""
Git diff 变更检测脚本
分析两个 commit 之间的文件变更，确定影响的项目理解模块
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional
import argparse


class ChangeDetector:
    """Git 变更检测器"""
    
    # 默认文件到模块的映射规则
    DEFAULT_MODULE_MAPPING = {
        "tech_stack": [
            "package.json",
            "requirements.txt",
            "go.mod",
            "Cargo.toml",
            "pom.xml",
            "build.gradle",
            "Dockerfile",
            "docker-compose.yml"
        ],
        "data_model": [
            "schema.prisma",
            "models.py",
            "schema.graphql",
            "*.proto",
            "migrations/"
        ],
        "api": [
            "src/api/",
            "src/routes/",
            "src/controllers/",
            "api/",
            "routes/"
        ],
        "security": [
            "src/auth/",
            "src/security/",
            "auth/",
            "security/"
        ],
        "domain": [
            "src/",
            "lib/"
        ]
    }
    
    def __init__(self, repo_path: Path, module_mapping: Optional[Dict[str, List[str]]] = None):
        """
        初始化检测器
        
        Args:
            repo_path: Git 仓库路径
            module_mapping: 自定义文件到模块的映射规则
        """
        self.repo_path = repo_path
        self.module_mapping = module_mapping or self.DEFAULT_MODULE_MAPPING
    
    def get_git_diff(self, base_commit: str, current_commit: str) -> Dict[str, List[str]]:
        """
        获取两个 commit 之间的文件变更
        
        Args:
            base_commit: 基准 commit SHA
            current_commit: 当前 commit SHA
            
        Returns:
            字典: {"added": [...], "modified": [...], "deleted": [...]}
        """
        try:
            # 运行 git diff 命令
            result = subprocess.run(
                ["git", "diff", "--name-status", f"{base_commit}..{current_commit}"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            changes = {
                "added": [],
                "modified": [],
                "deleted": []
            }
            
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                
                parts = line.split('\t', 1)
                if len(parts) != 2:
                    continue
                
                status, file_path = parts
                
                if status == 'A':
                    changes["added"].append(file_path)
                elif status == 'M':
                    changes["modified"].append(file_path)
                elif status == 'D':
                    changes["deleted"].append(file_path)
                elif status.startswith('R'):
                    # 重命名视为 modified
                    # 格式: R100\told_path\tnew_path
                    if '\t' in file_path:
                        _, new_path = file_path.split('\t', 1)
                        changes["modified"].append(new_path)
                    else:
                        changes["modified"].append(file_path)
            
            return changes
            
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to run git diff: {e}", file=sys.stderr)
            print(f"[ERROR] Output: {e.stderr}", file=sys.stderr)
            sys.exit(1)
    
    def match_file_to_modules(self, file_path: str) -> Set[str]:
        """
        将文件映射到影响的模块
        
        Args:
            file_path: 文件相对路径
            
        Returns:
            模块名集合
        """
        matched_modules = set()
        
        for module, patterns in self.module_mapping.items():
            for pattern in patterns:
                if self._matches_pattern(file_path, pattern):
                    matched_modules.add(module)
                    break
        
        return matched_modules
    
    def _matches_pattern(self, file_path: str, pattern: str) -> bool:
        """
        检查文件是否匹配模式
        
        Args:
            file_path: 文件路径
            pattern: 匹配模式
            
        Returns:
            是否匹配
        """
        # 精确匹配文件名
        if '/' not in pattern and '*' not in pattern:
            return Path(file_path).name == pattern
        
        # 目录匹配
        if pattern.endswith('/'):
            return file_path.startswith(pattern) or f"/{pattern}" in file_path
        
        # 通配符匹配
        if '*' in pattern:
            import fnmatch
            return fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(Path(file_path).name, pattern)
        
        # 部分路径匹配
        return pattern in file_path
    
    def estimate_impact(self, affected_modules: Set[str], changes: Dict[str, List[str]]) -> Dict[str, str]:
        """
        估算每个模块的影响程度
        
        Args:
            affected_modules: 受影响的模块集合
            changes: 变更字典
            
        Returns:
            模块 → 影响程度（none/low/medium/high）
        """
        all_modules = set(self.module_mapping.keys())
        impact = {}
        
        for module in all_modules:
            if module not in affected_modules:
                impact[module] = "none"
                continue
            
            # 统计该模块的变更文件数
            changed_count = 0
            for category in ["added", "modified", "deleted"]:
                for file_path in changes[category]:
                    if module in self.match_file_to_modules(file_path):
                        changed_count += 1
            
            # 根据变更数量判断影响程度
            if changed_count == 0:
                impact[module] = "none"
            elif changed_count <= 2:
                impact[module] = "low"
            elif changed_count <= 5:
                impact[module] = "medium"
            else:
                impact[module] = "high"
        
        return impact
    
    def detect(self, base_commit: str, current_commit: str) -> dict:
        """
        检测变更并生成完整报告
        
        Args:
            base_commit: 基准 commit SHA
            current_commit: 当前 commit SHA
            
        Returns:
            变更报告字典
        """
        print(f"[INFO] Analyzing changes: {base_commit[:8]}..{current_commit[:8]}")
        
        # 获取文件变更
        changes = self.get_git_diff(base_commit, current_commit)
        
        print(f"[INFO] Files changed:")
        print(f"  Added: {len(changes['added'])}")
        print(f"  Modified: {len(changes['modified'])}")
        print(f"  Deleted: {len(changes['deleted'])}")
        
        # 映射到模块
        affected_modules = set()
        for category in ["added", "modified", "deleted"]:
            for file_path in changes[category]:
                modules = self.match_file_to_modules(file_path)
                affected_modules.update(modules)
        
        print(f"[INFO] Affected modules: {', '.join(sorted(affected_modules))}")
        
        # 估算影响
        impact = self.estimate_impact(affected_modules, changes)
        
        # 生成报告
        report = {
            "base_commit": base_commit,
            "current_commit": current_commit,
            "affected_modules": sorted(list(affected_modules)),
            "added_files": changes["added"],
            "modified_files": changes["modified"],
            "deleted_files": changes["deleted"],
            "estimated_impact": impact,
            "total_changed_files": sum(len(changes[k]) for k in changes.keys())
        }
        
        return report


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(description='Detect git changes and map to project modules')
    parser.add_argument('--repo', default='.', help='Git repository path (default: current directory)')
    parser.add_argument('--base-commit', required=True, help='Base commit SHA')
    parser.add_argument('--current-commit', default='HEAD', help='Current commit SHA (default: HEAD)')
    parser.add_argument('--output', help='Output JSON file path (default: stdout)')
    parser.add_argument('--mapping', help='Custom module mapping JSON file')
    
    args = parser.parse_args()
    
    # 加载自定义映射
    module_mapping = None
    if args.mapping:
        with open(args.mapping, 'r') as f:
            module_mapping = json.load(f)
    
    # 执行检测
    detector = ChangeDetector(Path(args.repo), module_mapping)
    report = detector.detect(args.base_commit, args.current_commit)
    
    # 输出结果
    output_json = json.dumps(report, indent=2)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"[SUCCESS] Report saved to {args.output}")
    else:
        print("\n" + output_json)


if __name__ == '__main__':
    main()
