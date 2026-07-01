# coding=gbk
"""
QMT ÿ�ս������ݵ����ű�
ÿ�����̺󵼳����ɽ���ϸ���ֲ���ϸ���ʽ�ſ�
����� D:\\qmt_pool\\ Ŀ¼��GBK ���� CSV
���������� 2026-06-30 ̽��ʵ�⣨D:/qmt_pool/probe_output.txt��
"""

import os
from datetime import datetime

ACCOUNT_ID = '67014907'
OUTPUT_DIR = r'D:\qmt_pool'


def get_date_str():
    return datetime.now().strftime('%Y%m%d')


def safe_attr(obj, attr, default=''):
    """��ȫ��ȡ�������ԣ������ڻ��쳣���ؿ��ַ���"""
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
    """����ʽ����2λС������ֵ���ؿ��ַ���"""
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return '%.2f' % float(val)
    except Exception:
        return ''


def fmt_int(obj, attr):
    """������ʽ������������ֵ���ؿ��ַ���"""
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return str(int(val))
    except Exception:
        return ''


def fmt_pct(obj, attr, multiply=True):
    """�ٷֱȸ�ʽ����ӯ������ʵ����С������100����2λС��"""
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
    """�������ճɽ���ϸ"""
    deals = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'deal')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '�ɽ���ϸ_%s.csv' % date_str)
    header = '�ʽ��˺�,�ɽ�����,�ɽ�ʱ��,������,֤ȯ����,֤ȯ����,�������,�ɽ�����,�ɽ��۸�,�ɽ����,������,�ɽ����,��ͬ���,�������,������,Ͷ�ʱ�ע,�˺ű�ע,��֧����,Ͷ�ʱ�ע1,�ɶ���'
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
                '',  # Ͷ�ʱ�ע ������
                safe_attr(deal, 'm_strAccountRemark'),
                '',  # ��֧���� ������
                '',  # Ͷ�ʱ�ע1 ������
                '',  # �ɶ��� deal ��
            ])
            f.write(row + '\n')
    print('[����] �ɽ���ϸ %d �� -> %s' % (len(deals), filepath))
    return filepath


def export_positions(ContextInfo):
    """�����ֲ���ϸ"""
    positions = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'position')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '�ֲ���ϸ_%s.csv' % date_str)
    header = '�ʽ��˺�,������,֤ȯ����,֤ȯ����,��ǰӵ��,��������,��������,�ɱ���,���¼�,�ֲ�ӯ��,����ӯ��,ӯ������,�����Ƿ�,��ֵ,�ֲֳɱ�,�ɶ��˺�,�г�����,�ʲ�ռ��,��ֵռ��,״̬,��֧����,����ͨ��,����ӯ��'
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
                '',  # �����Ƿ� ������
                fmt_amount(pos, 'm_dMarketValue'),
                fmt_amount(pos, 'm_dPositionCost'),
                safe_attr(pos, 'm_strStockHolder'),
                safe_attr(pos, 'm_strExchangeName'),
                '',  # �ʲ�ռ�� ������
                '',  # ��ֵռ�� ������
                '',  # ״̬ ������
                '',  # ��֧���� ������
                '',  # ����ͨ�� ������
                '',  # ����ӯ�� ������
            ])
            f.write(row + '\n')
    print('[����] �ֲ���ϸ %d �� -> %s' % (len(positions), filepath))
    return filepath


def export_account(ContextInfo):
    """�����ʽ�ſ�"""
    accounts = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'account')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '�ʽ�ſ�_%s.csv' % date_str)
    header = '�ʽ��˺�,�˺�����,�˺ű�ע,��¼״̬,����,���ʲ�,���ʲ�,�ܸ�ծ,����ֵ,���ý��,������,�ֲ�ӯ��,������,��ȡ���,��Ʊ����ֵ,��������ֵ,ծȯ����ֵ,�ع�����ֵ,��������,��֧����,�ʽ����,�����˺�ӯ��'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for acc in accounts:
            row = ','.join([
                safe_attr(acc, 'm_strAccountID'),
                '',  # �˺����� ������
                safe_attr(acc, 'm_strAccountRemark'),
                safe_attr(acc, 'm_strStatus'),
                '',  # ���� ������
                fmt_amount(acc, 'm_dAssetBalance'),
                '',  # ���ʲ� ������
                fmt_amount(acc, 'm_dTotalDebit'),
                fmt_amount(acc, 'm_dStockValue'),
                fmt_amount(acc, 'm_dAvailable'),
                fmt_amount(acc, 'm_dFrozenCash'),
                fmt_amount(acc, 'm_dPositionProfit'),
                fmt_amount(acc, 'm_dCommission'),
                fmt_amount(acc, 'm_dFetchBalance'),
                fmt_amount(acc, 'm_dStockValue'),
                fmt_amount(acc, 'm_dFundValue'),
                '',  # ծȯ����ֵ ������
                fmt_amount(acc, 'm_dRepurchaseValue'),
                '',  # �������� ������
                safe_attr(acc, 'm_strBrokerName'),
                fmt_amount(acc, 'm_dBalance'),
                '',  # �����˺�ӯ�� ������
            ])
            f.write(row + '\n')
    print('[����] �ʽ�ſ� %d �� -> %s' % (len(accounts), filepath))
    return filepath


def _is_export_time():
    """工作日 15:05 后才允许导出。"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.strftime('%H%M')
    if hm < '1505':
        return False
    return True


def export_daily_data(ContextInfo):
    """主入口：导出所有数据。带时间锁。"""
    if not _is_export_time():
        print('[导出] 非工作日15:05后，跳过 (now=%s)' % datetime.now().strftime('%Y-%m-%d %H:%M'))
        return []
    files = []
    try:
        files.append(export_deals(ContextInfo))
    except Exception as e:
        print('[����] �ɽ���ϸʧ��: %s' % e)
    try:
        files.append(export_positions(ContextInfo))
    except Exception as e:
        print('[����] �ֲ���ϸʧ��: %s' % e)
    try:
        files.append(export_account(ContextInfo))
    except Exception as e:
        print('[����] �ʽ�ſ�ʧ��: %s' % e)
    return files


def init(ContextInfo):
    export_daily_data(ContextInfo)


def handlebar(ContextInfo):
    pass
