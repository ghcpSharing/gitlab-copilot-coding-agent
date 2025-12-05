"""Copilot CLI 调用封装

直接调用 copilot 命令（通过 stdin 传入 prompt）
与 mr_review_executor.py 保持一致的调用方式
"""

import subprocess
import logging
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CopilotResponse:
    """Copilot 响应"""
    success: bool
    content: str
    error: Optional[str] = None
    exit_code: int = 0


class CopilotClient:
    """Copilot CLI 客户端
    
    通过 subprocess 调用 copilot 命令，prompt 通过 stdin 传入
    """
    
    def __init__(
        self,
        timeout: int = 3600,  # 默认 1 小时
        max_retries: int = 2,
        allow_all_tools: bool = True,
        working_dir: Optional[Path] = None,
        # 兼容旧参数（忽略）
        model: str = "",
        verbose: bool = False
    ):
        """初始化客户端
        
        Args:
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
            allow_all_tools: 是否允许所有工具
            working_dir: 工作目录（用于 copilot 文件访问）
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.allow_all_tools = allow_all_tools
        self.working_dir = working_dir
    
    def call(
        self,
        prompt: str,
        context: Optional[str] = None,
        working_dir: Optional[Path] = None
    ) -> CopilotResponse:
        """调用 Copilot
        
        Args:
            prompt: 提示词
            context: 可选的上下文信息（会追加到 prompt）
            working_dir: 工作目录（覆盖实例配置）
            
        Returns:
            CopilotResponse: 响应对象
        """
        # 合并 prompt 和 context
        full_prompt = prompt
        if context:
            full_prompt = f"{prompt}\n\n---\nContext:\n{context}"
        
        # 构建命令
        cmd = ['copilot']
        if self.allow_all_tools:
            cmd.append('--allow-all-tools')
        
        # 确定工作目录
        cwd = working_dir or self.working_dir
        
        logger.debug(f"Calling copilot, prompt size: {len(full_prompt)} chars")
        
        try:
            result = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=cwd
            )
            
            if result.returncode == 0:
                return CopilotResponse(
                    success=True,
                    content=result.stdout.strip(),
                    exit_code=0
                )
            else:
                error_msg = result.stderr.strip() if result.stderr else f"Exit code: {result.returncode}"
                logger.warning(f"Copilot returned non-zero: {result.returncode}")
                logger.warning(f"stderr: {error_msg[:500]}")
                
                return CopilotResponse(
                    success=False,
                    content=result.stdout.strip(),  # 可能有部分输出
                    error=error_msg,
                    exit_code=result.returncode
                )
                
        except subprocess.TimeoutExpired:
            logger.error(f"Copilot timeout after {self.timeout}s")
            return CopilotResponse(
                success=False,
                content="",
                error=f"Timeout after {self.timeout}s",
                exit_code=124
            )
        except FileNotFoundError:
            logger.error("copilot command not found")
            return CopilotResponse(
                success=False,
                content="",
                error="copilot command not found. Is Copilot CLI installed?",
                exit_code=127
            )
        except Exception as e:
            logger.exception("Error calling Copilot")
            return CopilotResponse(
                success=False,
                content="",
                error=str(e),
                exit_code=1
            )
    
    def call_with_retry(
        self,
        prompt: str,
        context: Optional[str] = None,
        max_retries: Optional[int] = None,
        working_dir: Optional[Path] = None
    ) -> CopilotResponse:
        """带重试的 Copilot 调用
        
        Args:
            prompt: 提示词
            context: 可选的上下文信息
            max_retries: 最大重试次数（默认使用实例配置）
            working_dir: 工作目录
            
        Returns:
            CopilotResponse: 响应对象
        """
        retries = max_retries if max_retries is not None else self.max_retries
        last_response = None
        
        for attempt in range(retries + 1):
            if attempt > 0:
                logger.info(f"Retry attempt {attempt}/{retries}")
            
            response = self.call(prompt, context, working_dir)
            last_response = response
            
            if response.success:
                return response
            
            # 如果是超时，重试
            if response.exit_code == 124:
                logger.warning(f"Timeout on attempt {attempt + 1}, retrying...")
                continue
            
            # 命令不存在，不重试
            if response.exit_code == 127:
                logger.error("Copilot CLI not available, not retrying")
                break
            
            # 其他错误，记录并继续
            logger.warning(f"Error on attempt {attempt + 1}: {response.error}")
        
        return last_response or CopilotResponse(
            success=False,
            content="",
            error="Max retries exceeded",
            exit_code=1
        )
    
    def call_with_output_file(
        self,
        prompt: str,
        output_filename: str = "output.json",
        context: Optional[str] = None,
        working_dir: Optional[Path] = None
    ) -> tuple[CopilotResponse, Optional[dict]]:
        """调用 Copilot 并读取输出文件
        
        适用于需要 Copilot 生成结构化输出的场景
        
        Args:
            prompt: 提示词（应包含输出文件的指示）
            output_filename: 期望的输出文件名
            context: 可选的上下文信息
            working_dir: 工作目录
            
        Returns:
            (CopilotResponse, 输出文件内容dict或None)
        """
        import json
        
        cwd = working_dir or self.working_dir or Path.cwd()
        output_path = cwd / output_filename
        
        # 删除旧的输出文件
        if output_path.exists():
            output_path.unlink()
        
        response = self.call_with_retry(prompt, context, working_dir=cwd)
        
        # 尝试读取输出文件
        output_data = None
        if output_path.exists():
            try:
                output_data = json.loads(output_path.read_text(encoding='utf-8'))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse output file: {e}")
        
        return response, output_data


# 便捷函数
_default_client: Optional[CopilotClient] = None


def get_client(**kwargs) -> CopilotClient:
    """获取默认客户端实例（单例）"""
    global _default_client
    if _default_client is None:
        _default_client = CopilotClient(**kwargs)
    return _default_client


def call_copilot(
    prompt: str,
    context: Optional[str] = None,
    **kwargs
) -> CopilotResponse:
    """便捷函数：调用 Copilot
    
    Args:
        prompt: 提示词
        context: 可选的上下文信息
        **kwargs: 传递给 CopilotClient 的参数
        
    Returns:
        CopilotResponse: 响应对象
    """
    client = CopilotClient(**kwargs) if kwargs else get_client()
    return client.call_with_retry(prompt, context)
