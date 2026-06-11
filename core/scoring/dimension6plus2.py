# coding=utf-8
"""6+2 Fused Scoring Module — DEEPSEEK 6-dimension breakout framework
   + Sentiment + Sector Heat (pure pandas/numpy, zero QMT dependency).

     # | Dimension              | Weight
    ---|------------------------|--------
     1 | Breakout Validity      | 22
     2 | Trend Health           | 13
     3 | Consolidation Strength | 20
     4 | Volume-Price Health    | 12
     5 | MACD Momentum          | 12
     6 | Valuation Safety       |  7
     7 | Sentiment              |  7
     8 | Sector Heat            |  7
       | **Total**              | 100
"""

import json
import warnings

import numpy as np
import pandas as pd

from core.utils import calc_bias, calc_macd, ma, safe_last


class ScoreCalculator6Plus2:
    """6+2 fused scorer. Pure calculation — no QMT/xtquant dependency."""

    def __init__(self, sector_heat_path="D:/QMT_POOL/sector_heat.json"):
        self._heat_map = {}
        self._load_sector_heat(sector_heat_path)

    # ------------------------------------------------------------
    # Sector heat loading (same pattern as ScoreCalculator8D)
    # ------------------------------------------------------------
    def _load_sector_heat(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            data = json.loads(raw)
            if isinstance(data, dict):
                self._heat_map = data.get("stock_heat", data)
            else:
                self._heat_map = {}
            if not isinstance(self._heat_map, dict):
                self._heat_map = {}
        except Exception:
            self._heat_map = {}

    def update_sector_bonus(self, bonus_map):
        """动态注入板块热度（运行时更新，覆盖文件加载）"""
        if not bonus_map:
            return
        for code, heat in bonus_map.items():
            clean = code.replace('.SZ','').replace('.SH','').replace('.BJ','')
            self._heat_map[code] = heat
            self._heat_map[clean] = heat

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------
    def score_pool(
        self,
        pool_dict,
        fundamentals=None,
    ):
        """Score an entire pool cross-sectionally.

        Returns DataFrame indexed by stock_code with columns:
          [score_breakout, score_trend, score_consolidation, score_volumeprice,
           score_macd, score_valuation, score_sentiment, score_sector, score_total]
        """
        if not pool_dict:
            columns = [
                "score_breakout", "score_trend", "score_consolidation",
                "score_volumeprice", "score_macd", "score_valuation",
                "score_sentiment", "score_sector", "score_total",
            ]
            return pd.DataFrame(index=pd.Index([], name="stock_code"), columns=columns)

        # ---- Pass 1: compute 6 core dimensions + 5d return per stock ----
        records = {}
        fund = fundamentals or {}

        for code, df in pool_dict.items():
            if df is None or len(df) < 1:
                continue

            n = len(df)
            if n < 30:
                warnings.warn(f"[dimension6plus2] {code} has only {n} bars (< 30) — scoring with limited data")

            rec = self._score_core_dimensions(code, df, fund.get(code))

            # Collect 5-day return for cross-sectional sentiment
            rec["_ret_5d"] = self._compute_5d_return(df)
            records[code] = rec

        if not records:
            columns = [
                "score_breakout", "score_trend", "score_consolidation",
                "score_volumeprice", "score_macd", "score_valuation",
                "score_sentiment", "score_sector", "score_total",
            ]
            return pd.DataFrame(index=pd.Index([], name="stock_code"), columns=columns)

        # ---- Pass 2: cross-sectional sentiment ----
        ret_series = pd.Series(
            {code: rec["_ret_5d"] for code, rec in records.items()}
        ).dropna()
        sentiment_scores = self._compute_sentiment_scores(ret_series)

        # ---- Pass 3: sector heat lookup ----
        sector_scores = {}
        for code in records:
            clean = code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
            heat = self._heat_map.get(code, self._heat_map.get(clean, None))
            if heat is None:
                sector_scores[code] = 3.5
            else:
                sector_scores[code] = 7.0 * max(0.0, min(100.0, float(heat))) / 100.0

        # ---- Assemble result ----
        rows = []
        for code, rec in records.items():
            rows.append(
                {
                    "stock_code": code,
                    "score_breakout": rec["score_breakout"],
                    "score_trend": rec["score_trend"],
                    "score_consolidation": rec["score_consolidation"],
                    "score_volumeprice": rec["score_volumeprice"],
                    "score_macd": rec["score_macd"],
                    "score_valuation": rec["score_valuation"],
                    "score_sentiment": sentiment_scores.get(code, 3.5),
                    "score_sector": sector_scores.get(code, 3.5),
                }
            )

        result = pd.DataFrame(rows)
        result["score_total"] = (
            result["score_breakout"]
            + result["score_trend"]
            + result["score_consolidation"]
            + result["score_volumeprice"]
            + result["score_macd"]
            + result["score_valuation"]
            + result["score_sentiment"]
            + result["score_sector"]
        )
        return result.set_index("stock_code")

    def score_single(
        self,
        stock_code,
        df,
        dynamic_pe=None,
        static_pe=None,
        pool_5d_returns=None,
    ):
        """Score a single stock.

        If pool_5d_returns is provided, sentiment is computed from it;
        otherwise sentiment defaults to 3.5 (neutral).
        """
        fund = {}
        if dynamic_pe is not None:
            fund["dynamic_pe"] = dynamic_pe
        if static_pe is not None:
            fund["static_pe"] = static_pe

        rec = self._score_core_dimensions(stock_code, df, fund)

        # Sentiment
        if pool_5d_returns is not None and stock_code in pool_5d_returns.index:
            sret = pool_5d_returns.loc[stock_code]
            if pd.notna(sret):
                sentiment_map = self._compute_sentiment_scores(pool_5d_returns.dropna())
                rec["score_sentiment"] = sentiment_map.get(stock_code, 3.5)
            else:
                rec["score_sentiment"] = 3.5
        else:
            rec["score_sentiment"] = 3.5

        # Sector heat
        clean = stock_code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
        heat = self._heat_map.get(stock_code, self._heat_map.get(clean, None))
        if heat is None:
            rec["score_sector"] = 3.5
        else:
            rec["score_sector"] = 7.0 * max(0.0, min(100.0, float(heat))) / 100.0

        rec["score_total"] = (
            rec["score_breakout"]
            + rec["score_trend"]
            + rec["score_consolidation"]
            + rec["score_volumeprice"]
            + rec["score_macd"]
            + rec["score_valuation"]
            + rec["score_sentiment"]
            + rec["score_sector"]
        )
        return rec

    # ------------------------------------------------------------
    # Internal scoring helpers
    # ------------------------------------------------------------
    @staticmethod
    def _compute_5d_return(df):
        if len(df) < 7:
            return float("nan")
        return float(df["close"].iloc[-1] / df["close"].iloc[-6] - 1)

    @staticmethod
    def _score_breakout(df):
        """Dimension 1: Breakout Validity (22分)."""
        if len(df) < 21:
            return 0.0

        high = df["high"]
        low = df["low"]
        close = df["close"]
        volume = df["volume"]

        resistance = high.rolling(20).max().shift(1)
        amplitude_20 = high.rolling(20).max() / low.rolling(20).min() - 1

        amp_last = safe_last(amplitude_20)
        is_dense = amp_last <= 0.15

        res_last = safe_last(resistance)
        close_last = safe_last(close)
        if res_last <= 0.0:
            return 0.0
        breakout_pct = (close_last - res_last) / res_last * 100.0
        is_breakout = breakout_pct > 0.0

        vol_ma5 = volume.rolling(5).mean()
        vol_ratio = safe_last(volume) / safe_last(vol_ma5) if safe_last(vol_ma5) > 0 else 0.0

        if is_breakout and is_dense:
            base = 15.0
        elif is_breakout and not is_dense:
            base = 8.0
        else:
            base = 0.0

        if vol_ratio >= 2.0:
            vol_bonus = 7.0
        elif vol_ratio >= 1.2:
            vol_bonus = 4.0
        else:
            vol_bonus = 0.0

        return min(base + vol_bonus, 22.0)

    @staticmethod
    def _score_trend(df):
        """Dimension 2: Trend Health (13分)."""
        if len(df) < 6:
            return 0.0

        close = df["close"]
        ma5 = ma(close, 5)
        bias_5 = calc_bias(safe_last(close), safe_last(ma5))

        if 0.0 < bias_5 <= 12.0:
            return 13.0
        elif 12.0 < bias_5 <= 15.0:
            return 7.0
        else:
            return 0.0

    @staticmethod
    def _score_consolidation(df):
        """Dimension 3: Consolidation Strength (20分).

        For each of the last 5 trading days, check if low >= ma5 * 0.998.
        ma5 is computed per-day.
        """
        if len(df) < 5:
            return 0.0

        close = df["close"]
        low = df["low"]
        ma5 = ma(close, 5)

        # Use last 5 rows
        n_available = min(5, len(df))
        hold_days = 0
        for i in range(-n_available, 0):
            threshold = ma5.iloc[i] * 0.998
            if pd.notna(threshold) and low.iloc[i] >= threshold:
                hold_days += 1

        if n_available < 5:
            # Scale proportionally
            hold_days = int(round(hold_days * 5.0 / n_available))

        if hold_days >= 5:
            return 20.0
        elif hold_days == 4:
            return 15.0
        elif hold_days == 3:
            return 10.0
        else:
            return 0.0

    @staticmethod
    def _score_volume_price(df):
        """Dimension 4: Volume-Price Health (12分)."""
        if len(df) < 6:
            return 0.0

        volume = df["volume"]
        vol_ma5 = volume.rolling(5).mean()
        vol_ratio = safe_last(volume) / safe_last(vol_ma5) if safe_last(vol_ma5) > 0 else 0.0

        if vol_ratio <= 1.5:
            return 12.0
        elif vol_ratio <= 2.5:
            # Linear decay from 12 to 0
            return 12.0 * (2.5 - vol_ratio) / 1.0
        else:
            return 0.0

    @staticmethod
    def _score_macd(df):
        """Dimension 5: MACD Momentum (12分)."""
        if len(df) < 27:
            return 0.0

        close = df["close"]
        _, _, macd = calc_macd(close)

        macd_today = safe_last(macd)
        macd_yesterday = macd.iloc[-2] if len(macd) >= 2 else 0.0
        if pd.isna(macd_yesterday):
            macd_yesterday = 0.0

        if macd_today >= macd_yesterday:
            return 12.0
        else:
            if macd_today > 0 and macd_yesterday > 0:
                return 6.0
            elif macd_today > 0 and macd_yesterday <= 0:
                return 9.0
            elif macd_today <= 0 and macd_yesterday > 0:
                return 3.0
            else:
                return 0.0

    @staticmethod
    def _score_valuation(
        dynamic_pe,
        static_pe,
    ):
        """Dimension 6: Valuation Safety (7分)."""
        if dynamic_pe is None or static_pe is None or dynamic_pe <= 0.0 or static_pe <= 0.0:
            return 3.5
        if dynamic_pe <= static_pe:
            return 7.0
        ratio = static_pe / dynamic_pe
        return 7.0 * max(0.0, ratio)

    def _score_core_dimensions(
        self,
        code,
        df,
        fund,
    ):
        """Compute dimensions 1-6 for a single stock."""
        dynamic_pe = None
        static_pe = None
        if fund:
            dynamic_pe = fund.get("dynamic_pe")
            static_pe = fund.get("static_pe")

        return {
            "score_breakout": self._score_breakout(df),
            "score_trend": self._score_trend(df),
            "score_consolidation": self._score_consolidation(df),
            "score_volumeprice": self._score_volume_price(df),
            "score_macd": self._score_macd(df),
            "score_valuation": self._score_valuation(dynamic_pe, static_pe),
        }

    @staticmethod
    def _compute_sentiment_scores(ret_5d):
        """Dimension 7: Sentiment (7分) — cross-sectional percentile mapping."""
        n = len(ret_5d)
        if n == 0:
            return {}
        if n == 1:
            return {ret_5d.index[0]: 7.0}

        ranked = ret_5d.sort_values(ascending=False)  # rank 0 = best
        scores = {}
        for i, code in enumerate(ranked.index):
            pctile = (n - 1 - i) / (n - 1) * 100.0  # 0 = worst, 100 = best
            if pctile >= 80.0:
                scores[code] = 7.0
            elif pctile <= 20.0:
                scores[code] = 0.0
            else:
                scores[code] = 7.0 * (pctile - 20.0) / 60.0
        return scores
