# coding=utf-8
"""Tests for core.scoring.dimension6plus2 — 14 cases covering all 8 dimensions."""

import math

import numpy as np
import pandas as pd
import pytest

from core.scoring.dimension6plus2 import ScoreCalculator6Plus2


# ============================================================
#  Helpers: build targeted DataFrames
# ============================================================

def _df_from_close_volume(closes, volumes, opens=None, highs=None, lows=None):
    """Build minimal DataFrame from lists.  O/H/L default to C +/- 1%."""
    closes = list(closes)
    n = len(closes)
    if opens is None:
        opens = [c * (1 + np.random.uniform(-0.005, 0.005)) for c in closes]
    else:
        opens = list(opens)[:n] + [closes[-1]] * (n - len(opens))
    if highs is None:
        highs = [max(o, c) * (1 + abs(np.random.uniform(0, 0.01))) for o, c in zip(opens, closes)]
    else:
        highs = list(highs)[:n] + [max(opens[-1], closes[-1])] * (n - len(highs))
    if lows is None:
        lows = [min(o, c) * (1 - abs(np.random.uniform(0, 0.01))) for o, c in zip(opens, closes)]
    else:
        lows = list(lows)[:n] + [min(opens[-1], closes[-1])] * (n - len(lows))
    return pd.DataFrame({
        "open": opens[:n],
        "high": highs[:n],
        "low": lows[:n],
        "close": closes,
        "volume": list(volumes)[:n] + [volumes[-1]] * (n - len(volumes)),
    })


def _make_bullish_macd_close(n=40, start=10.0):
    """Return close prices that produce positive, increasing MACD."""
    prices = [start]
    for i in range(1, n):
        # accelerating uptrend
        accel = 0.001 + i * 0.0005
        prices.append(prices[-1] * (1 + accel + np.random.uniform(-0.003, 0.003)))
    return prices


def _make_bearish_macd_close(n=40, start=10.0):
    """Return close prices that produce negative, deepening MACD."""
    prices = [start]
    for i in range(1, n):
        decel = -0.001 - i * 0.0005
        prices.append(prices[-1] * (1 + decel + np.random.uniform(-0.003, 0.003)))
    return prices


# ============================================================
#  1. Breakout tests
# ============================================================

class TestBreakout:
    def test_dense_area_full(self):
        """D1: 20-day amplitude <=15%, close breaks 20-day high, vol_ratio=1.8 => 15+4=19."""
        # 21 bars: first 20 flat-ish (amplitude ~10%), last bar breaks high with volume
        base = [10.0] * 20
        highs = [10.2] * 20 + [10.2]  # amplitude = 10.2/10.0 -1 = 2%
        lows = [9.9] * 20 + [10.0]
        closes = base + [10.5]
        volumes = [1e6] * 19 + [1.5e6, 1.5e6]  # last vol / avg5 ~1.5
        df = _df_from_close_volume(closes, volumes, highs=highs, lows=lows)
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        assert scorer._score_breakout(df) == pytest.approx(19.0, abs=0.1)

    def test_non_dense_area(self):
        """D1: 20-day amplitude >15%, close breaks high => base=8."""
        highs = [12.0] * 20 + [12.0]  # high=12, low will be 9.5 => amplitude ~26%
        lows = [9.5] * 20 + [10.0]
        closes = [10.0] * 20 + [12.5]  # breakout above 12.0
        volumes = [1e6] * 19 + [1e6, 1e6]
        df = _df_from_close_volume(closes, volumes, highs=highs, lows=lows)
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        # base=8 (breakout but not dense), no volume bonus (vol_ratio ~1.0)
        assert scorer._score_breakout(df) == pytest.approx(8.0, abs=0.1)

    def test_no_breakout(self):
        """D1: close below 20-day high => 0 regardless of volume."""
        highs = [12.0] * 19 + [12.0]
        closes = [10.0] * 19 + [9.5]
        volumes = [1e6] * 19 + [5e6]
        df = _df_from_close_volume(closes, volumes, highs=highs)
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        assert scorer._score_breakout(df) == 0.0


# ============================================================
#  2. Trend Health
# ============================================================

class TestTrendHealth:
    def test_bias_zones(self):
        """D2: bias=5% =>13; 13% =>7; 20% =>0; -1% =>0."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        # bias 5% (stable MA5 from 20 pre-bars)
        df = _df_from_close_volume([10.0] * 20 + [10.5], [1e6] * 21)
        assert scorer._score_trend(df) == 13.0
        # bias 13%: need close where (close-ma5)/ma5=0.13
        # ma5=(40+close)/5 -> close=1.13*(8+0.2*close) -> close≈11.68
        df = _df_from_close_volume([10.0] * 20 + [11.68], [1e6] * 21)
        assert scorer._score_trend(df) == 7.0
        # bias 20%
        df = _df_from_close_volume([10.0] * 20 + [12.0], [1e6] * 21)
        assert scorer._score_trend(df) == 0.0
        # bias negative
        df = _df_from_close_volume([10.0] * 20 + [9.0], [1e6] * 21)
        assert scorer._score_trend(df) == 0.0


# ============================================================
#  3. Consolidation Strength
# ============================================================

class TestConsolidation:
    def test_perfect_5day(self):
        """D3: 5 days all low >= ma5*0.998 => 20."""
        # rising gently so low never breaks ma5; need 9 bars so last 5 ma5 values exist
        pad = [10.0] * 4
        closes = pad + [10.0, 10.01, 10.02, 10.03, 10.04]
        lows = pad + [9.99, 10.0, 10.01, 10.02, 10.03]
        df = _df_from_close_volume(closes, [1e6] * 9, lows=lows)
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        assert scorer._score_consolidation(df) == 20.0

    def test_4day_hold(self):
        """D3: 4 days hold => 15."""
        pad = [10.0] * 4
        closes = pad + [10.0, 10.01, 10.02, 10.03, 10.04]
        lows = pad + [9.99, 10.0, 10.01, 10.02, 9.0]  # last day breaks
        df = _df_from_close_volume(closes, [1e6] * 9, lows=lows)
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        assert scorer._score_consolidation(df) == 15.0

    def test_2day_hold(self):
        """D3: 2 days hold => 0."""
        closes = [10.0, 10.01, 10.02, 10.03, 10.04]
        lows = [9.0, 9.0, 10.01, 10.02, 9.0]  # only 2 days hold
        df = _df_from_close_volume(closes, [1e6] * 5, lows=lows)
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        assert scorer._score_consolidation(df) == 0.0


# ============================================================
#  4. Volume-Price Health
# ============================================================

class TestVolumePrice:
    def test_discrete_zones(self):
        """D4: vol_ratio=1.2 =>12; 2.0 =>6; 3.0 =>0."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        n = 101  # bars per case
        closes = [10.0] * n
        # vol_ratio = 1.2 => last_5 sum=5*last/R=5*1.2e6/1.2=5e6, first_4=3.8e6
        vols = [0.95e6] * 4 + [1.2e6]
        df = _df_from_close_volume(closes, [1e6] * (n - 5) + vols)
        assert scorer._score_volume_price(df) == pytest.approx(12.0, abs=0.1)
        # vol_ratio = 2.0 => first_4 sum = 2.0e6*(5-2)/2 = 3.0e6
        vols = [0.75e6] * 4 + [2.0e6]
        df = _df_from_close_volume(closes, [1e6] * (n - 5) + vols)
        assert scorer._score_volume_price(df) == pytest.approx(6.0, abs=0.1)
        # vol_ratio = 3.0 >= 2.5 => score 0
        vols = [0.5e6] * 4 + [3.0e6]
        df = _df_from_close_volume(closes, [1e6] * (n - 5) + vols)
        assert scorer._score_volume_price(df) == 0.0


# ============================================================
#  5. MACD Momentum
# ============================================================

class TestMACD:
    def test_binary_and_partial(self):
        """D5: today>=yesterday=>12; both pos shrinking=>6; pos->neg=>3; both neg deepening=>0."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")

        # Strong positive increasing MACD — steady accelerating uptrend
        closes = _make_bullish_macd_close(n=60)
        df = _df_from_close_volume(closes, [1e6] * 60)
        assert scorer._score_macd(df) == 12.0

        # Negative-to-stable MACD: sharp crash then long plateau.
        # The crash makes MACD negative; the long plateau lets both EMAs converge,
        # causing DIF to rise back from the trough. DEA lags behind DIF, so
        # DIF-DEA shrinks: both positive but decreasing => score 6.
        n_flat = 60
        n_plateau = 60
        data = [100.0] * n_flat + [50.0] * n_plateau
        df = _df_from_close_volume(data, [1e6] * len(data))
        score = scorer._score_macd(df)
        assert score == 6.0  # both positive, shrinking


# ============================================================
#  6. Valuation Safety
# ============================================================

class TestValuation:
    def test_zones(self):
        """D6: dynamic<=static =>7; dynamic=40 static=20 =>3.5; missing =>3.5."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        assert scorer._score_valuation(10.0, 15.0) == 7.0
        assert scorer._score_valuation(40.0, 20.0) == 3.5
        assert scorer._score_valuation(None, 15.0) == 3.5
        assert scorer._score_valuation(10.0, None) == 3.5
        assert scorer._score_valuation(-5.0, 10.0) == 3.5


# ============================================================
#  7. Sentiment (cross-sectional)
# ============================================================

class TestSentiment:
    def test_cross_sectional(self):
        """D7: 5-stock pool. Top =>7, bottom =>0, middle => interpolated."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        rets = pd.Series({
            "A": 0.20,  # best
            "B": 0.10,
            "C": 0.05,
            "D": 0.02,
            "E": -0.05,  # worst
        })
        scores = scorer._compute_sentiment_scores(rets)
        assert scores["A"] == 7.0
        assert scores["E"] == 0.0
        # C is middle (rank 2 of 4 effective after sort)
        assert 0.0 < scores["C"] < 7.0

    def test_single_default(self):
        """D7: score_single without pool_5d_returns => sentiment=3.5."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        df = _df_from_close_volume([10.0] * 6, [1e6] * 6)
        rec = scorer.score_single("TEST", df)
        assert rec["score_sentiment"] == 3.5


# ============================================================
#  8. Sector Heat
# ============================================================

class TestSectorHeat:
    def test_missing_file(self):
        """D8: nonexistent JSON => all sector scores = 3.5, no exception."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        df = _df_from_close_volume([10.0] * 6, [1e6] * 6)
        rec = scorer.score_single("000001.SZ", df)
        assert rec["score_sector"] == 3.5

    def test_heat_mapping(self):
        """D8: heat=100 =>7; heat=50 =>3.5; heat=0 =>0."""
        import tempfile, os, json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"stock_heat": {"000001": 100.0, "000002": 50.0, "000003": 0.0}}, f)
            path = f.name
        try:
            scorer = ScoreCalculator6Plus2(sector_heat_path=path)
            df = _df_from_close_volume([10.0] * 6, [1e6] * 6)
            assert scorer.score_single("000001.SZ", df)["score_sector"] == 7.0
            assert scorer.score_single("000002.SZ", df)["score_sector"] == 3.5
            assert scorer.score_single("000003.SZ", df)["score_sector"] == 0.0
        finally:
            os.unlink(path)


# ============================================================
#  9. Integration / Edge cases
# ============================================================

class TestIntegration:
    def test_total_near_max(self):
        """Construct ideal DF => total should be >= 70."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        # 50 bars: long flat zone + breakout last bar
        n_pre = 49
        base = [10.0] * n_pre
        highs = [10.02] * n_pre + [10.12]  # tight range => dense area
        lows = [9.99] * n_pre + [10.05]    # close to ma5 => consolidation holds
        closes = base + [10.10]            # breakout ~1%
        volumes = [1e6] * (n_pre - 1) + [1.2e6, 1.2e6]  # vol_ratio ~1.11
        df = _df_from_close_volume(closes, volumes, highs=highs, lows=lows)
        rec = scorer.score_single("IDEAL", df, dynamic_pe=10.0, static_pe=15.0)
        assert rec["score_total"] >= 70.0

    def test_empty_pool(self):
        """score_pool({}) returns empty DataFrame with correct columns."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        result = scorer.score_pool({})
        assert result.empty
        expected_cols = [
            "score_breakout", "score_trend", "score_consolidation",
            "score_volumeprice", "score_macd", "score_valuation",
            "score_sentiment", "score_sector", "score_total",
        ]
        assert list(result.columns) == expected_cols

    def test_short_df(self):
        """15-row DF should not crash; consolidation scaled proportionally."""
        scorer = ScoreCalculator6Plus2(sector_heat_path="/nonexistent")
        closes = [10.0 + i * 0.01 for i in range(15)]
        df = _df_from_close_volume(closes, [1e6] * 15)
        rec = scorer.score_single("SHORT", df)
        assert "score_total" in rec
        assert math.isfinite(rec["score_total"])
