# coding=gbk
"""
QMT 每日数据导出脚本。独立于主策略运行，每日盘后导出成交明细、持仓明细、资金概况。
输出到 D:\qmt_pool\ 目录，GBK 编码 CSV。
默认 15:00 后导出（_is_export_time 时间锁）。
作为 QMT 策略独立运行，K线周期设1分钟，init 触发导出，handlebar 仅转发。
"""

import os
from datetime import datetime

ACCOUNT_ID = '67014907'
OUTPUT_DIR = r'D:\qmt_pool'

def get_date_str():
    return datetime.now().strftime('%Y%m%d')



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


def export_deals(ContextInfo):
    deals = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'deal')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(OUTPUT_DIR, '成交明细_%s.csv' % date_str)
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
    print('[\u5bfc\u51fa] \u6210\u4ea4\u660e\u7ec6 %d \u6761 -> %s' % (len(deals), filepath))
    return filepath


def export_positions(ContextInfo):
    positions = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'position')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(OUTPUT_DIR, '持仓明细_%s.csv' % date_str)
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
    print('[\u5bfc\u51fa] \u6301\u4ed3\u660e\u7ec6 %d \u6761 -> %s' % (len(positions), filepath))
    return filepath


def export_account(ContextInfo):
    accounts = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'account')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(OUTPUT_DIR, '资金概况_%s.csv' % date_str)
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
        print('[\u5bfc\u51fa] \u8d44\u91d1\u6982\u51b5 %d \u6761 -> %s' % (len(accounts), filepath))
    return filepath


def export_daily_data(ContextInfo):
    """主入口：导出所有数据。带时间锁，非工作日15:00后跳过。"""
    if not _is_export_time(ContextInfo):
        print('[\u5bfc\u51fa] \u975e\u5de5\u4f5c\u65e515:00\u540e\uff0c\u8df3\u8fc7 (now=%s)' % datetime.now().strftime('%Y-%m-%d %H:%M'))
        return []
    files = []
    try:
        files.append(export_deals(ContextInfo))
    except Exception as e:
        print('[\u5bfc\u51fa] \u6210\u4ea4\u660e\u7ec6\u5931\u8d25: %s' % e)
    try:
        files.append(export_positions(ContextInfo))
    except Exception as e:
        print('[\u5bfc\u51fa] \u6301\u4ed3\u660e\u7ec6\u5931\u8d25: %s' % e)
    try:
        files.append(export_account(ContextInfo))
    except Exception as e:
        print('[\u5bfc\u51fa] \u8d44\u91d1\u6982\u51b5\u5931\u8d25: %s' % e)
    _ok = [f for f in files if f]
    if _ok:
        print('[\u5bfc\u51fa] \u5b8c\u6210 \u4ea7\u51fa%d\u6587\u4ef6: %s' % (len(_ok), _ok))
    else:
        print('[\u5bfc\u51fa] \u5b8c\u6210 \u4f46\u65e0\u6587\u4ef6\u4ea7\u51fa\uff08\u68c0\u67e5\u5404 export_* \u662f\u5426\u5f02\u5e38\uff09')
    return files


def init(ContextInfo):
    export_daily_data(ContextInfo)


def handlebar(ContextInfo):
    pass

