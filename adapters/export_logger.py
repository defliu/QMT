# coding=utf-8
import os
import time
from datetime import datetime

# ===== 日志缓冲 =====

def _append_log(timestamp=None, message=''):
    global _g_log_entries
    # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
    ts = timestamp or datetime.now().strftime('%H:%M:%S')
    _g_log_entries.append((ts, message))


def _reset_log_buffers():
    global _g_log_entries, _g_trade_records, _g_log_written_today
    _g_log_entries = []
    _g_trade_records = []
    _g_log_written_today = False


# ============================================================
#  SAFEMODE 安全壳
# ============================================================

def _safemode_log_trade_blocked(stock_code, direction, volume, price, remark, source_function):
    """记录被拦截的交易到 CSV 日志。"""
    if not SAFEMODE_ENABLED:
        return
    os.makedirs(SAFEMODE_LOG_DIR, exist_ok=True)
    # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
    today = datetime.now().strftime('%Y%m%d')
    log_path = os.path.join(SAFEMODE_LOG_DIR, 'trades_blocked_%s.csv' % today)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    import csv
    file_exists = os.path.exists(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['timestamp', 'stock_code', 'direction', 'volume', 'price', 'remark', 'source_function'])
        writer.writerow([timestamp, stock_code, direction, volume, price, remark, source_function])


def _safemode_log_signal(stock_code, score_8d, buy_points, sector_heat, details=None):
    """记录信号日志到 CSV。"""
    if not SAFEMODE_ENABLED:
        return
    os.makedirs(SAFEMODE_LOG_DIR, exist_ok=True)
    # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
    today = datetime.now().strftime('%Y%m%d')
    log_path = os.path.join(SAFEMODE_LOG_DIR, 'signals_%s.csv' % today)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    import csv
    file_exists = os.path.exists(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['timestamp', 'stock_code', 'score_8d', 'buy_points', 'sector_heat'])
        writer.writerow([timestamp, stock_code, score_8d, buy_points, sector_heat])


def _log_holdings_reconcile(C, tag):
    try:
        acct_codes = set(_g_trader.get_holdings().keys()) if _g_trader else set()
        my_codes = set(_g_my_codes.keys())
        only_acct = acct_codes - my_codes
        only_my = my_codes - acct_codes
        print("  [对账] %s _g_my_codes(%d只) vs account(%d只)" % (tag, len(my_codes), len(acct_codes)))
        if only_acct or only_my:
            print("  [对账告警] %s 仅账户=%s 仅策略=%s" % (tag, sorted(only_acct), sorted(only_my)))
    except Exception as e:
        print("  [对账] %s 失败: %s" % (tag, e))

