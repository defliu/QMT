# coding: utf-8
"""score_universe wrapper over core.scoring.dimension6plus2.

Maps reader DataFrame schema (vol) -> scorer DataFrame schema (volume).
Outputs records matching 03_interface_freeze.md section 6 diagnostics.scores.

3.6-safe constraints:
  - no dict[str, ...] / list[str] annotations
  - no str | None unions
  - no walrus, no match/case, no dataclass
  - no f-strings (use % formatting)

Purity constraints (03 section 1):
  - no IO / network
  - no xtquant / passorder / ContextInfo imports
  - sector_heat_path explicitly None to avoid D:/QMT_POOL filesystem read
"""

import logging

from core.scoring.dimension6plus2 import ScoreCalculator6Plus2
from core.utils import calc_bias, ma, safe_last


log = logging.getLogger(__name__)


def _rename_vol_to_volume(df):
    """Reader emits 'vol'; scorer expects 'volume'. Rename without mutating input."""
    if df is None:
        return df
    cols = df.columns
    if "volume" in cols:
        return df
    if "vol" in cols:
        return df.rename(columns={"vol": "volume"})
    return df  # let scorer raise if neither present


def _compute_bias5(df):
    """bias5 = (close[-1] / MA5(close) - 1) * 100, percentage units."""
    if df is None or len(df) < 5:
        return 0.0
    ma5 = ma(df["close"], 5)
    last_close = safe_last(df["close"])
    last_ma5 = safe_last(ma5)
    if last_ma5 is None or last_ma5 == 0:
        return 0.0
    return float(calc_bias(last_close, last_ma5))


def score_universe(
    market_window,
    sector_heat_mode="zero",
    aux_data=None,
    return_warnings=False,
):
    """Score every code in market_window per 03 section 6 diagnostics.scores schema.

    Args:
        market_window: dict[code(str), DataFrame[date, open, high, low, close, vol, amount]]
        sector_heat_mode: only "zero" supported in v0.2 (03 section 4 constraint 2)
        aux_data: dict per 03 section 5 (fundamentals/sector_map/sector_heat/...)
        return_warnings: if True, return (records, warnings) tuple

    Returns:
        list of dict, each containing the 12 keys from 03 section 6:
          code, score_total, score_breakout, score_trend, score_consolidation,
          score_volumeprice, score_macd, score_valuation, score_sentiment,
          score_sector, bias5, signal
        signal is fixed to "hold" at this layer; decision layer (Task 2.3) rewrites.
    """
    if sector_heat_mode != "zero":
        raise NotImplementedError(
            "sector_heat_mode=%r not supported in v0.2 (only 'zero')" % (sector_heat_mode,)
        )

    aux = aux_data or {}
    warnings_list = []

    # ---- Filter & rename columns ----
    pool_dict = {}
    for code, df in (market_window or {}).items():
        if df is None or len(df) < 60:
            msg = "insufficient data for %s" % code
            warnings_list.append(msg)
            log.warning(msg)
            continue
        pool_dict[code] = _rename_vol_to_volume(df)

    if not pool_dict:
        if return_warnings:
            return [], warnings_list
        return []

    # ---- Score (sector_heat_path=None -> no IO) ----
    scorer = ScoreCalculator6Plus2(sector_heat_path=None)
    fundamentals = aux.get("fundamentals")
    if fundamentals is None:
        msg = "fundamentals not available; valuation uses scorer default"
        warnings_list.append(msg)
        log.warning(msg)

    df_scores = scorer.score_pool(pool_dict, fundamentals=fundamentals)

    # ---- Assemble records per 03 section 6 schema ----
    records = []
    for code in df_scores.index:
        row = df_scores.loc[code]
        rec = {
            "code":                code,
            "score_breakout":      float(row["score_breakout"]),
            "score_trend":         float(row["score_trend"]),
            "score_consolidation": float(row["score_consolidation"]),
            "score_volumeprice":   float(row["score_volumeprice"]),
            "score_macd":          float(row["score_macd"]),
            "score_valuation":     float(row["score_valuation"]),
            "score_sentiment":     float(row["score_sentiment"]),
            "score_sector":        float(row["score_sector"]),
            "score_total":         float(row["score_total"]),
            "bias5":               _compute_bias5(pool_dict[code]),
            "signal":              "hold",
        }

        # zero mode: force sector=0 and recompute total (03 section 6 example)
        if sector_heat_mode == "zero":
            rec["score_total"] = rec["score_total"] - rec["score_sector"]
            rec["score_sector"] = 0.0

        records.append(rec)

    if return_warnings:
        return records, warnings_list
    return records
