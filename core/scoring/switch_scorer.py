# coding=utf-8
"""
Round-robin scorer switcher between ScoreCalculator8D and ScoreCalculator6Plus2.

Modes:
  - '6plus2' (default): always uses ScoreCalculator6Plus2
  - '8d': always uses ScoreCalculator8D
  - 'round_robin': alternates by trading date (even day → 6+2, odd day → 8D)

Usage:
    from core.scoring.switch_scorer import SwitchScorer
    scorer = SwitchScorer(mode='6plus2')
    result = scorer.score_single(stock_code='000001.SZ', df=df)
    print(scorer.active_name)  # 'ScoreCalculator6Plus2'
"""

from datetime import datetime

from core.signal_main_rise import ScoreCalculator8D
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2


DEFAULT_SECTOR_HEAT = 'D:/QMT_POOL/sector_heat.json'


class SwitchScorer:
    """Wrapper that delegates to 8D or 6+2 scorer with configurable switching."""

    def __init__(self, mode='6plus2', C=None,
                 sector_heat_path=DEFAULT_SECTOR_HEAT):
        """
        Args:
            mode: '6plus2' | '8d' | 'round_robin'
            C: QMT ContextInfo (required only for 8D mode)
            sector_heat_path: path to sector_heat.json (6+2 scorer)
        """
        if mode not in ('6plus2', '8d', 'round_robin'):
            raise ValueError("mode must be '6plus2', '8d', or 'round_robin'")

        self.mode = mode
        self._scorer_8d = None
        self._scorer_6plus2 = None
        self._C = C
        self._sector_heat_path = sector_heat_path

    # -- property: name of the active scorer --
    @property
    def active_name(self):
        return type(self._resolve()).__name__

    # -- public scoring interface (unified) --
    def score_single(self, stock_code, df,
                     circ_value=None,
                     index_close=None, index_ma20=None, index_ma60=None,
                     dynamic_pe=None, static_pe=None,
                     pool_5d_returns=None):
        """Unified scoring entry point — routes to whichever scorer is active.

        Returns dict with keys matching 6+2 format:
          score_breakout, score_trend, score_consolidation,
          score_volumeprice, score_macd, score_valuation,
          score_sentiment, score_sector, score_total
        """
        scorer = self._resolve()

        if isinstance(scorer, ScoreCalculator6Plus2):
            return scorer.score_single(
                stock_code=stock_code, df=df,
                dynamic_pe=dynamic_pe, static_pe=static_pe,
                pool_5d_returns=pool_5d_returns,
            )
        else:
            # ScoreCalculator8D
            raw = scorer.total_score(
                df=df, stock_code=stock_code,
                circ_value=circ_value,
                index_close=index_close,
                index_ma20=index_ma20,
                index_ma60=index_ma60,
            )
            return self._convert_8d_to_6plus2(raw)

    def update_sector_bonus(self, bonus_map):
        """Forward sector bonus to whichever scorer is active."""
        scorer = self._resolve()
        if isinstance(scorer, ScoreCalculator6Plus2):
            scorer.update_sector_bonus(bonus_map)
        elif isinstance(scorer, ScoreCalculator8D):
            scorer.update_sector_bonus(bonus_map)

    # -- internal --
    def _resolve(self):
        """Return the active scorer instance (lazy-init)."""
        if self.mode == 'round_robin':
            day = datetime.now().day
            use_8d = (day % 2 == 1)
        else:
            use_8d = (self.mode == '8d')

        if use_8d:
            if self._scorer_8d is None:
                self._scorer_8d = ScoreCalculator8D(self._C)
            return self._scorer_8d
        else:
            if self._scorer_6plus2 is None:
                self._scorer_6plus2 = ScoreCalculator6Plus2(
                    sector_heat_path=self._sector_heat_path
                )
            return self._scorer_6plus2

    @staticmethod
    def _convert_8d_to_6plus2(raw):
        """Map 8D result dict → 6+2 dimension keys."""
        return {
            'score_breakout': raw.get('d1_breakthrough', 0),
            'score_trend': raw.get('d2_deviation', 0),
            'score_consolidation': raw.get('d3_ma5_hold', 0),
            'score_volumeprice': raw.get('d4_volume', 0),
            'score_macd': raw.get('d5_macd', 0),
            'score_valuation': raw.get('估值面', 0),
            'score_sentiment': raw.get('情绪面', 0),
            'score_sector': raw.get('板块面', 0),
            'score_total': raw.get('final_total', 0),
        }
