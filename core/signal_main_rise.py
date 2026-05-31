# coding=utf-8
"""主升浪买点信号 + 8D打分系统 + 板块热度分析（纯逻辑，无 QMT 依赖）"""

import os
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from core.utils import ema, ma, calc_macd, calc_cmf, calc_angle, safe_last, calc_rsi, calc_rating, calc_kdj


# ============================================================
#  参数常量
# ============================================================

N = 5
N1 = 10
N2 = 20
N3 = 60
M = 10
YANG_RATIO = 60
CMF_PERIOD = 20
CMF_THRESHOLD = 0.15
REQUIRED_BARS = 120
MIN_BARS = 60
SECTOR_HOT_TOP_N = 10
MARKET_INDEX_CODE = '000001.SH'
MARKET_MA20 = 20
MARKET_MA60 = 60


# ============================================================
#  选股信号
# ============================================================

def _filter_pit_breakout(df):
    """
    坑底急拉过滤。
    文档定义: 22日内最低价的最低值 → 坑区范围(当前最低≤坑底×1.16) → 2日内涨幅>4.5%则过滤
    Returns: True = 正常（不过滤）, False = 过滤（急拉坑底）
    """
    low_22 = df['low'].rolling(22).min()
    pit_zone = df['low'] <= low_22.shift(1) * 1.16
    rapid_rise = (df['close'] / df['close'].shift(2) - 1) > 0.045
    return ~(pit_zone & rapid_rise)


def check_buy(df):
    """主买点判断逻辑。返回 (bool, reason_str, buy_type)。"""
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    open_ = df['open'].astype(float)
    volume = df['volume'].astype(float)

    ma5 = ma(close, N)
    ma10 = ma(close, N1)
    ma20 = ma(close, N2)
    ma60 = ma(close, N3)

    s1 = ema(close, 10)
    s2 = ema(s1, 3)
    s3 = ema(s2, 3)
    s4 = ema(s3, 3)
    purple_band = ema(s4, 3)

    l1 = ema(close, 45)
    l2 = ema(l1, 3)
    l3 = ema(l2, 3)
    l4 = ema(l3, 3)
    red_band = ema(l4, 3)

    _, _, macd = calc_macd(close)
    macd_red_ok = (macd > 0) & (macd.shift(1) > 0) & (macd >= macd.shift(1))
    macd_green_ok = (macd < 0) & (macd.shift(1) < 0) & (macd > macd.shift(1))
    macd_first_green_to_red = (macd > 0) & (macd.shift(1) < 0)
    macd_satisfied = macd_red_ok | macd_green_ok | macd_first_green_to_red

    no_pit = _filter_pit_breakout(df)

    bullish_multi = (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)
    yang = close > open_

    # 买点1（回踩反包）
    pullback_hold = low >= ma5 * 0.98
    engulf = close > high.shift(1)
    buy_signal_1 = bullish_multi & pullback_hold & yang & engulf & macd_satisfied & no_pit

    # 买点2（趋势突破）
    # B2-1: 筹码密集（近似：90日价格CV ≤ 12%）
    price_std = close.rolling(90).std()
    price_mean = close.rolling(90).mean()
    chip_dense = (price_std / price_mean) <= 0.12

    # B2-2: 突破30日高点1%
    high_30 = high.rolling(30).max().shift(1)
    breakout = (close / high_30 > 1.01) & (close.shift(1) / high_30.shift(1) <= 1.01)

    # B2-4: 趋势确认（站在60日通道上轨）
    high_60 = high.rolling(60).max()
    trend_confirm = close > high_60 * 0.98

    # B2-5: 蓄势（5日内有2日涨跌幅绝对值<3%）
    pct_abs = close.pct_change().abs()
    accumulation = (pct_abs < 0.03).rolling(5).sum() >= 2

    # B2-6: 角度
    angle = calc_angle(ma5)
    angle_ok = angle >= 45

    buy_signal_2 = (chip_dense & breakout & bullish_multi & trend_confirm
                    & accumulation & angle_ok & yang & macd_satisfied & no_pit)

    buy = buy_signal_1 | buy_signal_2

    val = buy.iloc[-1] if len(buy) > 0 else False
    if isinstance(val, (pd.Series, np.ndarray)):
        val = bool(val.iloc[-1])
    else:
        val = bool(val)

    if not val:
        return False, "", None

    has_buy1 = bool(buy_signal_1.iloc[-1]) if len(buy_signal_1) > 0 else False
    has_buy2 = bool(buy_signal_2.iloc[-1]) if len(buy_signal_2) > 0 else False

    if has_buy1 and has_buy2:
        buy_type = 'both'
    elif has_buy1:
        buy_type = 'buy1'
    else:
        buy_type = 'buy2'

    reasons = []
    if has_buy1:
        reasons.append("买点1")
    if has_buy2:
        reasons.append("买点2")
    if macd_satisfied.iloc[-1]:
        reasons.append("MACD")

    return True, "+".join(reasons), buy_type


# ============================================================
#  8D 加权打分系统
# ============================================================

class ScoreCalculator8D:
    """
    8维加权打分系统
    权重: 基本面18% 估值12% 技术面18% 资金面15% 成长性15% 情绪面8% 风险7% 板块7%
    """

    ROE_TARGET = 15.0
    GM_TARGET = 70.0
    DEBT_RATIO_SAFE = 30.0
    DEBT_RATIO_MAX = 65.0
    PE_CENTER = 15.0
    PE_WIDTH = 12.0
    PB_CENTER = 1.5
    PB_WIDTH = 1.5
    CAP_CENTER = 80.0
    CAP_WIDTH = 70.0
    BIAS_CENTER = 4.0
    BIAS_WIDTH = 3.0
    POS60_CENTER = 65.0
    POS60_WIDTH = 30.0
    PCT_CHG_CENTER = 3.0
    PCT_CHG_WIDTH = 3.5
    TURNOVER_CENTER = 5.0
    TURNOVER_WIDTH = 4.0
    AMP_CENTER = 5.0
    AMP_WIDTH = 3.0
    AMP_RISK_LOW = 3.0
    AMP_RISK_HIGH = 10.0
    SHRINK_LOW = 0.5
    SHRINK_HIGH = 1.0
    POS60_RISK_LOW = 70.0
    POS60_RISK_HIGH = 95.0
    BIAS_RISK_LOW = 6.0
    BIAS_RISK_HIGH = 14.0
    LIMIT_UP_THRESHOLD = 0.095

    def __init__(self, C=None):
        self.C = C
        self._financial_cache = {}
        self._sector_bonus = {}
        self._instrument_cache = {}

    @staticmethod
    def _linear_map(val, low, high, score_low, score_high, cap=True):
        """线性映射: 将 val 从 [low, high] 映射到 [score_low, score_high]"""
        if val <= low:
            return float(score_low)
        if val >= high:
            return float(score_high) if cap else float(score_high + (val - high) / (high - low) * (score_high - score_low))
        ratio = (val - low) / (high - low)
        return float(score_low + ratio * (score_high - score_low))

    @staticmethod
    def _bell_map(val, center, width, score_max, score_min=0):
        """钟形映射: 越接近 center 得分越高"""
        dist = abs(val - center)
        if dist >= width:
            return float(score_min)
        ratio = 1 - dist / width
        return float(score_min + ratio * (score_max - score_min))

    @staticmethod
    def _sigmoid_map(val, center, steepness, score_min, score_max):
        """Sigmoid 映射: 在 center 附近平滑过渡"""
        try:
            ratio = 1 / (1 + math.exp(-steepness * (val - center)))
            return float(score_min + ratio * (score_max - score_min))
        except Exception:
            return float((score_min + score_max) / 2)

    def load_financial_data(self, stock_list):
        """批量加载财务数据到缓存。C 为 None 时跳过。"""
        if not self.C or not stock_list:
            return
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=730)).strftime('%Y%m%d')
        fields = [
            'ASHAREINCOME.operating_revenue',
            'ASHAREINCOME.operating_cost',
            'ASHAREINCOME.net_profit_incl_min_int_inc',
            'ASHAREBALANCESHEET.total_liabilities',
            'ASHAREBALANCESHEET.total_equity',
            'PERSHAREINDEX.du_return_on_equity',
            'PERSHAREINDEX.s_fa_eps_basic',
            'PERSHAREINDEX.gross_profit',
            'PERSHAREINDEX.gear_ratio',
        ]
        loaded = 0
        failed = 0
        for code in stock_list:
            try:
                df = self.C.get_financial_data(fields, [code], start, end, 'announce_time')
                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    continue
                if isinstance(df, pd.Series):
                    self._cache_financial_series(code, df)
                elif isinstance(df, pd.DataFrame):
                    self._cache_financial_series(code, df.iloc[-1])
                loaded += 1
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print("  [财务数据] %s 加载失败: %s" % (code, e))
                continue
        if loaded > 0:
            print("  [财务数据] 加载 %d/%d 只股票, %d 只失败" % (loaded, len(stock_list), failed))
        else:
            print("  [财务数据] 警告: 未加载到任何财务数据")

    def _cache_financial_series(self, code, series):
        """将单只股票的财务序列缓存为结构化字典"""
        try:
            def _g(k, default=0.0):
                v = series.get(k, default)
                if v is None or (isinstance(v, float) and (v != v)):
                    return default
                return float(v)
            revenue = _g('operating_revenue')
            cost = _g('operating_cost')
            net_profit = _g('net_profit_incl_min_int_inc')
            liabilities = _g('total_liabilities')
            equity = _g('total_equity')
            roe_raw = _g('du_return_on_equity')
            eps = _g('s_fa_eps_basic')
            gp_raw = _g('gross_profit')
            gr_raw = _g('gear_ratio')
            roe = roe_raw / 100.0 if roe_raw > 1 else roe_raw
            gross_margin = (revenue - cost) / revenue if revenue > 0 else 0.0
            if gross_margin == 0 and gp_raw > 0:
                gross_margin = gp_raw / 100.0 if gp_raw > 1 else gp_raw
            total_assets = liabilities + equity
            debt_ratio = liabilities / total_assets if total_assets > 0 else 0.0
            if debt_ratio == 0 and gr_raw > 0:
                debt_ratio = gr_raw / 100.0 if gr_raw > 1 else gr_raw
            self._financial_cache[code] = {
                'roe': roe, 'gross_margin': gross_margin,
                'net_profit': net_profit, 'debt_ratio': debt_ratio,
                'eps': eps, 'has_data': True,
            }
        except Exception as e:
            print('  [财务数据] %s 缓存异常: %s' % (code, e))
            self._financial_cache[code] = {'has_data': False}

    def update_sector_bonus(self, bonus_map):
        """更新板块加分映射"""
        if bonus_map:
            self._sector_bonus = bonus_map

    def load_sector_heat_from_file(self, path='D:/QMT_POOL/sector_heat.json'):
        """从JSON文件加载板块热度数据"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = f.read()
            data = json.loads(raw)
            if isinstance(data, dict):
                heat_map = data.get('stock_heat', data)
            else:
                heat_map = {}
            if heat_map:
                self._sector_bonus = heat_map
                print('  [热度] 加载 %d 只股票的板块热度加分' % len(heat_map))
            else:
                print('  [热度] 热度数据为空')
        except Exception as e:
            print('  [热度] 读取热度数据失败: %s' % e)

    def _fundamental_score(self, code):
        """基本面打分（满分18分）: ROE、毛利率、净利润、负债率"""
        fin = self._financial_cache.get(code, {})
        if not fin.get('has_data'):
            return 9.0
        score = 0.0
        roe = fin.get('roe', 0) * 100
        score += self._linear_map(roe, 0, self.ROE_TARGET, 0, 6, cap=True)
        gm = fin.get('gross_margin', 0) * 100
        score += self._linear_map(gm, 0, self.GM_TARGET, 0, 5, cap=True)
        np_val = fin.get('net_profit', 0)
        if np_val > 0:
            score += 3.0
            if np_val > 1e8:
                score += 1.0
        elif np_val < 0:
            score += max(4.0 + np_val / abs(np_val) * 0.5, 0)
        else:
            score += 2.0
        dr = fin.get('debt_ratio', 0.5) * 100
        score += self._linear_map(dr, self.DEBT_RATIO_SAFE, self.DEBT_RATIO_MAX, 3, 0, cap=True)
        return round(min(score, 18.0), 2)

    def _fetch_tencent_pe_pb(self, stock_code):
        """通过腾讯接口获取实时PE/PB和流通市值"""
        if not stock_code:
            return
        if stock_code in self._instrument_cache and self._instrument_cache[stock_code].get('pe'):
            return
        try:
            import re as _re
            import urllib.request
            code = stock_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
            prefix = 'sh' if code.startswith(('6', '9')) else 'sz'
            url = 'https://qt.gtimg.cn/q=' + prefix + code
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            resp = urllib.request.urlopen(req, timeout=5)
            raw = resp.read().decode('gbk')
            vals = raw.split('"')[1].split('~')
            pe_ttm = float(vals[39]) if len(vals) > 39 and vals[39] else None
            pb = float(vals[46]) if len(vals) > 46 and vals[46] else None
            circ_str = vals[44] if len(vals) > 44 and vals[44] else None
            circ_value = None
            if circ_str:
                m = _re.match(r'([\d.]+)', circ_str)
                if m:
                    num = float(m.group(1))
                    if '亿' in circ_str:
                        circ_value = num * 1e8
                    elif '万' in circ_str:
                        circ_value = num * 1e4
                    else:
                        circ_value = num
            if pe_ttm or pb or circ_value:
                self._instrument_cache[stock_code] = {
                    'pe': pe_ttm, 'pb': pb, 'circ_value': circ_value,
                }
        except Exception:
            pass

    def _valuation_score(self, stock_code, df, circ_value=None):
        """估值打分（满分12分）: PE钟形、PB钟形、流通市值"""
        fin = self._financial_cache.get(stock_code, {})
        inst = self._instrument_cache.get(stock_code, {})
        close = df['close'].astype(float)
        c = safe_last(close)
        score = 0.0
        eps = fin.get('eps', 0)
        if not inst.get('pe'):
            self._fetch_tencent_pe_pb(stock_code)
            inst = self._instrument_cache.get(stock_code, {})
        pe_inst = inst.get('pe', 0)
        pe_val = None
        if eps > 0 and c > 0:
            pe_val = c / eps
        elif pe_inst and pe_inst > 0:
            pe_val = pe_inst
        if pe_val and pe_val > 0:
            score += self._bell_map(pe_val, self.PE_CENTER, self.PE_WIDTH, 5, 0)
        else:
            score += 1.0
        roe = fin.get('roe', 0)
        pb_inst = inst.get('pb', 0)
        pb_val = None
        if roe > 0 and eps > 0:
            bvps = eps / roe
            if bvps > 0 and c > 0:
                pb_val = c / bvps
        elif pb_inst and pb_inst > 0:
            pb_val = pb_inst
        if pb_val and pb_val > 0:
            score += self._bell_map(pb_val, self.PB_CENTER, self.PB_WIDTH, 4, 0)
        else:
            score += 2.0
        cv = circ_value if (circ_value is not None and circ_value > 0) else inst.get('circ_value', 0)
        cap = (cv / 1e8) if (cv is not None and cv > 0) else 0
        if cap > 0:
            score += self._bell_map(cap, self.CAP_CENTER, self.CAP_WIDTH, 3, 0.5)
        else:
            score += 1.8
        return round(min(score, 12.0), 2)

    def _technical_score(self, df):
        """技术面打分（满分18分）: 均线排列、MACD、RSI、KDJ、位置百分比、乖离率"""
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        c = safe_last(close)
        m5 = safe_last(ma(close, 5))
        m10 = safe_last(ma(close, 10))
        m20 = safe_last(ma(close, 20))
        m60 = safe_last(ma(close, 60))
        score = 0.0
        if c > 0 and m5 > 0 and m10 > 0 and m20 > 0 and m60 > 0:
            if c > m5 > m10 > m20 > m60:
                base = 3.5
                gaps_ok = all([
                    1 <= (m5 - m10) / m10 * 100 <= 8,
                    1 <= (m10 - m20) / m20 * 100 <= 8,
                    1 <= (m20 - m60) / m60 * 100 <= 8,
                ])
                score += base + (2.5 if gaps_ok else 1.5)
            elif m5 > m10 > m20:
                score += self._linear_map((m5 - m20) / m20 * 100, 0, 5, 2, 5, cap=True)
            elif m5 > m10:
                score += self._linear_map((m5 - m10) / m10 * 100, 0, 3, 1, 2.5, cap=True)
            else:
                score += max(self._linear_map((m5 - m10) / m10 * 100, -2, 0, 0, 1), 0)
        else:
            score += 1.0
        dif, dea, macd_hist = calc_macd(close)
        d = safe_last(dif)
        de = safe_last(dea)
        mh = safe_last(macd_hist)
        if not np.isnan(d) and not np.isnan(de):
            if d > 0:
                score += 1.0
            if d > de:
                score += 1.0
            if mh > 0:
                score += 1.0
            if len(macd_hist) >= 2 and not pd.isna(macd_hist.iloc[-2]):
                if mh > float(macd_hist.iloc[-2]):
                    score += 1.0
        else:
            score += 1.5
        rsi_val = safe_last(calc_rsi(close))
        if not np.isnan(rsi_val):
            if 40 <= rsi_val <= 60:
                score += 2.0
            elif 60 < rsi_val <= 80:
                score += 2.5
            elif rsi_val > 80:
                score += 1.5
            elif 20 <= rsi_val < 40:
                score += 0.8
            else:
                score += 0.3
        else:
            score += 1.2
        k, d_kdj, j = calc_kdj(close, high, low)
        k_val = safe_last(k)
        d_val = safe_last(d_kdj)
        j_val = safe_last(j)
        if not np.isnan(k_val) and not np.isnan(d_val):
            if k_val > d_val:
                score += 0.8
            if 20 <= k_val <= 80:
                score += 0.5
            if j_val > 0:
                score += 0.7
        else:
            score += 0.8
        if len(close) >= 60:
            high_60 = close.iloc[-60:].max()
            low_60 = close.iloc[-60:].min()
            if high_60 > low_60:
                pos_pct = (c - low_60) / (high_60 - low_60) * 100
                score += self._bell_map(pos_pct, self.POS60_CENTER, self.POS60_WIDTH, 2, 0)
            else:
                score += 1.0
        else:
            score += 1.0
        if m20 > 0:
            bias = (c - m20) / m20 * 100
            score += self._bell_map(bias, self.BIAS_CENTER, self.BIAS_WIDTH, 1, 0)
        else:
            score += 0.5

        # 第8维度：买点信号
        try:
            signal_ok, _, buy_type = check_buy(df)
            buy_score = 0
            if signal_ok:
                if buy_type == 'both':
                    buy_score = 3     # 双买点 = 最高分
                elif buy_type == 'buy2':
                    buy_score = 2     # 趋势突破 = 高分
                elif buy_type == 'buy1':
                    buy_score = 1     # 回踩反包 = 基础分
            score += buy_score * 2    # 权重2分
        except Exception:
            pass

        return round(min(score, 18.0), 2)

    def _capital_score(self, df):
        """资金面打分（满分15分）: 量比、涨幅"""
        close = df['close'].astype(float)
        volume = df['volume'].astype(float)
        open_ = df['open'].astype(float)
        c = safe_last(close)
        v = safe_last(volume)
        o = safe_last(open_)
        score = 0.0
        vm5 = safe_last(ma(volume, 5))
        if vm5 > 0:
            vr = v / vm5
            if vr <= 1.0:
                score += self._linear_map(vr, 0.3, 1.0, 0, 3)
            elif vr <= 2.0:
                score += self._linear_map(vr, 1.0, 2.0, 3, 5)
            elif vr <= 3.0:
                score += self._linear_map(vr, 2.0, 3.0, 5, 4)
            else:
                score += max(4 - (vr - 3.0), 1.5)
        else:
            score += 2.0
        if o > 0:
            pct_chg = (c - o) / o * 100
        elif len(close) >= 2:
            prev_c = safe_last(close.shift(1))
            pct_chg = (c - prev_c) / prev_c * 100 if prev_c > 0 else 0
        else:
            pct_chg = 0
        score += self._bell_map(pct_chg, self.PCT_CHG_CENTER, self.PCT_CHG_WIDTH, 5, 0.5)
        score += self._bell_map(pct_chg, 2.5, 5.0, 3, 0.5)
        if vm5 > 0:
            vr = v / vm5
            score += self._linear_map(vr, 0.5, 1.8, 0, 2, cap=True)
        else:
            score += 1.0
        return round(min(score, 15.0), 2)

    def _growth_score(self, code, df):
        """成长性打分（满分15分）: 净利润规模、量比"""
        fin = self._financial_cache.get(code, {})
        volume = df['volume'].astype(float)
        close = df['close'].astype(float)
        c = safe_last(close)
        v = safe_last(volume)
        score = 0.0
        if fin.get('has_data'):
            np_val = fin.get('net_profit', 0)
            if np_val > 1e7:
                score += self._linear_map(np_val / 1e8, 0, 5, 6, 10, cap=True)
            elif np_val > 0:
                score += 4.0
            else:
                score += 1.0
        else:
            score += 5.0
        if c > 0 and v > 0:
            vm5 = safe_last(ma(volume, 5))
            if vm5 > 0:
                vr = v / vm5
                score += self._bell_map(vr, 1.5, 1.0, 5, 0.5)
            else:
                score += 2.0
        else:
            score += 2.0
        return round(min(score, 15.0), 2)

    def _sentiment_score(self, df):
        """情绪面打分（满分8分）: 涨幅、振幅、量比"""
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        open_ = df['open'].astype(float)
        volume = df['volume'].astype(float)
        c = safe_last(close)
        o = safe_last(open_)
        h = safe_last(high)
        l = safe_last(low)
        v = safe_last(volume)
        score = 0.0
        if o > 0:
            pct_chg = (c - o) / o * 100
        elif len(close) >= 2:
            prev_c = safe_last(close.shift(1))
            pct_chg = (c - prev_c) / prev_c * 100 if prev_c > 0 else 0
        else:
            pct_chg = 0
        score += self._bell_map(pct_chg, self.PCT_CHG_CENTER, self.PCT_CHG_WIDTH, 3, 0.2)
        if o > 0:
            amp = (h - l) / o * 100
            score += self._bell_map(amp, self.AMP_CENTER, self.AMP_WIDTH, 3, 0.2)
        vm5 = safe_last(ma(volume, 5))
        if vm5 > 0 and v > 0:
            vr = v / vm5
            score += self._bell_map(vr, 1.5, 1.0, 2, 0.2)
        else:
            score += 0.8
        return round(min(score, 8.0), 2)

    def _risk_score(self, df):
        """风险打分（满分7分，初始10分扣减）: 振幅、缩量、高位位置、乖离率"""
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        open_ = df['open'].astype(float)
        volume = df['volume'].astype(float)
        c = safe_last(close)
        o = safe_last(open_)
        h = safe_last(high)
        l = safe_last(low)
        v = safe_last(volume)
        m20 = safe_last(ma(close, 20))
        score = 10.0
        if o > 0:
            amp = (h - l) / o * 100
            score -= self._linear_map(amp, self.AMP_RISK_LOW, self.AMP_RISK_HIGH, 0, 2, cap=True)
        else:
            score -= 1.0
        prev_v = safe_last(volume.shift(1)) if len(volume) >= 2 else 0
        if prev_v > 0 and v > 0:
            vol_shrink = v / prev_v
            if vol_shrink < 0.7:
                score -= self._linear_map(vol_shrink, 0.3, 0.7, 2, 0, cap=True)
        else:
            score -= 0.5
        if len(close) >= 60:
            high_60 = close.iloc[-60:].max()
            low_60 = close.iloc[-60:].min()
            if high_60 > low_60:
                pos_pct = (c - low_60) / (high_60 - low_60) * 100
                score -= self._linear_map(pos_pct, self.POS60_RISK_LOW, self.POS60_RISK_HIGH, 0, 2, cap=True)
        else:
            score -= 0.5
        if m20 > 0:
            bias = abs((c - m20) / m20 * 100)
            score -= self._linear_map(bias, self.BIAS_RISK_LOW, self.BIAS_RISK_HIGH, 0, 1, cap=True)
        else:
            score -= 0.3
        return round(min(max(score - 3.0, 0), 7.0), 2)

    def _sector_score(self, stock_code, df):
        """板块打分（满分7分）: 量比、振幅、涨停强度、板块热度加分"""
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        open_ = df['open'].astype(float)
        volume = df['volume'].astype(float)
        c = safe_last(close)
        o = safe_last(open_)
        h = safe_last(high)
        l = safe_last(low)
        v = safe_last(volume)
        score = 0.0
        vm5 = safe_last(ma(volume, 5))
        if vm5 > 0 and v > 0:
            vr = v / vm5
            score += self._bell_map(vr, 1.8, 1.2, 2, 0.2)
        else:
            score += 0.8
        if o > 0:
            amp = (h - l) / o * 100
            score += self._bell_map(amp, 4.0, 3.0, 1, 0.1)
        if o > 0:
            pct_chg = (c - o) / o * 100
            if pct_chg >= 9.5:
                score += 2.0
            elif pct_chg >= 7.0:
                score += 1.5
            elif pct_chg >= 5.0:
                score += 1.0
            elif pct_chg >= 3.0:
                score += 0.5
        else:
            score += 0.5
        bonus = self._sector_bonus.get(stock_code, 0)
        if bonus > 0:
            score += self._linear_map(bonus, 1, 15, 0.3, 2, cap=True)
        else:
            score += 1.0
        return round(min(score, 7.0), 2)

    @staticmethod
    def calc_market_coeff(index_close, index_ma20, index_ma60):
        """计算市场系数: 多头排列1.0, 震荡0.85, 空头0.60"""
        if pd.isna(index_close) or pd.isna(index_ma20) or pd.isna(index_ma60):
            return 1.0
        if index_close > index_ma20 > index_ma60:
            return 1.0
        elif index_close > index_ma20 or (index_ma60 is not None and index_close > index_ma60):
            return 0.85
        else:
            return 0.60

    def total_score(self, df, stock_code=None, circ_value=None,
                    index_close=None, index_ma20=None, index_ma60=None):
        """8D总分汇总: 加权各维度得分，返回字典"""
        s1 = self._fundamental_score(stock_code) if stock_code else 9.0
        s2 = self._valuation_score(stock_code, df, circ_value) if stock_code else 6.0
        s3 = self._technical_score(df)
        s4 = self._capital_score(df)
        s5 = self._growth_score(stock_code, df) if stock_code else 7.5
        s6 = self._sentiment_score(df)
        s7 = self._risk_score(df)
        s8 = self._sector_score(stock_code, df) if stock_code else 3.5
        scores = [s1, s2, s3, s4, s5, s6, s7, s8]
        for i in range(len(scores)):
            if np.isnan(scores[i]):
                scores[i] = 0.0
        s1, s2, s3, s4, s5, s6, s7, s8 = scores
        raw_total = round(s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8, 2)
        coeff = self.calc_market_coeff(index_close, index_ma20, index_ma60)
        final_total = round(raw_total * coeff, 2)
        return {
            '基本面': s1, '估值面': s2, '技术面': s3, '资金面': s4,
            '成长面': s5, '情绪面': s6, '风险面': s7, '板块面': s8,
            'raw_total': raw_total, 'final_total': final_total,
            'market_coeff': coeff, 'rating': calc_rating(final_total),
        }


# ============================================================
#  板块热度（纯逻辑，仅文件加载，无 QMT API 调用）
# ============================================================

class SectorAnalyzer:
    """
    板块热度分析。
    仅支持从预计算文件加载；QMT API 调用由 adapter 层处理。
    """

    SECTOR_HEAT_FILE = 'D:/QMT_POOL/sector_heat.json'

    def __init__(self):
        self._bonus_cache = None
        self._cache_date = None

    def load_from_file(self, dt=None):
        """
        从预计算文件加载板块热度数据。
        返回: {stock_code: bonus_score, ...} 或 None（文件不存在/过期）
        """
        today = dt.strftime('%Y%m%d') if dt else datetime.now().strftime('%Y%m%d')
        if not os.path.exists(self.SECTOR_HEAT_FILE):
            return None

        try:
            with open(self.SECTOR_HEAT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            file_date = data.get('update_date', '')
            if file_date != today:
                return None

            stock_heat = data.get('stock_heat', {})
            sector_rank = data.get('sector_rank', [])

            print("  [板块] 从文件加载 %d 只股票的板块热度" % len(stock_heat))
            if sector_rank:
                print("  热门板块前5:")
                for sec in sector_rank[:5]:
                    print("    %s. %s %+.2f%%  涨%d跌%d" % (
                        sec['rank'], sec['name'], sec['pct'],
                        sec['up_count'], sec['down_count']
                    ))

            self._bonus_cache = stock_heat
            self._cache_date = today
            return stock_heat

        except Exception:
            return None

    def calc_top10(self, force_refresh=False, dt=None):
        """
        计算前10热门板块的股票加分映射。
        仅支持从文件加载（QMT API 版本在 adapter 层）。
        """
        today = dt.strftime('%Y%m%d') if dt else datetime.now().strftime('%Y%m%d')
        if self._bonus_cache is not None and self._cache_date == today and not force_refresh:
            return self._bonus_cache

        print("  [板块] 尝试从文件加载板块热度...")
        file_result = self.load_from_file(dt=dt)
        if file_result is not None:
            return file_result

        print("  [板块] 无板块数据文件，返回空")
        self._bonus_cache = {}
        self._cache_date = today
        return {}
