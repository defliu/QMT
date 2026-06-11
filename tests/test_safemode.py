# coding=utf-8
"""SAFEMODE 安全壳专项测试"""
import os
import csv
import pytest
from datetime import datetime

from adapters.qmt_wrapper import (
    SAFEMODE_LOG_DIR,
    Trader, StrategyRunner,
    _safemode_log_trade_blocked, _safemode_log_signal,
)


@pytest.fixture
def safemode_log_dir(tmp_path, monkeypatch):
    """每个 logger 测试使用独立的临时目录，互不干扰。"""
    import adapters.qmt_wrapper as qmt
    log_dir = str(tmp_path / "safemode_logs")
    monkeypatch.setattr(qmt, 'SAFEMODE_LOG_DIR', log_dir)
    monkeypatch.setattr(qmt, 'SAFEMODE_ENABLED', True)
    return log_dir


class TestSafemodeGlobals:
    """SAFEMODE 全局标志位"""

    def test_safemode_enabled_true(self):
        """配置文件 safemode.enabled=true 时，SAFEMODE_ENABLED 应为 True"""
        import adapters.qmt_wrapper as qmt
        assert qmt.SAFEMODE_ENABLED is True

    def test_safemode_log_dir_valid(self):
        """SAFEMODE_LOG_DIR 应配置为非空路径"""
        assert SAFEMODE_LOG_DIR
        assert isinstance(SAFEMODE_LOG_DIR, str)
        assert SAFEMODE_LOG_DIR.startswith('D:/QMT_POOL')


class TestTraderSafemodeInterception:
    """Trader.buy() / Trader.sell() 在 SAFEMODE 下的行为"""

    def test_buy_returns_mock_order_id(self, mock_context):
        """buy() 在 SAFEMODE 下应返回 mock order_id，不抛出异常"""
        trader = Trader(mock_context, '67014907', 'STOCK', 'TestStrategy')
        result = trader.buy('000001.SZ', 1000, remark='测试买入')
        assert result is not None
        assert isinstance(result, str)
        assert result.startswith('safemode_')

    def test_sell_returns_mock_order_id(self, mock_context):
        """sell() 在 SAFEMODE 下应返回 mock order_id，不抛出异常"""
        trader = Trader(mock_context, '67014907', 'STOCK', 'TestStrategy')
        result = trader.sell('000001.SZ', 500, remark='测试卖出')
        assert result is not None
        assert isinstance(result, str)
        assert result.startswith('safemode_')

    def test_direct_passorder_asserts(self, mock_context):
        """_passorder() 在 SAFEMODE 下直接调用应触发 AssertionError（金丝雀）"""
        trader = Trader(mock_context, '67014907', 'STOCK', 'TestStrategy')
        with pytest.raises(AssertionError) as exc_info:
            trader._passorder(23, '000001.SZ', 1000, 'test')
        assert 'SAFEMODE_CRASH' in str(exc_info.value)


class TestSafemodeRunner:
    """StrategyRunner 在 SAFEMODE 下的行为"""

    def test_handlebar_no_exception(self, mock_context, mock_klines):
        """handlebar() 在 SAFEMODE 下不应抛出异常，应正常完成"""
        runner = StrategyRunner()
        runner.init(mock_context)
        try:
            runner.handlebar(mock_context)
        except Exception:
            pytest.fail("handlebar() raised unexpected exception in SAFEMODE")
        assert True

    def test_exit_no_file_write(self, mock_context):
        """exit() 在 SAFEMODE 下不应写入持仓/净值文件"""
        runner = StrategyRunner()
        runner.init(mock_context)

        hold_file = 'D:/QMT_POOL/endofday_holdings_beat.txt'
        nav_file = 'D:/QMT_POOL/endofday_nav_beat.txt'
        hold_before = os.path.getmtime(hold_file) if os.path.exists(hold_file) else None
        nav_before = os.path.getmtime(nav_file) if os.path.exists(nav_file) else None

        runner.exit(mock_context)

        hold_after = os.path.getmtime(hold_file) if os.path.exists(hold_file) else None
        nav_after = os.path.getmtime(nav_file) if os.path.exists(nav_file) else None

        assert hold_after == hold_before, "exit() 在 SAFEMODE 下不应修改持仓文件"
        assert nav_after == nav_before, "exit() 在 SAFEMODE 下不应修改净值文件"


class TestSafemodeLogger:
    """SAFEMODE 日志工具"""

    def test_log_trade_blocked_creates_csv(self, safemode_log_dir):
        """_safemode_log_trade_blocked 应创建 CSV 日志文件"""
        today = datetime.now().strftime('%Y%m%d')
        log_path = os.path.join(safemode_log_dir, 'trades_blocked_%s.csv' % today)

        _safemode_log_trade_blocked('000001.SZ', 'buy', 1000, 10.5, '测试', 'test_source')

        assert os.path.exists(log_path)
        with open(log_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) >= 1
        assert rows[0] == ['timestamp', 'stock_code', 'direction', 'volume', 'price', 'remark', 'source_function']
        assert rows[1][1] == '000001.SZ'
        assert rows[1][2] == 'buy'

    def test_log_signal_creates_csv(self, safemode_log_dir):
        """_safemode_log_signal 应创建 CSV 日志文件"""
        today = datetime.now().strftime('%Y%m%d')
        log_path = os.path.join(safemode_log_dir, 'signals_%s.csv' % today)

        _safemode_log_signal('000001.SZ', 85.5, 3, 2)

        assert os.path.exists(log_path)
        with open(log_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) >= 1
        assert rows[0] == ['timestamp', 'stock_code', 'score_8d', 'buy_points', 'sector_heat']
        assert rows[1][1] == '000001.SZ'
        assert rows[1][2] == '85.5'

    def test_log_trade_blocked_append(self, safemode_log_dir):
        """多次调用应追加行而非覆盖（self-contained，不依赖前置用例）。"""
        today = datetime.now().strftime('%Y%m%d')
        log_path = os.path.join(safemode_log_dir, 'trades_blocked_%s.csv' % today)

        # Setup row + 2 test rows = 3 data rows total
        _safemode_log_trade_blocked('000000.SH', 'buy', 100, 5.0, 'setup', 'setup')
        _safemode_log_trade_blocked('600001.SH', 'sell', 500, 20.0, '测试2', 'test_source2')
        _safemode_log_trade_blocked('300001.SZ', 'buy', 200, 15.0, '测试3', 'test_source3')

        with open(log_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) == 4  # header + 3 data rows
        assert rows[2][1] == '600001.SH'  # second data row is 600001.SH

    def test_safemode_started_log_created(self, mock_context, tmp_path, monkeypatch):
        """init() 在 SAFEMODE 下应创建 safemode_started.log（self-contained）。"""
        import adapters.qmt_wrapper as qmt
        log_dir = str(tmp_path / "safemode_logs")
        monkeypatch.setattr(qmt, 'SAFEMODE_LOG_DIR', log_dir)
        monkeypatch.setattr(qmt, 'SAFEMODE_ENABLED', True)
        monkeypatch.setattr(qmt, '_g_init_done', False)

        runner = StrategyRunner()
        runner.init(mock_context)

        log_path = os.path.join(log_dir, "safemode_started.log")
        assert os.path.exists(log_path)
        with open(log_path, 'r') as f:
            content = f.read()
        assert 'SAFEMODE ACTIVE' in content


class TestSafemodeDirectory:
    """SAFEMODE 日志目录"""

    def test_safemode_log_dir_exists(self):
        """safemode_logs/ 目录应自动创建"""
        assert os.path.exists(SAFEMODE_LOG_DIR)
        assert os.path.isdir(SAFEMODE_LOG_DIR)

    def test_csv_format_readable(self):
        """CSV 日志格式应正确可读"""
        today = datetime.now().strftime('%Y%m%d')
        trade_log = os.path.join(SAFEMODE_LOG_DIR, 'trades_blocked_%s.csv' % today)
        signal_log = os.path.join(SAFEMODE_LOG_DIR, 'signals_%s.csv' % today)

        for log_path in [trade_log, signal_log]:
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                assert len(rows) > 0  # 至少表头存在
                # 验证表头不为空，行数可计数
                assert all(isinstance(row, list) for row in rows)
