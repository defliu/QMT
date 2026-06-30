# coding=gbk
"""
QMT 每日交易数据导出脚本
每天收盘后导出：成交明细、持仓明细、资金概况
输出到 D:\\qmt_pool\\ 目录，GBK 编码 CSV
属性名基于 2026-06-30 探针实测（D:/qmt_pool/probe_output.txt）
"""

import os
from datetime import datetime

ACCOUNT_ID = '67014907'
OUTPUT_DIR = r'D:\qmt_pool'


def get_date_str():
    return datetime.now().strftime('%Y%m%d')


def safe_attr(obj, attr, default=''):
    """安全获取对象属性，不存在或异常返回空字符串"""
    if attr is None or attr == '':
        return default
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return default
        return str(val)
    except Exception:
        return default


def fmt_amount(obj, attr):
    """金额格式化：2位小数，空值返回空字符串"""
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return '%.2f' % float(val)
    except Exception:
        return ''


def fmt_int(obj, attr):
    """数量格式化：整数，空值返回空字符串"""
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return str(int(val))
    except Exception:
        return ''


def fmt_pct(obj, attr, multiply=True):
    """百分比格式化：盈亏比例实测是小数，乘100后保留2位小数"""
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
    """导出当日成交明细"""
    deals = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'deal')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '成交明细_%s.csv' % date_str)
    header = '资金账号,成交日期,成交时间,交易所,证券代码,证券名称,买卖标记,成交数量,成交价格,成交金额,手续费,成交编号,合同编号,订单编号,任务编号,投资备注,账号备注,分支机构,投资备注1,股东号'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for deal in deals:
            row = ','.join([
                safe_attr(deal, 'm_strAccountID'),
                safe_attr(deal, 'm_strTradeDate'),
                safe_attr(deal, 'm_strTradeTime'),
                safe_attr(deal, 'm_strExchangeID'),
                safe_attr(deal, 'm_strInstrumentID'),
                safe_attr(deal, 'm_strInstrumentName'),
                safe_attr(deal, 'm_strOptName'),
                fmt_int(deal, 'm_nVolume'),
                fmt_amount(deal, 'm_dPrice'),
                fmt_amount(deal, 'm_dTradeAmount'),
                fmt_amount(deal, 'm_dCommission'),
                safe_attr(deal, 'm_strTradeID'),
                safe_attr(deal, 'm_strOrderSysID'),
                safe_attr(deal, 'm_strOrderRef'),
                safe_attr(deal, 'm_strCompactNo'),
                '',  # 投资备注 不存在
                safe_attr(deal, 'm_strAccountRemark'),
                '',  # 分支机构 不存在
                '',  # 投资备注1 不存在
                '',  # 股东号 deal 无
            ])
            f.write(row + '\n')
    print('[导出] 成交明细 %d 条 -> %s' % (len(deals), filepath))
    return filepath


def export_positions(ContextInfo):
    """导出持仓明细"""
    positions = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'position')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '持仓明细_%s.csv' % date_str)
    header = '资金账号,交易所,证券代码,证券名称,当前拥股,可用数量,冻结数量,成本价,最新价,持仓盈亏,浮动盈亏,盈亏比例,当日涨幅,市值,持仓成本,股东账号,市场名称,资产占比,市值占比,状态,分支机构,非流通股,当日盈亏'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for pos in positions:
            row = ','.join([
                safe_attr(pos, 'm_strAccountID'),
                safe_attr(pos, 'm_strExchangeID'),
                safe_attr(pos, 'm_strInstrumentID'),
                safe_attr(pos, 'm_strInstrumentName'),
                fmt_int(pos, 'm_nVolume'),
                fmt_int(pos, 'm_nCanUseVolume'),
                fmt_int(pos, 'm_nFrozenVolume'),
                fmt_amount(pos, 'm_dOpenPrice'),
                fmt_amount(pos, 'm_dLastPrice'),
                fmt_amount(pos, 'm_dPositionProfit'),
                fmt_amount(pos, 'm_dFloatProfit'),
                fmt_pct(pos, 'm_dProfitRate', multiply=True),
                '',  # 当日涨幅 不存在
                fmt_amount(pos, 'm_dMarketValue'),
                fmt_amount(pos, 'm_dPositionCost'),
                safe_attr(pos, 'm_strStockHolder'),
                safe_attr(pos, 'm_strExchangeName'),
                '',  # 资产占比 不存在
                '',  # 市值占比 不存在
                '',  # 状态 不存在
                '',  # 分支机构 不存在
                '',  # 非流通股 不存在
                '',  # 当日盈亏 不存在
            ])
            f.write(row + '\n')
    print('[导出] 持仓明细 %d 条 -> %s' % (len(positions), filepath))
    return filepath


def export_account(ContextInfo):
    """导出资金概况"""
    accounts = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'account')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '资金概况_%s.csv' % date_str)
    header = '资金账号,账号名称,账号备注,登录状态,操作,总资产,净资产,总负债,总市值,可用金额,冻结金额,持仓盈亏,手续费,可取金额,股票总市值,基金总市值,债券总市值,回购总市值,报撤单比,分支机构,资金余额,今日账号盈亏'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for acc in accounts:
            row = ','.join([
                safe_attr(acc, 'm_strAccountID'),
                '',  # 账号名称 不存在
                safe_attr(acc, 'm_strAccountRemark'),
                safe_attr(acc, 'm_strStatus'),
                '',  # 操作 不存在
                fmt_amount(acc, 'm_dAssetBalance'),
                '',  # 净资产 不存在
                fmt_amount(acc, 'm_dTotalDebit'),
                fmt_amount(acc, 'm_dStockValue'),
                fmt_amount(acc, 'm_dAvailable'),
                fmt_amount(acc, 'm_dFrozenCash'),
                fmt_amount(acc, 'm_dPositionProfit'),
                fmt_amount(acc, 'm_dCommission'),
                fmt_amount(acc, 'm_dFetchBalance'),
                fmt_amount(acc, 'm_dStockValue'),
                fmt_amount(acc, 'm_dFundValue'),
                '',  # 债券总市值 不存在
                fmt_amount(acc, 'm_dRepurchaseValue'),
                '',  # 报撤单比 不存在
                safe_attr(acc, 'm_strBrokerName'),
                fmt_amount(acc, 'm_dBalance'),
                '',  # 今日账号盈亏 不存在
            ])
            f.write(row + '\n')
    print('[导出] 资金概况 %d 条 -> %s' % (len(accounts), filepath))
    return filepath


def export_daily_data(ContextInfo):
    """主入口：导出所有数据"""
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
    return files


def init(ContextInfo):
    export_daily_data(ContextInfo)


def handlebar(ContextInfo):
    pass
