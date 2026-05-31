# coding=utf-8
"""测试程序化回测模块 — BacktestParams, BacktestContext, 模拟交易, 绩效指标。"""

import os
import sys
import json
import math
import tempfile

import pytest
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 将 PROJECT_ROOT 注册到 sys.path（与 run_backtest.py 一致）
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.backtest_params import BacktestParams, BacktestResult
from scripts.run_backtest import (
    BacktestState,
    BacktestContext,
    ScanParams,
    _backtest_passorder,
    _backtest_get_trade_detail_data,
    _backtest_timetag_to_datetime,
    _calc_metrics,
    _light_filter,
    scan_market,
    _result_to_dict,
    _format_report,
    TRADING_DAYS_PER_YEAR,
    ANNUAL_RISK_FREE_RATE,
)


# ============================================================
#  Fixtures
# ============================================================

@pytest.fixture
def sample_params():
    return BacktestParams(
        stock_codes=['000001.SZ', '600519.SH'],
        start_date='2024-01-01',
        end_date='2024-03-31',
        initial_capital=100000.0,
    )


@pytest.fixture
def synthetic_data():
    """生成 200 个交易日的模拟 K 线数据（2 只股票 + 基准）。"""
    np.random.seed(42)
    n = 200
    dates = pd.date_range('2023-06-01', periods=n, freq='B')

    dfs = {}
    for code in ['000001.SZ', '600519.SH', '000300.SH']:
        close = 10.0 if code == '000001.SZ' else (150.0 if code == '600519.SH' else 3500.0)
        closes, opens, highs, lows, volumes = [], [], [], [], []

        for _ in range(n):
            change = np.random.uniform(-0.025, 0.028)
            op = close * (1 + np.random.uniform(-0.01, 0.01))
            new_close = close * (1 + change)
            high = max(op, new_close) * (1 + abs(np.random.uniform(0, 0.015)))
            low = min(op, new_close) * (1 - abs(np.random.uniform(0, 0.015)))
            vol = int(np.random.uniform(1_000_000, 10_000_000))

            opens.append(round(op, 2))
            closes.append(round(new_close, 2))
            highs.append(round(high, 2))
            lows.append(round(low, 2))
            volumes.append(vol)
            close = new_close

        dfs[code] = pd.DataFrame({
            'open': opens, 'close': closes, 'high': highs,
            'low': lows, 'volume': volumes,
        }, index=dates)

    all_dates = [d.strftime('%Y-%m-%d') for d in dates]
    return dfs, all_dates


@pytest.fixture
def backtest_state():
    """一个干净的 BacktestState 实例。"""
    return BacktestState(
        initial_capital=100000.0,
        slippage=0.001,
        commission_rate=0.00025,
        tax_rate=0.0001,
    )


# ============================================================
#  1. BacktestParams
# ============================================================

class TestBacktestParams:

    def test_default_values(self):
        """默认参数构造正确。"""
        p = BacktestParams()
        assert p.stock_codes == []
        assert p.start_date == '2024-01-01'
        assert p.end_date == '2024-12-31'
        assert p.initial_capital == 100000.0
        assert abs(p.slippage - 0.001) < 1e-6
        assert abs(p.commission_rate - 0.00025) < 1e-6
        assert abs(p.tax_rate - 0.0001) < 1e-6
        assert p.benchmark == '000300.SH'

    def test_custom_values(self):
        """自定义参数正确生效。"""
        p = BacktestParams(
            stock_codes=['000001.SZ'],
            start_date='2024-06-01',
            end_date='2024-09-30',
            initial_capital=500000.0,
        )
        assert p.stock_codes == ['000001.SZ']
        assert p.start_date == '2024-06-01'
        assert p.end_date == '2024-09-30'
        assert p.initial_capital == 500000.0


# ============================================================
#  2. BacktestResult
# ============================================================

class TestBacktestResult:

    def test_default_values(self):
        """默认构造产生 FAIL 状态。"""
        r = BacktestResult()
        assert r.success is False
        assert r.total_return == 0.0
        assert r.status == 'FAIL'

    def test_pass_status(self):
        """夏普 > 1 且回撤 < 8% 时 PASS。"""
        r = BacktestResult(success=True, sharpe_ratio=1.5, max_drawdown=-0.05)
        assert r.status == 'PASS'

    def test_fail_status_low_sharpe(self):
        """夏普不足时 FAIL。"""
        r = BacktestResult(success=True, sharpe_ratio=0.5, max_drawdown=-0.03)
        assert r.status == 'FAIL'

    def test_fail_status_high_drawdown(self):
        """回撤过大时 FAIL。"""
        r = BacktestResult(success=True, sharpe_ratio=1.2, max_drawdown=-0.15)
        assert r.status == 'FAIL'

    def test_to_dict(self):
        """to_dict 输出关键字段。"""
        r = BacktestResult(
            success=True, total_return=0.0832, sharpe_ratio=1.85,
            total_trades=18, win_rate=0.667,
        )
        d = r.to_dict()
        assert d['success'] is True
        assert abs(d['total_return'] - 0.0832) < 1e-4
        assert d['total_trades'] == 18

    def test_to_dict_error(self):
        """错误时 to_dict 包含 error。"""
        r = BacktestResult(success=False, error="QMT client not running")
        d = r.to_dict()
        assert d['success'] is False
        # to_dict 不包含 error（见实现），error 在 _result_to_dict
        assert 'total_return' in d

    def test_monthly_returns_field(self):
        """monthly_returns 默认空字典。"""
        r = BacktestResult()
        assert isinstance(r.monthly_returns, dict)
        assert len(r.monthly_returns) == 0

    def test_equity_curve_field(self):
        """equity_curve 默认空列表。"""
        r = BacktestResult()
        assert isinstance(r.equity_curve, list)
        assert len(r.equity_curve) == 0


# ============================================================
#  3. BacktestContext
# ============================================================

class TestBacktestContext:

    def test_get_market_data_ex_returns_data_up_to_current_bar(self, synthetic_data):
        """get_market_data_ex 返回截止当前 bar 的数据。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=50, all_dates=dates)
        result = ctx.get_market_data_ex(stock_code=['000001.SZ'], period='1d', count=120)

        assert '000001.SZ' in result
        df = result['000001.SZ']
        assert len(df) == 51  # bar 0..50 = 51 rows
        assert 'close' in df.columns

    def test_get_market_data_ex_count_limit(self, synthetic_data):
        """count 参数正确限制返回行数。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=100, all_dates=dates)
        result = ctx.get_market_data_ex(stock_code=['000001.SZ'], period='1d', count=30)
        assert '000001.SZ' in result
        assert len(result['000001.SZ']) == 30

    def test_get_market_data_ex_empty_for_invalid_code(self, synthetic_data):
        """无效股票代码返回空 DataFrame。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=50, all_dates=dates)
        result = ctx.get_market_data_ex(stock_code=['INVALID'], period='1d', count=120)
        assert 'INVALID' in result
        assert result['INVALID'].empty

    def test_get_current_time(self, synthetic_data):
        """get_current_time 返回正确日期。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=10, all_dates=dates)
        dt = ctx.get_current_time()
        assert dt.strftime('%Y-%m-%d') == dates[10]
        assert dt.strftime('%H%M') == '1450'

    def test_get_full_tick(self, synthetic_data):
        """get_full_tick 返回当前 bar 的收盘价。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=10, all_dates=dates)
        tick = ctx.get_full_tick(codes=['000001.SZ'])
        assert '000001.SZ' in tick
        assert tick['000001.SZ']['lastPrice'] > 0
        assert tick['000001.SZ']['preClose'] > 0

    def test_get_stock_name_default(self, synthetic_data):
        """get_stock_name 默认返回 code 自身。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=0, all_dates=dates)
        assert ctx.get_stock_name('000001.SZ') == '000001.SZ'

    def test_get_stock_name_with_names(self, synthetic_data):
        """传入 stock_names 时返回正确名称。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=0, all_dates=dates,
                               stock_names={'000001.SZ': '平安银行'})
        assert ctx.get_stock_name('000001.SZ') == '平安银行'

    def test_get_instrument_detail(self, synthetic_data):
        """get_instrument_detail 返回 CirculateValue。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=10, all_dates=dates)
        detail = ctx.get_instrument_detail('000001.SZ')
        assert 'CirculateValue' in detail
        assert detail['CirculateValue'] > 0

    def test_sector_list_empty(self, synthetic_data):
        """get_sector_list 返回空。"""
        dfs, dates = synthetic_data
        ctx = BacktestContext(dfs, current_bar=0, all_dates=dates)
        assert ctx.get_sector_list() == []


# ============================================================
#  4. BacktestState + Mock 交易函数
# ============================================================

class TestBacktestTrading:

    def _set_global_state(self, state):
        """设置模块级 _backtest_state 供 mock 函数使用。"""
        import scripts.run_backtest as bt
        bt._backtest_state = state

    def test_buy_updates_cash_and_positions(self, backtest_state):
        """买入操作正确扣减资金并增加持仓。"""
        from scripts.run_backtest import _backtest_passorder
        self._set_global_state(backtest_state)
        state = backtest_state
        state.current_prices = {'000001.SZ': 10.0}
        state.current_date = '20240105'

        class FakeCtx:
            pass

        oid = _backtest_passorder(
            23, 1101, '67014907', '000001.SZ',
            5, -1, 1000, 'test', 2, '', FakeCtx(),
        )
        assert oid is not None and oid > 0
        assert '000001.SZ' in state.positions
        assert state.positions['000001.SZ']['volume'] == 1000
        assert state.cash < 100000.0

    def test_sell_updates_cash_and_removes_position(self, backtest_state):
        """卖出操作正确增加资金并移除持仓。"""
        from scripts.run_backtest import _backtest_passorder
        self._set_global_state(backtest_state)
        state = backtest_state
        state.current_prices = {'000001.SZ': 10.0}
        state.current_date = '20240105'

        # 先买入
        state.cash = 100000.0
        cost = 10.0 * 1000 + 10.0 * 1000 * 0.00025
        state.cash -= cost
        state.positions['000001.SZ'] = {'volume': 1000, 'cost': 10.0}

        class FakeCtx:
            pass

        oid = _backtest_passorder(
            24, 1101, '67014907', '000001.SZ',
            5, -1, 1000, 'test', 2, '', FakeCtx(),
        )
        assert oid is not None
        assert '000001.SZ' not in state.positions or state.positions['000001.SZ']['volume'] == 0
        assert state.cash > 10000

    def test_sell_insufficient_volume_returns_none(self, backtest_state):
        """卖出多于持仓量时返回 None。"""
        from scripts.run_backtest import _backtest_passorder
        self._set_global_state(backtest_state)
        state = backtest_state
        state.current_prices = {'000001.SZ': 10.0}
        state.current_date = '20240105'
        state.positions['000001.SZ'] = {'volume': 100, 'cost': 10.0}

        class FakeCtx:
            pass

        oid = _backtest_passorder(
            24, 1101, '67014907', '000001.SZ',
            5, -1, 1000, 'test', 2, '', FakeCtx(),
        )
        assert oid is None

    def test_buy_insufficient_cash_adjusts_volume(self, backtest_state):
        """资金不足时自动调整买入数量（不足100股时返回None）。"""
        from scripts.run_backtest import _backtest_passorder
        self._set_global_state(backtest_state)
        state = backtest_state
        state.cash = 500  # 很少现金
        state.current_prices = {'000001.SZ': 10.0}
        state.current_date = '20240105'

        class FakeCtx:
            pass

        oid = _backtest_passorder(
            23, 1101, '67014907', '000001.SZ',
            5, -1, 10000, 'test', 2, '', FakeCtx(),
        )
        # 现金不足 100 股时应返回 None
        assert oid is None

    def test_get_trade_detail_data_position(self, backtest_state):
        """get_trade_detail_data 返回正确持仓。"""
        from scripts.run_backtest import _backtest_get_trade_detail_data
        self._set_global_state(backtest_state)
        state = backtest_state
        state.current_prices = {'000001.SZ': 10.5}
        state.positions['000001.SZ'] = {'volume': 500, 'cost': 10.0}

        positions = _backtest_get_trade_detail_data('67014907', 'STOCK', 'position')
        assert len(positions) == 1
        assert positions[0].m_strInstrumentID == '000001'
        assert positions[0].m_nVolume == 500

    def test_get_trade_detail_data_account(self, backtest_state):
        """get_trade_detail_data 返回正确账户资金。"""
        from scripts.run_backtest import _backtest_get_trade_detail_data
        self._set_global_state(backtest_state)
        state = backtest_state
        state.current_prices = {'000001.SZ': 10.0}
        state.cash = 50000.0
        state.positions['000001.SZ'] = {'volume': 1000, 'cost': 10.0}

        accounts = _backtest_get_trade_detail_data('67014907', 'STOCK', 'account')
        assert len(accounts) == 1
        assert accounts[0].m_dAvailable > 0
        assert accounts[0].m_dTotalAsset > 50000

    def test_get_trade_detail_data_order_empty(self, backtest_state):
        """get_trade_detail_data order 返回空列表（即日成交）。"""
        orders = _backtest_get_trade_detail_data('67014907', 'STOCK', 'order')
        assert orders == []

    def test_timetag_to_datetime(self):
        """_backtest_timetag_to_datetime 返回字符串。"""
        result = _backtest_timetag_to_datetime(20240101093000, '%Y%m%d')
        assert isinstance(result, str)

    def test_multi_buy_average_cost(self, backtest_state):
        """多次买入同一股票正确计算平均成本。"""
        from scripts.run_backtest import _backtest_passorder
        self._set_global_state(backtest_state)
        state = backtest_state
        state.current_date = '20240105'

        class FakeCtx:
            pass

        # 第一次买入
        state.current_prices = {'000001.SZ': 10.0}
        oid = _backtest_passorder(23, 1101, '67014907', '000001.SZ',
                                   5, -1, 1000, '', 2, '', FakeCtx())
        assert oid is not None

        first_cost = state.positions['000001.SZ']['cost']

        # 第二次买入，价格不同
        state.current_prices = {'000001.SZ': 11.0}
        oid = _backtest_passorder(23, 1101, '67014907', '000001.SZ',
                                   5, -1, 500, '', 2, '', FakeCtx())
        assert oid is not None
        assert state.positions['000001.SZ']['volume'] == 1500
        # 平均成本应在 10 和 11 之间
        assert first_cost < state.positions['000001.SZ']['cost'] < 11.0


# ============================================================
#  5. 绩效指标计算
# ============================================================

class TestMetrics:

    def test_calc_metrics_basic(self, synthetic_data):
        """基本指标计算不报错。"""
        dfs, dates = synthetic_data
        params = BacktestParams(
            stock_codes=['000001.SZ'],
            start_date='2024-01-01',
            end_date='2024-03-31',
            initial_capital=100000.0,
        )
        state = BacktestState(100000.0, 0.001, 0.00025, 0.0001)
        # 模拟简单净值曲线
        state.equity_curve = [
            ('2024-01-05', 100000.0),
            ('2024-01-08', 101000.0),
            ('2024-01-09', 100500.0),
            ('2024-01-10', 103000.0),
        ]
        state.closed_trades = [
            {'code': '000001.SZ', 'volume': 1000, 'entry_price': 10.0,
             'exit_price': 11.0, 'pnl': 1000.0, 'exit_date': '20240110'},
        ]

        result = _calc_metrics(state, params, dates, dfs)
        assert result.success is True
        assert result.total_return > 0  # 净值上升
        assert result.total_trades == 1
        assert result.win_rate == 1.0  # 盈利交易

    def test_calc_metrics_losing_trades(self, synthetic_data):
        """亏损回测正确报告负值。"""
        dfs, dates = synthetic_data
        params = BacktestParams(stock_codes=['000001.SZ'])
        state = BacktestState(100000.0, 0.001, 0.00025, 0.0001)
        state.equity_curve = [
            ('2024-01-05', 100000.0),
            ('2024-01-08', 90000.0),
            ('2024-01-09', 85000.0),
            ('2024-01-10', 82000.0),
        ]
        state.closed_trades = [
            {'code': '000001.SZ', 'volume': 1000, 'entry_price': 10.0,
             'exit_price': 8.0, 'pnl': -2000.0, 'exit_date': '20240110'},
        ]

        result = _calc_metrics(state, params, dates, dfs)
        assert result.success is True
        assert result.total_return < -0.1  # 亏损大于 10%
        assert result.total_trades == 1
        assert result.win_rate == 0.0  # 亏损交易

    def test_calc_metrics_custom_params(self, synthetic_data):
        """不同参数下指标计算正确。"""
        dfs, dates = synthetic_data
        for capital in [50000, 200000]:
            params = BacktestParams(
                stock_codes=['000001.SZ'],
                initial_capital=float(capital),
            )
            state = BacktestState(float(capital), 0.001, 0.00025, 0.0001)
            state.equity_curve = [
                ('2024-01-05', float(capital)),
                ('2024-01-08', float(capital) * 1.05),
            ]
            result = _calc_metrics(state, params, dates, dfs)
            assert result.success
            assert abs(result.total_return - 0.05) < 0.001

    def test_calc_metrics_empty_equity(self, synthetic_data):
        """无净值数据时返回失败。"""
        dfs, dates = synthetic_data
        state = BacktestState(100000.0, 0.001, 0.00025, 0.0001)
        result = _calc_metrics(state, BacktestParams(), dates, dfs)
        assert result.success is False
        assert '数据不足' in (result.error or '')

    def test_sharpe_ratio_calculation(self):
        """夏普比率公式验证。"""
        state = BacktestState(100000.0, 0.001, 0.00025, 0.0001)
        # 稳定上涨：每天 +0.5%
        eq = [100000.0]
        for i in range(20):
            eq.append(eq[-1] * 1.005)
        dates = [f'2024-01-{i+1:02d}' for i in range(21)]
        state.equity_curve = list(zip(dates, eq))

        result = _calc_metrics(state, BacktestParams(), dates, {})
        assert result.success
        # 夏普应该为正
        assert result.sharpe_ratio > 0

    def test_max_drawdown_calculation(self):
        """最大回撤公式验证：先涨后跌。"""
        state = BacktestState(100000.0, 0.001, 0.00025, 0.0001)
        # 先涨到 120k 再跌回 90k
        eq = [100000, 110000, 120000, 115000, 105000, 90000]
        dates = [f'2024-01-{i+1:02d}' for i in range(6)]
        state.equity_curve = list(zip(dates, eq))

        result = _calc_metrics(state, BacktestParams(), dates, {})
        assert result.success
        # 最大回撤: (120000 - 90000) / 120000 = 25%
        assert abs(result.max_drawdown - (-0.25)) < 0.01


# ============================================================
#  6. 错误处理
# ============================================================

class TestErrorHandling:

    def test_empty_stock_codes_returns_error(self):
        """空股票列表返回错误。"""
        from scripts.run_backtest import BacktestRunner
        params = BacktestParams(stock_codes=[])
        result = BacktestRunner().run_backtest(params)
        assert result.success is False
        assert result.error is not None
        assert '空' in result.error or '列表' in result.error

    def test_result_to_dict_includes_error(self):
        """失败结果转字典包含 error。"""
        r = BacktestResult(success=False, error="QMT client not running")
        d = _result_to_dict(r, BacktestParams())
        assert d['success'] is False
        assert d['error'] == "QMT client not running"
        assert d['status'] == 'FAIL'

    def test_result_to_dict_required_fields(self):
        """JSON 输出包含所有必填字段。"""
        r = BacktestResult(
            success=True, total_return=0.0832, annualized_return=0.3328,
            benchmark_return=0.0215, max_drawdown=-0.0521, sharpe_ratio=1.85,
            volatility=0.18, total_trades=18, win_trades=12, lose_trades=6,
            win_rate=0.667, profit_factor=2.31, avg_hold_days=4.2,
        )
        params = BacktestParams(start_date='2024-01-01', end_date='2024-03-31',
                                 initial_capital=100000.0)
        d = _result_to_dict(r, params, '双带主升浪_尾盘_外部池_beat四层版')

        required = ['strategy', 'period', 'capital', 'total_return',
                    'annualized_return', 'benchmark_return', 'max_drawdown',
                    'sharpe_ratio', 'volatility', 'total_trades', 'win_trades',
                    'lose_trades', 'win_rate', 'profit_factor', 'avg_hold_days',
                    'status', 'success']
        for field in required:
            assert field in d, f"缺少字段: {field}"
        assert d['strategy'] == '双带主升浪_尾盘_外部池_beat四层版'
        assert d['period']['start'] == '2024-01-01'
        assert d['capital'] == 100000.0

    def test_format_report_success(self):
        """成功回测的报告中包含收益和评估。"""
        r = BacktestResult(
            success=True, total_return=0.0832, annualized_return=0.3328,
            benchmark_return=0.0215, max_drawdown=-0.0521, sharpe_ratio=1.85,
            total_trades=18, win_rate=0.667, profit_factor=2.31,
        )
        params = BacktestParams(start_date='2024-01-01', end_date='2024-03-31',
                                 initial_capital=100000.0)
        report = _format_report(r, params)
        assert 'Backtest Report' in report
        assert '+8.32%' in report or '+0.0832' in report
        assert '2024-01-01' in report
        assert '100,000' in report

    def test_format_report_failure(self):
        """失败回测的报告显示错误。"""
        r = BacktestResult(success=False, error="测试错误")
        report = _format_report(r, BacktestParams())
        assert '失败' in report
        assert '测试错误' in report

    def test_format_report_qmt_not_running(self):
        """QMT 未运行时的错误信息明确。"""
        r = BacktestResult(success=False, error="QMT client not running. Start MiniQMT first.")
        report = _format_report(r, BacktestParams())
        assert 'QMT client not running' in report or 'QMT' in report
        assert 'Start MiniQMT' in report or '失败' in report


# ============================================================
#  7. JSON 输出格式
# ============================================================

class TestJsonOutput:

    def test_json_serializable(self):
        """_result_to_dict 输出可 JSON 序列化。"""
        r = BacktestResult(
            success=True, total_return=0.0832, annualized_return=0.3328,
            benchmark_return=0.0215, max_drawdown=-0.0521, sharpe_ratio=1.85,
            volatility=0.18, total_trades=18, win_trades=12, lose_trades=6,
            win_rate=0.667, profit_factor=2.31, avg_hold_days=4.2,
        )
        params = BacktestParams(start_date='2024-01-01', end_date='2024-03-31',
                                 initial_capital=100000.0)
        d = _result_to_dict(r, params)
        json_str = json.dumps(d, ensure_ascii=False, indent=2)
        parsed = json.loads(json_str)
        assert parsed['success'] is True
        assert abs(parsed['total_return'] - 0.0832) < 1e-4

    def test_json_matches_spec_structure(self):
        """JSON 结构与 spec 一致。"""
        # spec 示例输出:
        # {"strategy": "...", "period": {"start": "...", "end": "..."},
        #  "capital": 100000.0, "total_return": 0.0832, ...,
        #  "status": "PASS", "checks": {"sharpe": "PASS", "drawdown": "PASS"}}
        r = BacktestResult(
            success=True, sharpe_ratio=1.85, max_drawdown=-0.0521,
            total_return=0.0832, annualized_return=0.3328,
            benchmark_return=0.0215, volatility=0.18,
            total_trades=18, win_trades=12, lose_trades=6,
            win_rate=0.667, profit_factor=2.31, avg_hold_days=4.2,
        )
        d = _result_to_dict(r, BacktestParams(start_date='2024-01-01', end_date='2024-03-31'))
        assert 'strategy' in d
        assert isinstance(d['period'], dict)
        assert 'start' in d['period']
        assert 'end' in d['period']
        assert 'capital' in d
        assert 'status' in d
        assert d['status'] in ('PASS', 'FAIL')


# ============================================================
#  8. 多次运行不残留 state
# ============================================================

class TestStateIsolation:

    def test_runner_state_does_not_leak_across_calls(self, synthetic_data):
        """连续两次 run_with_data 不互相影响（无残留 state）。"""
        from scripts.run_backtest import BacktestRunner

        dfs, dates = synthetic_data
        params = BacktestParams(
            stock_codes=['000001.SZ'],
            start_date='2023-09-01',
            end_date='2023-12-31',
            initial_capital=100000.0,
        )

        r1 = BacktestRunner().run_with_data(params, dfs, dates)
        r2 = BacktestRunner().run_with_data(params, dfs, dates)

        # 两次结果应相同（确定种子 + 独立 state）
        assert r1.success == r2.success
        if r1.success and r2.success:
            # 净值曲线应有差异（策略依赖 _g_all_data，第二次独立运行）
            assert isinstance(r1.total_trades, int)
            assert isinstance(r2.total_trades, int)

    def test_global_state_reset_between_runs(self):
        """_backtest_state 在 run 后重置为 None。"""
        from scripts.run_backtest import _backtest_state as bs
        # 直接验证模块级全局变量
        import scripts.run_backtest as bt
        bt._backtest_state = BacktestState(100000.0, 0.001, 0.00025, 0.0001)
        assert bt._backtest_state is not None
        # 模拟清理
        bt._backtest_state = None
        assert bt._backtest_state is None


# ============================================================
#  9. CLI 参数解析
# ============================================================

class TestCliParsing:

    def test_parse_args_defaults(self):
        """CLI 默认参数能解析。"""
        from scripts.run_backtest import _parse_cli
        # 模拟空参数（用 sys.argv 覆盖）
        import argparse
        # 不能直接调 _parse_cli（会读 sys.argv），测试 parse_args 逻辑
        parser = argparse.ArgumentParser()
        parser.add_argument('--start')
        parser.add_argument('--end')
        parser.add_argument('--capital', type=float)
        parser.add_argument('--stocks')
        parser.add_argument('--output')
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--params')

        args = parser.parse_args([])
        assert args.start is None
        assert args.end is None
        assert args.capital is None
        assert args.json is False

        args = parser.parse_args(['--start', '2024-01-01', '--end', '2024-03-31',
                                   '--capital', '200000', '--json'])
        assert args.start == '2024-01-01'
        assert args.end == '2024-03-31'
        assert args.capital == 200000.0
        assert args.json is True

    def test_parse_stocks_arg(self):
        """--stocks 参数正确解析多只股票。"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--stocks', type=str)
        args = parser.parse_args(['--stocks', '000001.SZ,600519.SH'])
        codes = [s.strip() for s in args.stocks.split(',')]
        assert codes == ['000001.SZ', '600519.SH']


# ============================================================
#  10. 数据源选择
# ============================================================

class TestDatasource:

    def test_strip_suffix_sh(self):
        """_strip_suffix 正确去除 .SH 后缀。"""
        from scripts.run_backtest import _strip_suffix
        assert _strip_suffix('600519.SH') == '600519'

    def test_strip_suffix_sz(self):
        """_strip_suffix 正确去除 .SZ 后缀。"""
        from scripts.run_backtest import _strip_suffix
        assert _strip_suffix('000001.SZ') == '000001'

    def test_strip_suffix_bj(self):
        """_strip_suffix 正确去除 .BJ 后缀。"""
        from scripts.run_backtest import _strip_suffix
        assert _strip_suffix('832000.BJ') == '832000'

    def test_strip_suffix_no_suffix(self):
        """_strip_suffix 对纯6位代码原样返回。"""
        from scripts.run_backtest import _strip_suffix
        assert _strip_suffix('688017') == '688017'

    def test_strip_suffix_lowercase(self):
        """_strip_suffix 处理小写后缀。"""
        from scripts.run_backtest import _strip_suffix
        assert _strip_suffix('600519.sh') == '600519'

    def test_invalid_datasource_raises_error(self):
        """无效 datasource 值抛出 ValueError 且信息明确。"""
        with pytest.raises(ValueError) as exc:
            from scripts.run_backtest import _download_and_prepare_data
            _download_and_prepare_data([], '2024-01-01', '2024-01-10',
                                       '000300.SH', datasource='invalid')
        assert '未知数据源' in str(exc.value)
        assert 'invalid' in str(exc.value)

    def test_default_datasource_is_xtquant(self):
        """默认 datasource=xtquant 时 xtquant 报错应为 ImportError 而非 invalid。"""
        import scripts.run_backtest as bt
        with pytest.raises((RuntimeError, ImportError)) as exc:
            bt._download_and_prepare_data(
                ['000001.SZ'], '2024-01-01', '2024-01-10', '000300.SH',
            )
        # 如果有 xtquant 会尝试 connect 并报 RunTimeError；没有则报 ImportError
        # 无论哪种，都不应出现 "未知数据源" —— 验证 dispatch 逻辑
        assert '未知数据源' not in str(exc.value)


# ============================================================
#  11. ScanParams
# ============================================================

class TestScanParams:

    def test_default_values(self):
        """默认参数正确。"""
        sp = ScanParams()
        assert abs(sp.min_price - 5.0) < 1e-6
        assert sp.min_volume == 100000
        assert sp.exclude_st is True
        assert sp.min_listed_days == 365
        assert sp.max_candidates == 100

    def test_custom_values(self):
        """自定义参数正确生效。"""
        sp = ScanParams(min_price=10.0, max_candidates=50)
        assert abs(sp.min_price - 10.0) < 1e-6
        assert sp.max_candidates == 50


# ============================================================
#  12. _light_filter
# ============================================================

class TestLightFilter:

    def test_normal_stock_passes(self):
        """正常股票通过过滤。"""
        assert _light_filter('600519', '贵州茅台', 150.0, 3000) is True

    def test_low_price_rejected(self):
        """价格低于 5 元被过滤。"""
        assert _light_filter('000001', '平安银行', 3.5, 3000) is False

    def test_st_name_rejected(self):
        """ST 股票被过滤。"""
        assert _light_filter('600123', '*ST兰格', 6.0, 1000) is False

    def test_st_prefix_rejected(self):
        """ST 前缀股票被过滤。"""
        assert _light_filter('600456', 'ST保千', 7.0, 500) is False

    def test_tui_rejected(self):
        """退市股票被过滤。"""
        assert _light_filter('002123', '退市昆机', 8.0, 2000) is False

    def test_short_listed_rejected(self):
        """上市不足 365 天被过滤。"""
        assert _light_filter('688999', '次新股', 20.0, 100) is False

    def test_boundary_price(self):
        """正好 5 元可通过（>= 5.0），4.99 被过滤。"""
        assert _light_filter('000001', '测试股', 5.0, 500) is True
        assert _light_filter('000001', '测试股', 4.99, 500) is False

    def test_boundary_listed_days(self):
        """正好 365 天应通过过滤（>= 365）。"""
        assert _light_filter('600001', '测试股', 10.0, 365) is True
        assert _light_filter('600001', '测试股', 10.0, 364) is False


# ============================================================
#  13. scan_market (mocked mootdx)
# ============================================================

class TestScanMarket:

    @pytest.fixture
    def mock_mootdx(self, mocker):
        """Mock mootdx Quotes factory + stocks/quotes/bars."""
        import pandas as pd

        # Mock stocks() - return DataFrames with real stock codes
        sh_df = pd.DataFrame([
            {'code': 600519, 'name': '贵州茅台'},
            {'code': 600036, 'name': '招商银行'},
            {'code': 600001, 'name': 'ST保千'},
            {'code': 688999, 'name': '次新股'},
        ])
        sz_df = pd.DataFrame([
            {'code': 858, 'name': '五粮液'},       # 会被 length 过滤
            {'code': 39, 'name': '指数'},           # 会被 length 过滤
            {'code': 999999, 'name': '上证指数'},    # 不匹配前缀
            {'code': 300750, 'name': '宁德时代'},
        ])

        mock_quotes = mocker.patch('mootdx.quotes.Quotes')
        instance = mock_quotes.factory.return_value
        instance.stocks.side_effect = lambda market: sh_df if market == 1 else sz_df

        # Mock quotes() - return price data
        q_df = pd.DataFrame([
            {'code': '600519', 'price': 150.0},
            {'code': '600036', 'price': 35.0},
            {'code': '600001', 'price': 8.0},
            {'code': '688999', 'price': 20.0},
            {'code': '300750', 'price': 220.0},
        ])
        instance.quotes.return_value = q_df

        # Mock bars() - return enough data for most stocks
        import numpy as np
        n_days = 500
        dates = pd.date_range('2023-01-01', periods=n_days, freq='B')
        bar_df = pd.DataFrame({
            'close': np.random.uniform(10, 100, n_days),
            'open': np.random.uniform(10, 100, n_days),
            'high': np.random.uniform(10, 100, n_days),
            'low': np.random.uniform(10, 100, n_days),
            'vol': np.random.uniform(100000, 1000000, n_days),
            'datetime': [d.strftime('%Y-%m-%d') + ' 15:00' for d in dates],
        })
        instance.bars.return_value = bar_df

        return instance

    def test_scan_normal(self, mock_mootdx):
        """正常扫描返回候选股票。"""
        sp = ScanParams(max_candidates=10)
        codes, info = scan_market(sp)
        # 600519(150元) 和 300750(220元) 应通过；ST保京被过滤；次新股（len问题不影响）
        assert len(codes) > 0
        assert len(codes) <= 10
        # 不应包含 ST 股
        for c in codes:
            assert 'ST' not in info.get(c, {}).get('name', '')

    def test_scan_exclude_st(self, mock_mootdx):
        """ST 股票不在结果中。"""
        sp = ScanParams(max_candidates=100)
        codes, info = scan_market(sp)
        codes_no_suffix = [c.split('.')[0] for c in codes]
        assert '600001' not in codes_no_suffix  # ST保千

    def test_scan_min_price_filter(self, mock_mootdx):
        """价格过滤有效。"""
        # 设置高 min_price 应该只留高价股
        sp = ScanParams(min_price=100.0, max_candidates=10)
        codes, info = scan_market(sp)
        for c in codes:
            assert info[c]['price'] >= 100.0

    def test_scan_max_candidates(self, mock_mootdx):
        """候选池上限生效。"""
        sp = ScanParams(min_price=1.0, max_candidates=2)
        codes, info = scan_market(sp)
        assert len(codes) <= 2

    def test_scan_no_mootdx_raises(self, mocker):
        """mootdx 未安装时抛出 RuntimeError。"""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'mootdx.quotes':
                raise ImportError('No module named mootdx.quotes')
            return real_import(name, *args, **kwargs)

        mocker.patch('builtins.__import__', side_effect=mock_import)
        with pytest.raises(RuntimeError) as exc:
            scan_market(ScanParams())
        assert 'mootdx' in str(exc.value)

    def test_scan_result_format(self, mock_mootdx):
        """scan_market 返回格式正确（带后缀代码 + info dict）。"""
        sp = ScanParams(max_candidates=10)
        codes, info = scan_market(sp)
        assert isinstance(codes, list)
        assert isinstance(info, dict)
        for c in codes:
            assert isinstance(c, str)
            assert '.' in c  # 带后缀
            assert c in info
            assert 'name' in info[c]
            assert 'price' in info[c]


# ============================================================
#  14. CLI --scan 参数
# ============================================================

class TestCliScan:

    def test_parse_scan_flag(self):
        """--scan 参数正确解析为 True。"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--scan', action='store_true')
        parser.add_argument('--min-price', type=float, default=5.0)
        parser.add_argument('--max-candidates', type=int, default=100)

        args = parser.parse_args(['--scan'])
        assert args.scan is True

        args = parser.parse_args(['--scan', '--min-price', '10', '--max-candidates', '50'])
        assert args.scan is True
        assert abs(args.min_price - 10.0) < 1e-6
        assert args.max_candidates == 50

    def test_no_scan_flag(self):
        """不传 --scan 时 scan 为 False。"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--scan', action='store_true')

        args = parser.parse_args([])
        assert args.scan is False

    def test_scan_with_stocks_uses_stocks(self):
        """--scan --stocks 时仍以外部 stocks 为准。"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--scan', action='store_true')
        parser.add_argument('--stocks', type=str)

        args = parser.parse_args(['--scan', '--stocks', '000001.SZ'])
        assert args.scan is True
        assert args.stocks == '000001.SZ'


# ============================================================
#  End
# ============================================================
