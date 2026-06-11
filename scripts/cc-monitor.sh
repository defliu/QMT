#!/bin/bash
# CC 调用监控器 — 记录每次 CC 调用的状态、时长、网络状况
#
# 用法：
#   作为管道：  echo "task" | ./scripts/cc-monitor.sh [log_label]
#   嵌入脚本：  source ./scripts/cc-monitor.sh  # 加载函数后手动调用
#
# 日志位置：  D:\QMT_STRATEGIES\worklog\cc-monitor\YYYY-MM-DD.md
#
# 输出：
#   除了透传 CC 的输出，还会在 stderr 打印监控摘要
#   日志文件记录完整调用记录

set -euo pipefail

# ── 配置 ──────────────────────────────────────────────
CC_CMD="C:\\Users\\Administrator\\AppData\\Roaming\\npm\\claude.cmd"
PROJECT_DIR="D:\\QMT_STRATEGIES"
MONITOR_LOG_DIR="/mnt/d/QMT_STRATEGIES/worklog/cc-monitor"
DATE_TAG=$(date +%Y-%m-%d)
TIME_TAG=$(date +%H:%M:%S)
TIMESTAMP=$(date +%s)
LABEL="${1:-unnamed-task}"
mkdir -p "$MONITOR_LOG_DIR"

# ── 网络检查 ──────────────────────────────────────────
check_network() {
    local result="ok"
    local detail=""
    
    # 测试 API 可达性 (用 CDN 或 google 做通用检查)
    if ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
        detail="internet=ok"
    else
        # 再试一次，避免误报
        if ping -c 1 -W 3 114.114.114.114 >/dev/null 2>&1; then
            detail="internet=ok(dns114)"
        else
            detail="internet=DOWN"
            result="down"
        fi
    fi
    
    # 测速到几个常见 API 端点（只试 curl，更精确）
    for endpoint in "https://api.anthropic.com" "https://api.openai.com"; do
        local curl_result
        curl_result=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$endpoint" 2>/dev/null || echo "timeout")
        detail="$detail | $endpoint=$curl_result"
    done
    
    echo "{\"status\":\"$result\",\"detail\":\"$detail\"}"
}

# ── 执行并监控 CC 调用 ──────────────────────────────
run_cc_monitored() {
    local task="$1"
    local task_label="$2"
    local start_ts
    start_ts=$(date +%s)
    local start_time
    start_time=$(date +%H:%M:%S)
    
    # 调用前网络检查
    local net_before
    net_before=$(check_network)
    
    # 临时文件
    local task_file_win="D:\\QMT_STRATEGIES\\.hermes_task_$$.txt"
    local task_file_ux="/mnt/d/QMT_STRATEGIES/.hermes_task_$$.txt"
    echo "$task" > "$task_file_ux"
    
    # ── 执行 CC ──
    local cc_output
    local cc_exit=0
    local output_truncated="no"
    
    set +e
    cc_output=$(cmd.exe /c "cd /d $PROJECT_DIR && type $task_file_win | $CC_CMD --dangerously-skip-permissions --print --add-dir $PROJECT_DIR" 2>&1)
    cc_exit=$?
    set -e
    
    local end_ts
    end_ts=$(date +%s)
    local end_time
    end_time=$(date +%H:%M:%S)
    local duration=$((end_ts - start_ts))
    
    # 清理
    rm -f "$task_file_ux"
    
    # 调用后网络检查
    local net_after
    net_after=$(check_network)
    
    # 检测输出是否被截断（CC 中途断连的典型迹象）
    local output_lines
    output_lines=$(echo "$cc_output" | wc -l)
    if [ $cc_exit -eq 0 ] && [ $output_lines -lt 3 ]; then
        output_truncated="maybe-truncated"
    fi
    
    # ── 写日志 ──
    local log_file="$MONITOR_LOG_DIR/$DATE_TAG.md"
    local duration_min
    duration_min=$(echo "scale=1; $duration / 60" | bc)
    
    {
        echo ""
        echo "## $TIME_TAG | $task_label"
        echo ""
        echo "| 字段 | 值 |"
        echo "|------|-----|"
        echo "| 开始时间 | $start_time |"
        echo "| 结束时间 | $end_time |"
        echo "| 耗时 | ${duration}s (${duration_min}min) |"
        echo "| CC 退出码 | $cc_exit |"
        echo "| 输出行数 | $output_lines |"
        echo "| 截断标记 | $output_truncated |"
        echo "| 前网络 | $net_before |"
        echo "| 后网络 | $net_after |"
        echo ""
        if [ $cc_exit -ne 0 ] || [ "$output_truncated" = "maybe-truncated" ]; then
            echo "### ⚠️ 异常详情"
            echo '```'
            echo "exit=$cc_exit, lines=$output_lines, truncated=$output_truncated"
            echo '```'
            echo ""
        fi
        echo "---"
    } >> "$log_file"
    
    # ── 输出到 stderr 的监控摘要 ──
    if [ $cc_exit -ne 0 ] || [ "$output_truncated" = "maybe-truncated" ]; then
        echo "[CC-MONITOR] ⚠️ $task_label → exit=$cc_exit duration=${duration}s lines=$output_lines truncated=$output_truncated" >&2
    else
        echo "[CC-MONITOR] ✅ $task_label → exit=$cc_exit duration=${duration}s" >&2
    fi
    
    # ── 透传 CC 输出到 stdout ──
    echo "$cc_output"
    return $cc_exit
}

# ── 作为独立脚本执行 ──
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    TASK="${1:-$(cat)}"
    LABEL="${2:-standalone}"
    if [ -z "$TASK" ]; then
        echo "Usage: echo 'task' | $0 [label]" >&2
        exit 1
    fi
    run_cc_monitored "$TASK" "$LABEL"
fi
