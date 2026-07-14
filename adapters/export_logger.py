# coding=utf-8
import os
import time
from datetime import datetime

EXPORT_OUTPUT_DIR = r'D:\qmt_pool'

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


# ============================================================
#  每日数据导出（成交/持仓/资金 CSV）
# ============================================================

def _is_export_time(ContextInfo):
    """工作日 15:00 后才允许导出。周末/盘前返回 False。
    优先用 QMT 行情时间，取不到时 fallback 系统时间。"""
    now = None
    if ContextInfo is not None:
        try:
            now = ContextInfo.get_current_time()
        except Exception:
            try:
                tick_ms = ContextInfo.get_tick_timetag()
                if tick_ms is not None and tick_ms > 0:
                    now = datetime.fromtimestamp(tick_ms / 1000)
            except Exception:
                pass
    if now is None:
        now = datetime.now()
        print('[导出] 行情时间取不到，fallback系统时间')
    if now.weekday() >= 5:
        return False
    hm = now.strftime('%H%M')
    if hm < '1500':
        return False
    return True


def _export_safe_attr(obj, attr, default=''):
    if attr is None or attr == '':
        return default
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return default
        return str(val)
    except Exception:
        return default


def _export_fmt_amount(obj, attr):
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return '%.2f' % float(val)
    except Exception:
        return ''


def _export_fmt_int(obj, attr):
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return str(int(val))
    except Exception:
        return ''


def _export_fmt_pct(obj, attr, multiply=True):
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        v = float(val)
        if multiply:
            v = v * 100.0
        return '%.2f' % v
    except Exception:
        return ''


def export_deals(ContextInfo):
    deals = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'deal')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(EXPORT_OUTPUT_DIR, '成交明细_%s.csv' % date_str)
    header = '资金账号,成交日期,成交时间,交易所,证券代码,证券名称,买卖标记,成交数量,成交价格,成交金额,手续费,成交编号,合同编号,订单编号,任务编号,投资备注,账号备注,分支机构,投资备注1,股东号'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for deal in deals:
            row = ','.join([
                _export_safe_attr(deal, 'm_strAccountID'),
                _export_safe_attr(deal, 'm_strTradeDate'),
                _export_safe_attr(deal, 'm_strTradeTime'),
                _export_safe_attr(deal, 'm_strExchangeID'),
                _export_safe_attr(deal, 'm_strInstrumentID'),
                _export_safe_attr(deal, 'm_strInstrumentName'),
                _export_safe_attr(deal, 'm_strOptName'),
                _export_fmt_int(deal, 'm_nVolume'),
                _export_fmt_amount(deal, 'm_dPrice'),
                _export_fmt_amount(deal, 'm_dTradeAmount'),
                _export_fmt_amount(deal, 'm_dCommission'),
                _export_safe_attr(deal, 'm_strTradeID'),
                _export_safe_attr(deal, 'm_strOrderSysID'),
                _export_safe_attr(deal, 'm_strOrderRef'),
                _export_safe_attr(deal, 'm_strCompactNo'),
                '',
                _export_safe_attr(deal, 'm_strAccountRemark'),
                '',
                '',
                '',
            ])
            f.write(row + '\n')
    print('[导出] 成交明细 %d 条 -> %s' % (len(deals), filepath))
    return filepath


def export_positions(ContextInfo):
    positions = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'position')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(EXPORT_OUTPUT_DIR, '持仓明细_%s.csv' % date_str)
    header = '资金账号,交易所,证券代码,证券名称,当前拥股,可用数量,冻结数量,成本价,最新价,持仓盈亏,浮动盈亏,盈亏比例,当日涨幅,市值,持仓成本,股东账号,市场名称,资产占比,市值占比,状态,分支机构,非流通股,当日盈亏'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for pos in positions:
            row = ','.join([
                _export_safe_attr(pos, 'm_strAccountID'),
                _export_safe_attr(pos, 'm_strExchangeID'),
                _export_safe_attr(pos, 'm_strInstrumentID'),
                _export_safe_attr(pos, 'm_strInstrumentName'),
                _export_fmt_int(pos, 'm_nVolume'),
                _export_fmt_int(pos, 'm_nCanUseVolume'),
                _export_fmt_int(pos, 'm_nFrozenVolume'),
                _export_fmt_amount(pos, 'm_dOpenPrice'),
                _export_fmt_amount(pos, 'm_dLastPrice'),
                _export_fmt_amount(pos, 'm_dPositionProfit'),
                _export_fmt_amount(pos, 'm_dFloatProfit'),
                _export_fmt_pct(pos, 'm_dProfitRate', multiply=True),
                '',
                _export_fmt_amount(pos, 'm_dMarketValue'),
                _export_fmt_amount(pos, 'm_dPositionCost'),
                _export_safe_attr(pos, 'm_strStockHolder'),
                _export_safe_attr(pos, 'm_strExchangeName'),
                '',
                '',
                '',
                '',
                '',
                '',
            ])
            f.write(row + '\n')
    print('[导出] 持仓明细 %d 条 -> %s' % (len(positions), filepath))
    return filepath


def export_account(ContextInfo):
    accounts = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'account')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(EXPORT_OUTPUT_DIR, '资金概况_%s.csv' % date_str)
    header = '资金账号,账号名称,账号备注,登录状态,操作,总资产,净资产,总负债,总市值,可用金额,冻结金额,持仓盈亏,手续费,可取金额,股票总市值,基金总市值,债券总市值,回购总市值,报撤单比,分支机构,资金余额,今日账号盈亏'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for acc in accounts:
            row = ','.join([
                _export_safe_attr(acc, 'm_strAccountID'),
                '',
                _export_safe_attr(acc, 'm_strAccountRemark'),
                _export_safe_attr(acc, 'm_strStatus'),
                '',
                _export_fmt_amount(acc, 'm_dAssetBalance'),
                '',
                _export_fmt_amount(acc, 'm_dTotalDebit'),
                _export_fmt_amount(acc, 'm_dStockValue'),
                _export_fmt_amount(acc, 'm_dAvailable'),
                _export_fmt_amount(acc, 'm_dFrozenCash'),
                _export_fmt_amount(acc, 'm_dPositionProfit'),
                _export_fmt_amount(acc, 'm_dCommission'),
                _export_fmt_amount(acc, 'm_dFetchBalance'),
                _export_fmt_amount(acc, 'm_dStockValue'),
                _export_fmt_amount(acc, 'm_dFundValue'),
                '',
                _export_fmt_amount(acc, 'm_dRepurchaseValue'),
                '',
                _export_safe_attr(acc, 'm_strBrokerName'),
                _export_fmt_amount(acc, 'm_dBalance'),
                '',
            ])
            f.write(row + '\n')
        print('[导出] 资金概况 %d 条 -> %s' % (len(accounts), filepath))
    return filepath


def export_timer_cb(ContextInfo):
    """run_time 定时器回调：工作日>=15:05 且当日未导出，则导出当日 CSV。
    不依赖 handlebar 行情帧，定时器每60秒主动检查。"""
    global _g_exported_today, _g_last_date
    try:
        now = datetime.now()
        today = now.strftime('%Y%m%d')
        if today != _g_last_date:
            _g_last_date = today
            _g_exported_today = False
        if now.weekday() >= 5:
            return
        if now.strftime('%H%M') < '1505':
            return
        if _g_exported_today:
            return
        print('  [导出] 定时器触发导出 (now=%s)' % now.strftime('%H:%M:%S'))
        files = export_daily_data(ContextInfo)
        if files:
            _g_exported_today = True
            print('  [导出] 定时器导出完成: %d 个文件' % len(files))
    except Exception as e:
        print('  [导出] 定时器回调异常: %s' % e)


def export_daily_data(ContextInfo):
    """主入口：导出所有数据。带时间锁，非工作日15:05后跳过。"""
    if not _is_export_time(ContextInfo):
        print('[导出] 非工作日15:05后，跳过 (now=%s)' % datetime.now().strftime('%Y-%m-%d %H:%M'))
        return []
    files = []
    try:
        files.append(export_deals(ContextInfo))
    except Exception as e:
        print('[导出] 成交明细失败: %s' % e)
    try:
        files.append(export_positions(ContextInfo))
    except Exception as e:
        print('[导出] 持仓明细失败: %s' % e)
    try:
        files.append(export_account(ContextInfo))
    except Exception as e:
        print('[导出] 资金概况失败: %s' % e)
    _ok = [f for f in files if f]
    if _ok:
        print('[导出] 完成 产出%d文件: %s' % (len(_ok), _ok))
    else:
        print('[导出] 完成 但无文件产出（检查各 export_* 是否异常）')
    return files
