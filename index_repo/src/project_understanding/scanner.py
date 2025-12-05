"""文件扫描器 - 扫描项目结构，提取关键文件"""

import os
from pathlib import Path
from typing import Optional

from .models import FileInfo, ScanResult


# 忽略的目录
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv',
    'dist', 'build', '.next', '.nuxt', 'target', 'bin', 'obj',
    '.idea', '.vscode', '.cache', 'coverage', '.pytest_cache',
}

# 忽略的文件模式
IGNORE_PATTERNS = {
    '*.pyc', '*.pyo', '*.class', '*.o', '*.so', '*.dll',
    '*.lock', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    '*.min.js', '*.min.css', '*.map',
}

# 关键文件类别和模式
KEY_FILE_PATTERNS = {
    'config': [
        'package.json', 'pyproject.toml', 'Cargo.toml', 'go.mod',
        'pom.xml', 'build.gradle', 'composer.json', 'Gemfile',
        'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
        '.env.example', 'config.yaml', 'config.yml', 'config.json',
    ],
    'schema': [
        'schema.prisma', 'prisma/schema.prisma',
        '*.sql', 'migrations/*.sql',
        'models.py', '*/models.py', '*/models/*.py',
        '*.graphql', 'schema.graphql',
        'openapi.yaml', 'openapi.yml', 'swagger.yaml', 'swagger.yml',
    ],
    'doc': [
        'README.md', 'README.rst', 'README.txt',
        'CONTRIBUTING.md', 'ARCHITECTURE.md',
        'docs/*.md', 'doc/*.md',
    ],
    'auth': [
        '**/auth/**', '**/authentication/**', '**/authorization/**',
        '**/middleware/auth*', '**/guards/**',
        '.env*',
    ],
    'api': [
        '**/routes/**', '**/router/**', '**/controllers/**',
        '**/api/**', '**/endpoints/**', '**/handlers/**',
    ],
}

# 语言检测
LANGUAGE_INDICATORS = {
    'TypeScript': ['tsconfig.json', '*.ts', '*.tsx'],
    'JavaScript': ['package.json', '*.js', '*.jsx'],
    'Python': ['pyproject.toml', 'setup.py', 'requirements.txt', '*.py'],
    'Go': ['go.mod', '*.go'],
    'Rust': ['Cargo.toml', '*.rs'],
    'Java': ['pom.xml', 'build.gradle', '*.java'],
    'C#': ['*.csproj', '*.cs'],
    'Ruby': ['Gemfile', '*.rb'],
    'PHP': ['composer.json', '*.php'],
}


def should_ignore(path: Path) -> bool:
    """检查是否应该忽略该路径"""
    # 检查目录
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    
    # 检查文件模式
    name = path.name
    for pattern in IGNORE_PATTERNS:
        if pattern.startswith('*'):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True
    
    return False


def match_pattern(path: Path, pattern: str) -> bool:
    """检查路径是否匹配模式"""
    path_str = str(path)
    
    if '**' in pattern:
        # 递归匹配
        pattern_parts = pattern.split('**')
        if len(pattern_parts) == 2:
            prefix, suffix = pattern_parts
            if prefix and not path_str.startswith(prefix.rstrip('/')):
                return False
            if suffix and not path_str.endswith(suffix.lstrip('/')):
                return False
            return True
    elif '*' in pattern:
        # 简单通配符
        if pattern.startswith('*'):
            return path.name.endswith(pattern[1:])
        elif pattern.endswith('*'):
            return path.name.startswith(pattern[:-1])
    else:
        # 精确匹配或路径包含
        return path.name == pattern or pattern in path_str
    
    return False


def detect_languages(files: list[Path]) -> list[str]:
    """检测项目使用的编程语言"""
    detected = set()
    
    for lang, indicators in LANGUAGE_INDICATORS.items():
        for indicator in indicators:
            for file in files:
                if match_pattern(file, indicator):
                    detected.add(lang)
                    break
    
    return sorted(list(detected))


def read_file_safe(path: Path, max_size: int = 100_000) -> Optional[str]:
    """安全读取文件内容"""
    try:
        if path.stat().st_size > max_size:
            return f"[File too large: {path.stat().st_size} bytes]"
        return path.read_text(encoding='utf-8', errors='ignore')
    except Exception as e:
        return f"[Error reading file: {e}]"


def scan_project(workspace: Path, max_files: int = 500) -> ScanResult:
    """
    扫描项目目录，提取结构和关键文件
    
    Args:
        workspace: 项目根目录
        max_files: 最大扫描文件数
    
    Returns:
        ScanResult: 扫描结果
    """
    workspace = Path(workspace).resolve()
    all_files: list[Path] = []
    file_tree_lines: list[str] = []
    key_files: dict[str, FileInfo] = {}
    
    # 遍历目录
    for root, dirs, files in os.walk(workspace):
        # 过滤忽略的目录
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        rel_root = Path(root).relative_to(workspace)
        depth = len(rel_root.parts)
        
        # 限制深度
        if depth > 10:
            continue
        
        # 添加目录到文件树
        if depth > 0:
            indent = "  " * (depth - 1)
            file_tree_lines.append(f"{indent}{rel_root.name}/")
        
        # 处理文件
        for file in sorted(files):
            file_path = Path(root) / file
            rel_path = file_path.relative_to(workspace)
            
            if should_ignore(rel_path):
                continue
            
            all_files.append(rel_path)
            
            # 添加到文件树
            indent = "  " * depth
            file_tree_lines.append(f"{indent}{file}")
            
            # 检查是否是关键文件
            for category, patterns in KEY_FILE_PATTERNS.items():
                for pattern in patterns:
                    if match_pattern(rel_path, pattern):
                        # 读取文件内容（限制大小）
                        content = read_file_safe(file_path)
                        
                        file_info = FileInfo(
                            path=str(rel_path),
                            category=category,
                            size=file_path.stat().st_size,
                            content=content,
                        )
                        
                        # 每个类别保留最重要的几个文件
                        if category not in key_files:
                            key_files[category] = file_info
                        elif category == 'schema' and 'prisma' in str(rel_path):
                            # Prisma schema 优先级更高
                            key_files[category] = file_info
                        
                        break
            
            # 限制文件数
            if len(all_files) >= max_files:
                file_tree_lines.append(f"... (truncated, total files > {max_files})")
                break
        
        if len(all_files) >= max_files:
            break
    
    # 检测语言
    languages = detect_languages(all_files)
    
    # 构建文件树字符串
    file_tree = "\n".join(file_tree_lines[:200])  # 限制行数
    if len(file_tree_lines) > 200:
        file_tree += f"\n... ({len(file_tree_lines) - 200} more lines)"
    
    return ScanResult(
        file_tree=file_tree,
        key_files=key_files,
        total_files=len(all_files),
        languages=languages,
    )


if __name__ == "__main__":
    # 测试
    import sys
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    result = scan_project(workspace)
    
    print("=== File Tree ===")
    print(result.file_tree[:2000])
    print(f"\n=== Total Files: {result.total_files} ===")
    print(f"=== Languages: {result.languages} ===")
    print(f"\n=== Key Files ===")
    for category, info in result.key_files.items():
        print(f"  {category}: {info.path} ({info.size} bytes)")
