# coding=utf-8
# 基线版本: CLEAN_BASELINE_V2 | 日期: 2026-07-14 | P3维度已从总分计算中完全移除
"""6+2 Fused Scoring Module — DEEPSEEK 6-dimension breakout framework
   + ShortTermMomentum + Sector Heat + MarketSentiment (pure pandas/numpy, zero QMT dependency).

     # | Dimension              | Weight
    ---|------------------------|--------
     1 | Breakout Validity      | 22
     2 | Trend Health           | 13
     3 | Consolidation Strength | 20
     4 | Volume-Price Health    | 12
     5 | MACD Momentum          | 12
     6 | Valuation Safety       |  7
     7 | ShortTermMomentum      |  7
     8 | Sector Heat            |  7
     9 | MarketSentiment        |  0 (disabled)
       | **Total**              | 110
"""

import json
import warnings

import numpy as np
import pandas as pd

from core.utils import calc_bias, calc_macd, ma, safe_last


class ScoreCalculator6Plus2:
    """6+2 fused scorer. Pure calculation — no QMT/xtquant dependency."""

    def __init__(self, sector_heat_path="D:/QMT_POOL/sector_heat.json", enable_p3_dims=False):
        self._heat_map = {}
        self.enable_p3_dims = enable_p3_dims  # CLEAN_BASELINE_V2: P3 开关 (默认 off)
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
                raw_map = data.get("stock_heat", data)
            else:
                raw_map = {}
            if not isinstance(raw_map, dict):
                raw_map = {}
            # 自动缩放：排名加分(1-10) → 百分比(10-100)
            values = [v for v in raw_map.values() if isinstance(v, (int, float))]
            scale = 1.0
            if values and max(values) <= 10:
                scale = 10.0
            self._heat_map = {k: float(v) * scale for k, v in raw_map.items()}
        except Exception:
            self._heat_map = {}

    def update_sector_bonus(self, bonus_map):
        """动态注入板块热度（运行时更新，覆盖文件加载）。

        bonus_map 中的值可能是排名加分 (1-10) 或百分比 (0-100)。
        自动检测并缩放到 0-100 范围。
        """
        if not bonus_map:
            return
        values = [v for v in bonus_map.values() if isinstance(v, (int, float))]
        scale = 1.0
        if values:
            max_v = max(values)
            if max_v <= 10:
                scale = 10.0
        for code, heat in bonus_map.items():
            scaled = float(heat) * scale
            clean = code.replace('.SZ','').replace('.SH','').replace('.BJ','')
            self._heat_map[code] = scaled
            self._heat_map[clean] = scaled

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
           score_macd, score_valuation, score_short_term_momentum, score_sector,
           score_market_sentiment, score_total]
        """
        if not pool_dict:
            columns = [
                "score_breakout", "score_trend", "score_consolidation",
                "score_volumeprice", "score_macd", "score_valuation",
                "score_short_term_momentum", "score_sector",
                "score_market_sentiment", "score_total",
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
                "score_short_term_momentum", "score_sector",
                "score_market_sentiment", "score_total",
            ]
            return pd.DataFrame(index=pd.Index([], name="stock_code"), columns=columns)

        # ---- Pass 2: cross-sectional sentiment ----
        ret_series = pd.Series(
            {code: rec["_ret_5d"] for code, rec in records.items()}
        ).dropna()
        sentiment_scores = self._compute_sentiment_scores(ret_series)

        # ---- Pass 3: sector heat lookup (enhanced: leader + rotation) ----
        ret_5d_map = {code: rec["_ret_5d"] for code, rec in records.items()}
        sector_scores = {}
        for code in records:
            clean = code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
            heat = self._heat_map.get(code, self._heat_map.get(clean, None))
            if heat is None:
                base_heat = 3.5
            else:
                base_heat = 7.0 * max(0.0, min(100.0, float(heat))) / 100.0

            # 1.2 Rotation filter: heat < 20 as proxy for declining sector (< -3%)
            if heat is not None and heat < 20.0:
                base_heat *= 0.8

            sector_scores[code] = base_heat

        # 1.1 Leader identification: top 20% by 5d return in pool → +1.5
        valid_rets = {c: r for c, r in ret_5d_map.items() if pd.notna(r)}
        if len(valid_rets) > 1:
            sorted_codes = sorted(valid_rets.keys(), key=lambda c: valid_rets[c], reverse=True)
            n_top = max(1, int(len(sorted_codes) * 0.2))
            leader_codes = set(sorted_codes[:n_top])
            for code in leader_codes:
                sector_scores[code] = min(sector_scores[code] + 1.5, 7.0)

        # ---- Pass 4: market sentiment ----
        market_sentiment_scores = {}
        for code, df in pool_dict.items():
            market_sentiment_scores[code] = 0.0  # MarketSentiment disabled

        # ---- Assemble result ----
        rows = []
        for code, rec in records.items():
            row = {
                "stock_code": code,
                "score_breakout": rec["score_breakout"],
                "score_trend": rec["score_trend"],
                "score_consolidation": rec["score_consolidation"],
                "score_volumeprice": rec["score_volumeprice"],
                "score_macd": rec["score_macd"],
                "score_valuation": rec["score_valuation"],
                "score_short_term_momentum": sentiment_scores.get(code, 3.5),
                "score_sector": sector_scores.get(code, 3.5),
                "score_market_sentiment": market_sentiment_scores.get(code, 3.5),
                "score_atr": 0.0,  # P3 disabled by default (CLEAN_BASELINE_V2)
                "score_circ_mv": 0.0,
                "score_fund_flow": 0.0,
            }
            if self.enable_p3_dims:
                df_code = pool_dict.get(code)
                if df_code is not None and len(df_code) > 0:
                    row["score_atr"] = self._score_atr(df_code) if hasattr(self, "_score_atr") else 0.0
                    row["score_circ_mv"] = self._score_circ_mv(df_code) if hasattr(self, "_score_circ_mv") else 0.0
                    row["score_fund_flow"] = self._score_fund_flow(df_code) if hasattr(self, "_score_fund_flow") else 0.0
            rows.append(row)

        result = pd.DataFrame(rows)
        # CLEAN_BASELINE_V2: score_total = P0 原始 8 维 (max=100)。market_sentiment 永不进总分;
        # P3 (atr/circ_mv/fund_flow) 仅当 enable_p3_dims=True 时加入。
        result["score_total"] = (
            result["score_breakout"]
            + result["score_trend"]
            + result["score_consolidation"]
            + result["score_volumeprice"]
            + result["score_macd"]
            + result["score_valuation"]
            + result["score_short_term_momentum"]
            + result["score_sector"]
        )
        if self.enable_p3_dims:
            result["score_total"] = (
                result["score_total"]
                + result["score_atr"]
                + result["score_circ_mv"]
                + result["score_fund_flow"]
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

        # ShortTermMomentum
        if pool_5d_returns is not None and stock_code in pool_5d_returns.index:
            sret = pool_5d_returns.loc[stock_code]
            if pd.notna(sret):
                sentiment_map = self._compute_sentiment_scores(pool_5d_returns.dropna())
                rec["score_short_term_momentum"] = sentiment_map.get(stock_code, 3.5)
            else:
                rec["score_short_term_momentum"] = 3.5
        else:
            rec["score_short_term_momentum"] = 3.5

        # Sector heat (enhanced: leader + rotation)
        clean = stock_code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
        heat = self._heat_map.get(stock_code, self._heat_map.get(clean, None))
        if heat is None:
            score_sec = 3.5
        else:
            score_sec = 12.0 * max(0.0, min(100.0, float(heat))) / 100.0

        # 1.2 Rotation filter: heat < 20 as proxy for declining sector
        if heat is not None and heat < 20.0:
            score_sec *= 0.8

        # 1.1 Leader identification: top 20% by 5d return in pool → +1.5
        if pool_5d_returns is not None and len(pool_5d_returns) > 1:
            valid = pool_5d_returns.dropna()
            if len(valid) > 1:
                sorted_idx = valid.sort_values(ascending=False).index
                n_top = max(1, int(len(sorted_idx) * 0.2))
                leader_set = set(sorted_idx[:n_top])
                if stock_code in leader_set:
                    score_sec = min(score_sec + 1.5, 12.0)

        rec["score_sector"] = score_sec

        # MarketSentiment: 计算保留供参考, CLEAN_BASELINE_V2 起不再计入 score_total
        rec["score_market_sentiment"] = self._score_market_sentiment_single(df)

        # P3 维度: enable_p3_dims 开关门控 (默认 False=不计算不进总分)
        rec["score_atr"] = 0.0
        rec["score_circ_mv"] = 0.0
        rec["score_fund_flow"] = 0.0
        if self.enable_p3_dims:
            rec["score_atr"] = self._score_atr(df) if hasattr(self, "_score_atr") else 0.0
            rec["score_circ_mv"] = self._score_circ_mv(df) if hasattr(self, "_score_circ_mv") else 0.0
            rec["score_fund_flow"] = self._score_fund_flow(df) if hasattr(self, "_score_fund_flow") else 0.0

        # CLEAN_BASELINE_V2: score_total = P0 原始 8 维 (max=100)
        rec["score_total"] = (
            rec["score_breakout"]
            + rec["score_trend"]
            + rec["score_consolidation"]
            + rec["score_volumeprice"]
            + rec["score_macd"]
            + rec["score_valuation"]
            + rec["score_short_term_momentum"]
            + rec["score_sector"]
        )
        if self.enable_p3_dims:
            rec["score_total"] += (
                rec["score_atr"] + rec["score_circ_mv"] + rec["score_fund_flow"]
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
        """Dimension 1: Breakout Validity (16分)."""
        if len(df) < 21:
            return 0.0

        high = df["high"]
        low = df["low"]
        close = df["close"]
        volume = df["volume"]

        resistance = high.rolling(20).max().shift(1)
        amplitude_20 = high.rolling(20).max() / low.rolling(20).min() - 1

        amp_last = safe_last(amplitude_20)
        is_dense = amp_last <= 0.20

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
        """Dimension 2: Trend Health (12分)."""
        if len(df) < 6:
            return 0.0

        close = df["close"]
        ma5 = ma(close, 5)
        bias_5 = calc_bias(safe_last(close), safe_last(ma5))

        if 0.0 < bias_5 <= 12.0:
            return 12.0
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
        """Dimension 5: MACD Momentum (10分)."""
        if len(df) < 27:
            return 0.0

        close = df["close"]
        _, _, macd = calc_macd(close)

        macd_today = safe_last(macd)
        macd_yesterday = macd.iloc[-2] if len(macd) >= 2 else 0.0
        if pd.isna(macd_yesterday):
            macd_yesterday = 0.0

        if macd_today >= macd_yesterday:
            return 10.0
        else:
            if macd_today > 0 and macd_yesterday > 0:
                return 6.0
            elif macd_today > 0 and macd_yesterday <= 0:
                return 8.0
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
        """Dimension 7: ShortTermMomentum (10分) — cross-sectional percentile mapping."""
        n = len(ret_5d)
        if n == 0:
            return {}
        if n == 1:
            return {ret_5d.index[0]: 10.0}

        ranked = ret_5d.sort_values(ascending=False)  # rank 0 = best
        scores = {}
        for i, code in enumerate(ranked.index):
            pctile = (n - 1 - i) / (n - 1) * 100.0  # 0 = worst, 100 = best
            if pctile >= 80.0:
                scores[code] = 10.0
            elif pctile <= 20.0:
                scores[code] = 0.0
            else:
                scores[code] = 10.0 * (pctile - 20.0) / 60.0
        return scores

    @staticmethod
    def _score_market_sentiment_single(df):
        """Dimension 9: MarketSentiment (10分) — cross-sectional percentile mapping.

        Components:
          - 30% 换手率异常度截面 (turnover_rate percentile)
          - 25% 5日涨停板数（市场宽度）(limit_up_count)
          - 20% 涨跌比 (gain_ratio)
          - 15% 北向资金5日净流入 (default 3.5 if no data)
          - 10% 融资余额5日变化率 (default 3.5 if no data)
        """
        if df is None or len(df) < 5:
            return 3.5  # default neutral score

        close = df["close"]
        n = len(df)

        # 1. 换手率异常度 (30%): use turnover_rate if available, else default 3.5
        turnover_score = 3.5
        if "turnover_rate" in df.columns:
            turnover_rate = df["turnover_rate"].iloc[-1]
            if pd.notna(turnover_rate) and turnover_rate > 0:
                # Simple percentile mapping based on absolute value
                # Higher turnover rate -> higher score (up to a point)
                if turnover_rate > 10.0:
                    turnover_score = 10.0
                elif turnover_rate > 5.0:
                    turnover_score = 8.0
                elif turnover_rate > 2.0:
                    turnover_score = 6.0
                elif turnover_rate > 0.5:
                    turnover_score = 4.0
                else:
                    turnover_score = 2.0

        # 2. 5日涨停板数 (25%): count limit up days in last 5 days
        limit_up_count = 0
        up_limit = None
        if "up_limit" in df.columns:
            up_limit = df["up_limit"]
        for i in range(max(0, n - 5), n):
            if up_limit is not None and pd.notna(up_limit.iloc[i]) and up_limit.iloc[i] > 0:
                if close.iloc[i] >= up_limit.iloc[i]:
                    limit_up_count += 1
            else:
                # Fallback: estimate limit up as 10% gain
                if i > 0:
                    prev_close = close.iloc[i - 1]
                    if prev_close > 0 and (close.iloc[i] / prev_close - 1) >= 0.098:
                        limit_up_count += 1
        limit_up_score = min(limit_up_count * 2.0, 10.0)  # 0-5 limit ups -> 0-10

        # 3. 涨跌比 (20%): gain days in last 5 days / 5
        gain_days = 0
        for i in range(max(1, n - 5), n):
            if close.iloc[i] > close.iloc[i - 1]:
                gain_days += 1
        gain_ratio_score = gain_days / 5.0 * 10.0  # 0-5 -> 0-10

        # 4. 北向资金5日净流入 (15%): default 3.5
        northbound_score = 3.5

        # 5. 融资余额5日变化率 (10%): default 3.5
        margin_score = 3.5

        # Weighted average
        total = (
            0.30 * turnover_score +
            0.25 * limit_up_score +
            0.20 * gain_ratio_score +
            0.15 * northbound_score +
            0.10 * margin_score
        )

        return max(0.0, min(10.0, total))


class ScoreCalculator6Plus2Experimental(ScoreCalculator6Plus2):
    """Parameterized experimental 6+2 scorer for backtest comparison."""

    DEFAULT_PARAMS = {
        "breakout_dense_amp": 0.18,
        "breakout_min_pct": 0.3,
        "breakout_ideal_pct": 2.5,
        "breakout_hot_pct": 7.0,
        "breakout_min_close_pos": 0.6,
        "breakout_min_vol_ratio": 1.2,
        "breakout_hot_vol_ratio": 3.0,
        "trend_bias_full": 10.0,
        "trend_bias_max": 14.0,
        "volume_full_ratio": 1.8,
        "volume_zero_ratio": 3.0,
        "macd_hist_improve_days": 3,
    }

    def __init__(self, sector_heat_path="D:/QMT_POOL/sector_heat.json", params=None):
        super().__init__(sector_heat_path=sector_heat_path)
        self.params = dict(self.DEFAULT_PARAMS)
        if params:
            self.params.update(params)

    def _score_breakout(self, df):
        if len(df) < 21:
            return 0.0

        high = df["high"]
        low = df["low"]
        close = df["close"]
        volume = df["volume"]
        p = self.params

        resistance = high.rolling(20).max().shift(1)
        amplitude_20 = high.rolling(20).max() / low.rolling(20).min() - 1
        res_last = safe_last(resistance)
        close_last = safe_last(close)
        high_last = safe_last(high)
        low_last = safe_last(low)
        if res_last <= 0.0:
            return 0.0

        breakout_pct = (close_last - res_last) / res_last * 100.0
        if breakout_pct < p["breakout_min_pct"]:
            return 0.0

        amp_last = safe_last(amplitude_20)
        close_pos = (close_last - low_last) / (high_last - low_last) if high_last > low_last else 0.5
        vol_ma5 = volume.rolling(5).mean()
        vol_ma_last = safe_last(vol_ma5)
        vol_ratio = safe_last(volume) / vol_ma_last if vol_ma_last > 0 else 0.0

        dense_score = 6.0 if amp_last <= p["breakout_dense_amp"] else 3.0
        pct_score = min(6.0, max(0.0, breakout_pct / p["breakout_ideal_pct"] * 6.0))
        if breakout_pct > p["breakout_hot_pct"]:
            pct_score *= 0.5
        pos_score = 4.0 if close_pos >= p["breakout_min_close_pos"] else 0.0
        if vol_ratio >= p["breakout_hot_vol_ratio"]:
            vol_score = 2.0
        elif vol_ratio >= p["breakout_min_vol_ratio"]:
            vol_score = 6.0
        else:
            vol_score = 0.0
        return min(dense_score + pct_score + pos_score + vol_score, 16.0)

    def _score_trend(self, df):
        if len(df) < 6:
            return 0.0

        close = df["close"]
        ma5 = ma(close, 5)
        bias_5 = calc_bias(safe_last(close), safe_last(ma5))
        p = self.params

        if 0.0 < bias_5 <= p["trend_bias_full"]:
            return 13.0
        if p["trend_bias_full"] < bias_5 <= p["trend_bias_max"]:
            return 7.0
        return 0.0

    def _score_volume_price(self, df):
        if len(df) < 6:
            return 0.0

        volume = df["volume"]
        vol_ma5 = volume.rolling(5).mean()
        vol_ma_last = safe_last(vol_ma5)
        vol_ratio = safe_last(volume) / vol_ma_last if vol_ma_last > 0 else 0.0
        p = self.params

        if vol_ratio <= p["volume_full_ratio"]:
            return 12.0
        if vol_ratio <= p["volume_zero_ratio"]:
            return 12.0 * (p["volume_zero_ratio"] - vol_ratio) / (p["volume_zero_ratio"] - p["volume_full_ratio"])
        return 0.0

    def _score_macd(self, df):
        if len(df) < 30:
            return 0.0

        close = df["close"]
        diff, dea, macd = calc_macd(close)
        p = self.params
        days = int(p["macd_hist_improve_days"])
        recent = macd.iloc[-days:]
        if len(recent) < days or recent.isna().any():
            return 0.0

        macd_today = safe_last(macd)
        macd_yesterday = macd.iloc[-2] if len(macd) >= 2 and pd.notna(macd.iloc[-2]) else 0.0
        diff_today = safe_last(diff)
        dea_today = safe_last(dea)
        improving = all(recent.iloc[i] >= recent.iloc[i - 1] for i in range(1, len(recent)))

        if macd_today > 0 and diff_today > dea_today and improving:
            return 12.0
        if macd_today > 0 and macd_today >= macd_yesterday:
            return 8.0
        if macd_today > 0:
            return 5.0
        if macd_today >= macd_yesterday:
            return 3.0
        return 0.0

    def _score_circ_mv(self, df):
        """P3: 流通市值分档(3分) - 中小盘加分."""
        if 'circ_mv' not in df.columns or len(df) < 1:
            return 1.5
        mv = safe_last(df['circ_mv'])
        if pd.isna(mv) or mv <= 0:
            return 1.5
        mv_yi = mv / 1e8  # 转亿元
        if mv_yi < 50:
            return 3.0  # 小盘
        if mv_yi < 200:
            return 2.0  # 中盘
        return 1.0  # 大盘

    def _score_fund_flow(self, df, lhb_codes=None):
        """P3: 资金流向(5分) - akshare龙虎榜数据+量价代理."""
        score = 1.5
        # 量价代理基础分
        if len(df) >= 6:
            close = df['close']
            volume = df['volume'] if 'volume' in df.columns else df.get('vol', pd.Series([0]*len(df)))
            ret_5d = (safe_last(close) / close.iloc[-6] - 1) if len(close) >= 6 else 0
            vol_ratio = safe_last(volume) / safe_last(volume.rolling(5).mean()) if safe_last(volume.rolling(5).mean()) > 0 else 1.0
            if ret_5d > 0.03 and vol_ratio > 1.2:
                score = 3.5
            elif ret_5d > 0 and vol_ratio > 1.0:
                score = 2.5
        # 龙虎榜加分（lhb_codes为当日龙虎榜上榜股票集合）
        if lhb_codes is not None:
            code = df.name if hasattr(df, 'name') else None
            if code and code in lhb_codes:
                score = min(score + 2.0, 5.0)  # 上榜+2分
        return score

    @staticmethod
    def _fetch_lhb_codes(date_str):
        """从akshare获取龙虎榜上榜股票代码集合."""
        try:
            import akshare as ak
            date_dash = date_str[:4] + '-' + date_str[4:6] + '-' + date_str[6:8]
            df = ak.stock_lhb_detail_em(start_date=date_dash, end_date=date_dash)
            if df is not None and len(df) > 0 and '代码' in df.columns:
                codes = set(df['代码'].astype(str).str.zfill(6))
                return codes
        except:
            pass
        return set()
        """P3: ATR Volatility (4分) - 低波动加分."""
        if len(df) < 15:
            return 0.0
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        atr_pct = safe_last(atr) / safe_last(close) if safe_last(close) > 0 else 0
        if atr_pct < 0.03:
            return 4.0
        if atr_pct < 0.06:
            return 3.0
        if atr_pct < 0.10:
            return 2.0
        return 1.0
