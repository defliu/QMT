# coding=utf-8
"""_is_export_time 和 export_daily_data 时间锁测试

覆盖场景：
1. 工作日 15:00 后返回 True
2. 工作日 15:00 前返回 False
3. 工作日恰好 15:00 返回 True（边界 >=1500）
4. 周六返回 False
5. 周日返回 False
6. 非导出时段 export_daily_data 返回 [] 且不调 get_trade_detail_data
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import qmt_daily_export as qmt

import pytest
from unittest.mock import patch, MagicMock


class TestIsExportTimeWeekdayAfter1500:
    """工作日 15:00 后返回 True"""

    def test_weekday_after_1500(self):
        mock_dt = MagicMock()
        mock_dt.now.return_value.weekday.return_value = 2  # Wednesday
        mock_dt.now.return_value.strftime.return_value = '1510'
        with patch.object(qmt, 'datetime', mock_dt):
            assert qmt._is_export_time(None) is True


class TestIsExportTimeWeekdayBefore1500:
    """工作日 15:00 前返回 False"""

    def test_weekday_before_1500(self):
        mock_dt = MagicMock()
        mock_dt.now.return_value.weekday.return_value = 2  # Wednesday
        mock_dt.now.return_value.strftime.return_value = '1400'
        with patch.object(qmt, 'datetime', mock_dt):
            assert qmt._is_export_time(None) is False


class TestIsExportTimeWeekdayExactly1500:
    """工作日恰好 15:00 返回 True（边界 >=1500）"""

    def test_weekday_exactly_1500(self):
        mock_dt = MagicMock()
        mock_dt.now.return_value.weekday.return_value = 2  # Wednesday
        mock_dt.now.return_value.strftime.return_value = '1500'
        with patch.object(qmt, 'datetime', mock_dt):
            assert qmt._is_export_time(None) is True


class TestIsExportTimeWeekendSaturday:
    """周六返回 False"""

    def test_weekend_saturday(self):
        mock_dt = MagicMock()
        mock_dt.now.return_value.weekday.return_value = 5  # Saturday
        mock_dt.now.return_value.strftime.return_value = '1510'
        with patch.object(qmt, 'datetime', mock_dt):
            assert qmt._is_export_time(None) is False


class TestIsExportTimeWeekendSunday:
    """周日返回 False"""

    def test_weekend_sunday(self):
        mock_dt = MagicMock()
        mock_dt.now.return_value.weekday.return_value = 6  # Sunday
        mock_dt.now.return_value.strftime.return_value = '1510'
        with patch.object(qmt, 'datetime', mock_dt):
            assert qmt._is_export_time(None) is False


class TestExportDailyDataSkipsWhenNotTime:
    """非导出时段 export_daily_data 返回 [] 且不调 get_trade_detail_data"""

    def test_export_daily_data_skips(self):
        mock_dt = MagicMock()
        mock_dt.now.return_value.weekday.return_value = 2  # Wednesday
        mock_dt.now.return_value.strftime.return_value = '1000'
        mock_get_trade = MagicMock(side_effect=Exception('should not be called'))
        qmt.get_trade_detail_data = mock_get_trade
        try:
            with patch.object(qmt, 'datetime', mock_dt):
                result = qmt.export_daily_data(None)
                assert result == [], "非导出时段应返回空列表，实际: %s" % result
                mock_get_trade.assert_not_called()
        finally:
            del qmt.get_trade_detail_data


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
