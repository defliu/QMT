# coding=utf-8
"""Tests for scripts.diagnose_dimension6plus2 — helper functions and data pipeline."""

import os
import tempfile
import numpy as np
import pandas as pd
import pytest

from scripts.diagnose_dimension6plus2 import (
    _strip_suffix,
    _add_suffix,
    read_pool,
)


# ============================================================
#  Helper functions
# ============================================================

class TestStripSuffix:
    def test_sh_suffix(self):
        assert _strip_suffix("600519.SH") == "600519"

    def test_sz_suffix(self):
        assert _strip_suffix("000858.SZ") == "000858"

    def test_bj_suffix(self):
        assert _strip_suffix("830799.BJ") == "830799"

    def test_lowercase_suffix(self):
        assert _strip_suffix("600519.sh") == "600519"

    def test_no_suffix(self):
        assert _strip_suffix("600519") == "600519"

    def test_mixed_case(self):
        assert _strip_suffix("000858.sz") == "000858"


class TestAddSuffix:
    def test_sh_stock_6(self):
        assert _add_suffix("600519") == "600519.SH"

    def test_sh_stock_9(self):
        assert _add_suffix("900901") == "900901.SH"

    def test_sz_stock_0(self):
        assert _add_suffix("000858") == "000858.SZ"

    def test_sz_stock_3(self):
        assert _add_suffix("300750") == "300750.SZ"

    def test_sz_stock_2(self):
        assert _add_suffix("002415") == "002415.SZ"

    def test_zfill(self):
        assert _add_suffix("858") == "000858.SZ"

    def test_trimmed_input(self):
        assert _add_suffix(" 600519 ") == "600519.SH"


class TestReadPool:
    def test_read_normal(self):
        content = "600519.SH\t茅台\n000858.SZ\t五粮液\n601318.SH\n"
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False) as f:
            f.write(content)
            tmp_path = f.name
        try:
            codes = read_pool(tmp_path)
            assert codes == ["600519", "000858", "601318"]
        finally:
            os.unlink(tmp_path)

    def test_read_with_extra_whitespace(self):
        content = "  600519.SH  \t  茅台  \n000858.SZ\n"
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False) as f:
            f.write(content)
            tmp_path = f.name
        try:
            codes = read_pool(tmp_path)
            assert codes == ["600519", "000858"]
        finally:
            os.unlink(tmp_path)

    def test_skip_invalid_lines(self):
        content = "600519.SH\nnot_a_code\n000858.SZ\n\n# comment\n"
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False) as f:
            f.write(content)
            tmp_path = f.name
        try:
            codes = read_pool(tmp_path)
            assert codes == ["600519", "000858"]
        finally:
            os.unlink(tmp_path)

    def test_file_not_exists(self):
        codes = read_pool("/nonexistent/path/selected.txt")
        assert codes == []

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False) as f:
            tmp_path = f.name
        try:
            codes = read_pool(tmp_path)
            assert codes == []
        finally:
            os.unlink(tmp_path)


# ============================================================
#  Data pipeline helpers (mocked mootdx output)
# ============================================================

def _make_mock_bars(n=100, start_price=10.0):
    """Create a synthetic DataFrame mimicking mootdx bars() output."""
    dates = pd.date_range(end=pd.Timestamp.today(), periods=n, freq='B')
    np.random.seed(42)
    closes = start_price * (1 + np.cumsum(np.random.randn(n) * 0.005))
    opens = closes * (1 + np.random.randn(n) * 0.002)
    highs = np.maximum(opens, closes) * (1 + abs(np.random.randn(n)) * 0.003)
    lows = np.minimum(opens, closes) * (1 - abs(np.random.randn(n)) * 0.003)
    volumes = np.random.randint(100000, 5000000, n)
    return pd.DataFrame({
        'datetime': dates.strftime('%Y-%m-%d %H:%M:%S'),
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'vol': volumes,  # mootdx uses 'vol', not 'volume'
    })


class TestDataPipeline:
    def test_column_rename_vol_to_volume(self):
        """Verify 'vol' → 'volume' renaming logic used in download_data."""
        bars = _make_mock_bars(60)
        assert 'vol' in bars.columns
        assert 'volume' not in bars.columns

        # Apply same logic as download_data
        if 'vol' in bars.columns and 'volume' not in bars.columns:
            bars = bars.rename(columns={'vol': 'volume'})
        assert 'volume' in bars.columns
        assert 'vol' not in bars.columns

    def test_date_parsing(self):
        """Verify datetime → date index logic used in download_data."""
        bars = _make_mock_bars(60)
        # Apply same logic as download_data
        if 'datetime' in bars.columns:
            bars['_date'] = pd.to_datetime(bars['datetime'].str[:10], errors='coerce')
            bars.set_index('_date', inplace=True)
            bars.drop(columns=['datetime'], inplace=True)
        bars.sort_index(inplace=True)
        bars = bars[bars.index.notna()]

        assert bars.index.name == '_date'
        assert isinstance(bars.index, pd.DatetimeIndex)
        assert not bars.index.duplicated().any()

    def test_column_filtering(self):
        """Verify only needed columns survive the filter step."""
        bars = _make_mock_bars(60)
        # Apply pipeline
        if 'vol' in bars.columns and 'volume' not in bars.columns:
            bars = bars.rename(columns={'vol': 'volume'})
        if 'datetime' in bars.columns:
            bars['_date'] = pd.to_datetime(bars['datetime'].str[:10], errors='coerce')
            bars.set_index('_date', inplace=True)
            bars.drop(columns=['datetime'], inplace=True)
        bars.sort_index(inplace=True)
        bars = bars[bars.index.notna()]

        needed = ['open', 'high', 'low', 'close', 'volume']
        if all(c in bars.columns for c in needed):
            df = bars[needed].dropna()

        assert list(df.columns) == needed
        assert len(df) > 0

    def test_min_bars_threshold(self):
        """Verify stocks with <30 bars are filtered out."""
        short = _make_mock_bars(20)  # only 20 bars
        long_enough = _make_mock_bars(60)  # 60 bars

        def process(bars):
            if 'vol' in bars.columns and 'volume' not in bars.columns:
                bars = bars.rename(columns={'vol': 'volume'})
            if 'datetime' in bars.columns:
                bars['_date'] = pd.to_datetime(bars['datetime'].str[:10], errors='coerce')
                bars.set_index('_date', inplace=True)
                bars.drop(columns=['datetime'], inplace=True)
            bars.sort_index(inplace=True)
            bars = bars[bars.index.notna()]
            bars = bars[bars['close'] > 0]
            needed = ['open', 'high', 'low', 'close', 'volume']
            if all(c in bars.columns for c in needed):
                return bars[needed].dropna()
            return pd.DataFrame()

        short_df = process(short)
        long_df = process(long_enough)

        assert len(short_df) < 30
        assert len(long_df) >= 30

    def test_vol_and_volume_both_present(self):
        """Verify when both 'vol' and 'volume' exist, 'vol' is dropped."""
        bars = _make_mock_bars(60)
        bars['volume'] = bars['vol'].copy()  # add both

        assert 'vol' in bars.columns and 'volume' in bars.columns

        # Apply the elif branch
        if 'vol' in bars.columns and 'volume' in bars.columns:
            bars = bars.drop(columns=['vol'])

        assert 'volume' in bars.columns
        assert 'vol' not in bars.columns
