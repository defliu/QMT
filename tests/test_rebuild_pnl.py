# coding=utf-8
"""rebuild_cumulative_pnl_from_csv 测试

覆盖场景：
1. 单CSV清仓股重建
2. 多CSV按代码去重取最新
3. 跳过今日CSV
4. 无CSV返回None
5. 持仓股不计入
6. 策略名从config读取
7. CUMULATIVE_PNL_FILE文件名含STRATEGY_KEY
"""
import sys
import os
import glob as _glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


HEADER = "资金账号,交易所,证券代码,证券名称,当前拥股,可用数量,冻结数量,成本价,最新价,持仓盈亏,浮动盈亏,盈亏比例\n"


def _make_csv_row(code, name, vol, pnl):
    return "%s,1,%s,%s,%d,0,0,10.00,10.50,%.2f,0.00,0.05\n" % (
        '67014907', code, name, vol, pnl)


def _write_csv(filepath, rows, encoding='gbk'):
    with open(filepath, 'w', encoding=encoding) as f:
        f.write(HEADER)
        for row in rows:
            f.write(row)


_real_glob = _glob.glob


def _call_rebuild(csv_dir, today_str='20260701'):
    """调用 rebuild_cumulative_pnl_from_csv，mock glob 和 datetime"""
    import adapters.qmt_wrapper as qmt
    from unittest.mock import patch, MagicMock

    mock_dt_cls = MagicMock()
    mock_dt_cls.now.return_value.strftime.return_value = today_str

    def fake_glob(pattern):
        return _real_glob(os.path.join(csv_dir, '持仓明细_*.csv'))

    with patch.object(qmt, 'datetime', mock_dt_cls), \
         patch('glob.glob', side_effect=fake_glob):
        return qmt.rebuild_cumulative_pnl_from_csv()


class TestRebuildClosedPosition:
    """单CSV清仓股重建"""

    def test_rebuild_closed_position(self, tmp_path):
        csv_dir = str(tmp_path)
        _write_csv(os.path.join(csv_dir, '持仓明细_20260630.csv'), [
            _make_csv_row('600641', '先导基电', 0, 2280.41),
            _make_csv_row('603283', '赛腾股份', 300, 240.99),
        ])
        result = _call_rebuild(csv_dir)
        assert abs(result - 2280.41) < 0.01, "重建值应为2280.41，实际: %s" % result


class TestRebuildMultiCsvDedup:
    """多CSV按代码去重取最新"""

    def test_rebuild_multi_csv_dedup(self, tmp_path):
        csv_dir = str(tmp_path)
        _write_csv(os.path.join(csv_dir, '持仓明细_20260629.csv'), [
            _make_csv_row('600641', '先导基电', 0, 2000.00),
        ])
        _write_csv(os.path.join(csv_dir, '持仓明细_20260630.csv'), [
            _make_csv_row('600641', '先导基电', 0, 2280.41),
        ])
        result = _call_rebuild(csv_dir)
        assert abs(result - 2280.41) < 0.01, "多CSV去重应取最新值2280.41，实际: %s" % result


class TestRebuildSkipToday:
    """跳过今日CSV"""

    def test_rebuild_skip_today(self, tmp_path):
        csv_dir = str(tmp_path)
        _write_csv(os.path.join(csv_dir, '持仓明细_20260701.csv'), [
            _make_csv_row('600641', '先导基电', 0, 2280.41),
        ])
        result = _call_rebuild(csv_dir, today_str='20260701')
        assert result is None, "今日CSV应被跳过，返回None，实际: %s" % result


class TestRebuildNoCsvFallback:
    """无CSV返回None"""

    def test_rebuild_no_csv_fallback(self, tmp_path):
        result = _call_rebuild(str(tmp_path))
        assert result is None, "无CSV时应返回None，实际: %s" % result


class TestRebuildHoldingNotCounted:
    """拥股>0的持仓盈亏不计入"""

    def test_rebuild_holding_not_counted(self, tmp_path):
        csv_dir = str(tmp_path)
        _write_csv(os.path.join(csv_dir, '持仓明细_20260630.csv'), [
            _make_csv_row('603283', '赛腾股份', 300, 240.99),
            _make_csv_row('688396', '华润微', 900, 3240.90),
        ])
        result = _call_rebuild(csv_dir)
        assert result == 0.0, "拥股>0不应计入，实际: %s" % result


class TestStrategyNameFromConfig:
    """策略名从config读取"""

    def test_strategy_name_from_config(self):
        import adapters.qmt_wrapper as qmt
        assert qmt.STRATEGY_NAME == '主升浪6+2', "STRATEGY_NAME应为主升浪6+2，实际: %s" % qmt.STRATEGY_NAME
        assert qmt.STRATEGY_KEY == 'DUAL_BAND', "STRATEGY_KEY应为DUAL_BAND，实际: %s" % qmt.STRATEGY_KEY


class TestCumulativePnlFileNaming:
    """CUMULATIVE_PNL_FILE文件名含STRATEGY_KEY"""

    def test_cumulative_pnl_file_naming(self):
        import adapters.qmt_wrapper as qmt
        assert 'DUAL_BAND' in qmt.CUMULATIVE_PNL_FILE, "CUMULATIVE_PNL_FILE应含DUAL_BAND，实际: %s" % qmt.CUMULATIVE_PNL_FILE


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
