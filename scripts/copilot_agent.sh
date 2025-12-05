#!/usr/bin/env bash
# =============================================================================
# Copilot Agent Wrapper Script
# 封装 gh copilot 调用，供 Python 通过 subprocess 调用
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# -----------------------------------------------------------------------------
# 配置
# -----------------------------------------------------------------------------
COPILOT_TIMEOUT="${COPILOT_TIMEOUT:-120}"
COPILOT_MODEL="${COPILOT_MODEL:-claude-sonnet-4}"
COPILOT_MAX_TOKENS="${COPILOT_MAX_TOKENS:-4096}"

# -----------------------------------------------------------------------------
# 帮助信息
# -----------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] <prompt_file> [context_file]

封装 gh copilot 调用，用于项目分析 Agent。

Arguments:
  prompt_file     包含提示词的文件路径
  context_file    可选，包含上下文信息的文件路径

Options:
  -o, --output FILE    输出文件路径（默认输出到 stdout）
  -t, --timeout SEC    超时时间（默认: ${COPILOT_TIMEOUT}）
  -m, --model MODEL    模型名称（默认: ${COPILOT_MODEL}）
  -v, --verbose        详细输出
  -h, --help           显示帮助信息

Environment Variables:
  COPILOT_TIMEOUT      超时时间
  COPILOT_MODEL        模型名称
  COPILOT_MAX_TOKENS   最大输出 token 数

Examples:
  $(basename "$0") prompts/tech_stack.txt context.txt
  $(basename "$0") -o result.md prompts/domain.txt
EOF
}

# -----------------------------------------------------------------------------
# 日志函数
# -----------------------------------------------------------------------------
VERBOSE=false

log_info() {
    if [[ "${VERBOSE}" == "true" ]]; then
        echo "[INFO] $*" >&2
    fi
}

log_error() {
    echo "[ERROR] $*" >&2
}

# -----------------------------------------------------------------------------
# 主函数
# -----------------------------------------------------------------------------
main() {
    local prompt_file=""
    local context_file=""
    local output_file=""
    local timeout="${COPILOT_TIMEOUT}"
    local model="${COPILOT_MODEL}"

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -o|--output)
                output_file="$2"
                shift 2
                ;;
            -t|--timeout)
                timeout="$2"
                shift 2
                ;;
            -m|--model)
                model="$2"
                shift 2
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            -*)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
            *)
                if [[ -z "${prompt_file}" ]]; then
                    prompt_file="$1"
                elif [[ -z "${context_file}" ]]; then
                    context_file="$1"
                else
                    log_error "Too many arguments"
                    usage
                    exit 1
                fi
                shift
                ;;
        esac
    done

    # 验证参数
    if [[ -z "${prompt_file}" ]]; then
        log_error "prompt_file is required"
        usage
        exit 1
    fi

    if [[ ! -f "${prompt_file}" ]]; then
        log_error "Prompt file not found: ${prompt_file}"
        exit 1
    fi

    # 读取 prompt
    local prompt
    prompt=$(cat "${prompt_file}")

    # 如果有 context 文件，追加到 prompt
    if [[ -n "${context_file}" && -f "${context_file}" ]]; then
        local context
        context=$(cat "${context_file}")
        prompt="${prompt}

---
Context:
${context}"
    fi

    log_info "Calling Copilot with model: ${model}"
    log_info "Timeout: ${timeout}s"
    log_info "Prompt length: ${#prompt} chars"

    # 调用 gh copilot
    local result
    local exit_code=0

    # 使用 timeout 命令限制执行时间
    # gh copilot suggest 使用 -t 指定目标类型
    result=$(timeout "${timeout}" gh copilot suggest -t shell "${prompt}" 2>&1) || exit_code=$?

    if [[ ${exit_code} -ne 0 ]]; then
        if [[ ${exit_code} -eq 124 ]]; then
            log_error "Copilot call timed out after ${timeout}s"
        else
            log_error "Copilot call failed with exit code: ${exit_code}"
            log_error "Output: ${result}"
        fi
        exit ${exit_code}
    fi

    # 输出结果
    if [[ -n "${output_file}" ]]; then
        echo "${result}" > "${output_file}"
        log_info "Result written to: ${output_file}"
    else
        echo "${result}"
    fi
}

# 如果直接运行脚本（而不是被 source）
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
