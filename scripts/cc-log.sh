#!/bin/bash
# 快速查看 CC 监控日志
#
# 用法:
#   ./scripts/cc-log.sh              # 今天的最新记录
#   ./scripts/cc-log.sh --today      # 今天所有记录
#   ./scripts/cc-log.sh --recent     # 最近5天的统计摘要
#   ./scripts/cc-log.sh --tail       # 实时跟踪（tail -f）

set -euo pipefail

MONITOR_LOG_DIR="/mnt/d/QMT_STRATEGIES/worklog/cc-monitor"

case "${1:-}" in
    --today|-t)
        cat "$MONITOR_LOG_DIR/$(date +%Y-%m-%d).md" 2>/dev/null \
            || echo "今天还没有 CC 调用记录"
        ;;
    --recent|-r)
        echo "━━━ 最近 CC 调用统计 ━━━"
        for f in $(ls -t "$MONITOR_LOG_DIR"/*.md 2>/dev/null | head -5); do
            date=$(basename "$f" .md)
            total=$(grep -c "^## " "$f" 2>/dev/null || echo 0)
            fails=$(grep -c "⚠️" "$f" 2>/dev/null || echo 0)
            echo "  $date  →  $total 次调用, $fails 次异常"
        done
        echo ""
        echo "查看详情: ./scripts/cc-log.sh --today"
        ;;
    --tail|-f)
        latest=$(ls -t "$MONITOR_LOG_DIR"/*.md 2>/dev/null | head -1)
        if [ -n "$latest" ]; then
            tail -f "$latest"
        else
            echo "暂无日志文件"
            exit 1
        fi
        ;;
    *)
        # 默认：今天的最后一条记录
        logfile="$MONITOR_LOG_DIR/$(date +%Y-%m-%d).md"
        if [ -f "$logfile" ]; then
            # 找最后一条 ## 记录
            last=$(grep -n "^## " "$logfile" | tail -1 | cut -d: -f1)
            if [ -n "$last" ]; then
                tail -n +"$last" "$logfile"
            else
                cat "$logfile"
            fi
        else
            echo "今天还没有 CC 调用记录"
            echo "使用 --recent 查看历史统计"
        fi
        ;;
esac
