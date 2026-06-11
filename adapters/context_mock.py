# coding=utf-8
"""
Mock ContextInfo — 让 QMT 策略代码在 Claude Code 终端直接运行
无需启动 QMT 客户端即可测试 handlebar 主流程
"""
import pandas as pd


class MockContextInfo(object):
    """
    模拟 QMT 的 ContextInfo 对象

    用法:
        C = MockContextInfo()
        C.set_klines(df)  # 注入模拟 K 线
        runner = StrategyRunner()
        runner.init(C)
        runner.handlebar(C)
    """

    def __init__(self, stockcode='000001', market='SZ', period='1d'):
        self.stockcode = stockcode
        self.market = market
        self.period = period
        self.barpos = 100  # mock: 当前K线位置
        self._param = {'n1': 5, 'n2': 20}
        self._klines = None

    def set_klines(self, df):
        """注入模拟 K 线数据"""
        self._klines = df.copy()

    def is_last_bar(self):
        """模拟：总是返回 True（测试时只跑最后一根）"""
        return True

    def get_bar_timetag(self, pos):
        """返回模拟时间戳"""
        return 20240530000000

    def get_current_time(self):
        """返回模拟当前时间"""
        import datetime
        return datetime.datetime(2024, 5, 30, 15, 0, 0)

    def get_market_data_ex(self, fields, stocks, **kwargs):
        """模拟 get_market_data_ex 返回 {stock_code: DataFrame} 格式"""
        if self._klines is None:
            raise ValueError('请先调用 set_klines() 注入数据')
        available_cols = [c for c in fields if c in self._klines.columns]
        if not available_cols:
            available_cols = list(self._klines.columns)
        df = self._klines[available_cols].copy()
        return {self.stock: df}

    @property
    def close(self):
        """返回最新收盘价"""
        if self._klines is not None and 'close' in self._klines.columns:
            return float(self._klines['close'].iloc[-1])
        return 10.0

    @property
    def stock(self):
        return '%s.%s' % (self.stockcode, self.market)


def WINNER(price):
    """Mock 获利盘比例"""
    return 92.0


def SCR(n):
    """Mock 筹码集中度"""
    return 10.0


def DYNAINFO(n):
    """Mock 动态数据"""
    if n == 10:
        return 3000000000.0
    elif n == 17:
        return 1.5
    return 0.0


def get_trade_detail_data(accountid, datatype, datakind):
    """Mock 持仓/账户数据"""

    class MockPos(object):
        m_strInstrumentID = '000001'
        m_strExchangeID = 'SZ'
        m_nVolume = 0
        m_dOpenPrice = 10.0

    class MockAccount(object):
        m_dAvailable = 1000000.0
        m_dBalance = 1000000.0

    if datakind == 'position':
        return [MockPos()]
    elif datakind == 'account':
        return [MockAccount()]
    return []


def passorder(*args):
    """Mock 下单，只打印不执行"""
    safe_args = tuple('<ContextInfo>' if ('Context' in type(a).__name__) else a for a in args)
    print('[MOCK下单] 参数: %s' % (safe_args,))
    return True


def timetag_to_datetime(timetag, fmt):
    """Mock 时间转换"""
    return '20240530'


def draw_text(*args, **kwargs):
    """Mock 画图"""
    pass
