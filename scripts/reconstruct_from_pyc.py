# -*- coding: utf-8 -*-
"""Reconstruct risk_only_strategy.py from PYC bytecode"""
import marshal, dis, types, sys, os

PYC_PATH = '__pycache__/risk_only_strategy.cpython-310.pyc'
OUTPUT_PATH = 'risk_only_strategy.py'

with open(PYC_PATH, 'rb') as f:
    f.read(16)
    code = marshal.load(f)

# Execute to get runtime objects
ns = {}
exec(code, ns)

# Known Chinese replacements (from core/risk_manager.py and the original file)
CHINESE_MAP = {
    'HOLD': '持有',
    'REDUCE': '减仓',
    'CLEAR': '清仓',
    '预警层': '预警层',
    'warning_add': 'warning_add',
    '确认层': '确认层',
    '底线': '底线',
    '确认': '确认',
    '清仓': '清仓',
    # From original _signal methods
    'B1:爆量上影': 'B1:爆量上影',
    'B2:量价背离': 'B2:量价背离',
    'C2:MACD绿柱缩短': 'C2:MACD绿柱缩短',
    'KDJ死叉+MA5走平': 'KDJ死叉+MA5走平',
}

# Build reconstruction of module-level code
output_lines = []
output_lines.append('# -*- coding: gbk -*-')
output_lines.append('"""风控专用策略 — 只做卖出/减仓/预警/确认/清仓/移动止盈版本，不参与买入执行。"""')
output_lines.append('')
output_lines.append('import os')
output_lines.append('import json')
output_lines.append('import math')
output_lines.append('import numpy as np')
output_lines.append('import pandas as pd')
output_lines.append('from datetime import datetime')
output_lines.append('from enum import Enum')
output_lines.append('')

# Get module-level constants from the code object
module_consts = {}
# Extract global assignments from bytecode
instructions = list(dis.Bytecode(code))
for i, instr in enumerate(instructions):
    if instr.opname == 'STORE_NAME' and i >= 1:
        prev = instructions[i-1]
        if prev.opname == 'LOAD_CONST':
            module_consts[instr.argval] = prev.argval

# Utility functions
output_lines.extend([
    '',
    'def ema(series, n):',
    '    return series.ewm(span=n, adjust=False).mean()',
    '',
    'def ma(series, n):',
    '    return series.rolling(n).mean()',
    '',
    'def safe_last(series):',
    '    if series is None or len(series) == 0: return 0.0',
    '    val = series.iloc[-1]',
    '    return float(val) if not pd.isna(val) else 0.0',
    '',
    'def calc_macd(close):',
    '    diff = ema(close, 12) - ema(close, 26)',
    '    dea = ema(diff, 9)',
    '    macd = 2 * (diff - dea)',
    '    return diff, dea, macd',
    '',
    'def calc_atr(close, high, low, n=14):',
    '    """计算真实波幅 ATR"""',
    '    prev_close = close.shift(1)',
    '    tr1 = high - low',
    '    tr2 = (high - prev_close).abs()',
    '    tr3 = (low - prev_close).abs()',
    '    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)',
    '    atr = tr.ewm(span=n, adjust=False).mean()',
    '    return atr',
    '',
    'def calc_angle_simple(ma_series):',
    '    """计算均线角度（度）"""',
    '    if len(ma_series) < 3: return None',
    '    try:',
    '        prev = float(ma_series.iloc[-2])',
    '        curr = float(ma_series.iloc[-1])',
    '        if prev <= 0: return None',
    '        rad = np.arctan((curr - prev) / prev * 100)',
    '        return float(rad * 180 / np.pi)',
    '    except Exception: return None',
    '',
    'def calc_kdj(close, high, low, n=9, m1=3, m2=3):',
    '    L = low.rolling(n).min()',
    '    H = high.rolling(n).max()',
    '    rsv = (close - L) / (H - L) * 100',
    '    rsv = rsv.fillna(50)',
    '    k = rsv.ewm(alpha=1/m1, adjust=False).mean()',
    '    d = k.ewm(alpha=1/m2, adjust=False).mean()',
    '    j = 3 * k - 2 * d',
    '    return k.fillna(50), d.fillna(50), j.fillna(50)',
    '',
    'def detect_long_upper_shadow(high, close, open_, sr=0.5):',
    '    body_top = pd.concat([close, open_], axis=1).max(axis=1)',
    '    upper = high - body_top',
    '    total = high - pd.concat([close, open_], axis=1).min(axis=1)',
    '    total = total.replace(0, np.nan)',
    '    return (upper / total).fillna(0) >= sr',
    '',
    'def detect_volume_price_divergence(close, volume, lb=5, th=0.70):',
    '    if len(close) < 2: return False, 0.0',
    '    if close.iloc[-1] < close.iloc[-lb:].max(): return False, 0.0',
    '    r = volume.iloc[-1] / volume.iloc[-2] if volume.iloc[-2] > 0 else 1',
    '    return (True, float(r)) if r < th else (False, float(r))',
    '',
])

# Module-level constants
output_lines.extend([
    'BOTTOM_LINE_LOSS_PCT = -0.05',
    'BOTTOM_LINE_DAILY_DROP_PCT = -0.07',
    'WARNING_REDUCE_PCT = 0.30',
    'WARNING_ADD_REDUCE_PCT = 0.20',
    'VOLUME_RATIO_THRESHOLD = 1.5',
    'VOLUME_DIVERGE_THRESHOLD = 0.70',
    'MACD_SHORTEN_DAYS = 3',
    'MA5_SLOPE_FLAT_DEG = 15',
    'CONFIRM_REDUCE_PCT = 0.50',
    'CLEAR_MA20_DAYS = 3',
    'REBOUND_WINDOW_DAYS = 3',
    'TRAILING_BREAK_MA5_INTERVAL = 0.10',
    'TRAILING_DRAWDOWN_LO = 0.06',
    'TRAILING_DRAWDOWN_MID = 0.08',
    'TRAILING_DRAWDOWN_HI = 0.10',
    'CHANDELIER_ATR_MULTIPLE = 3',
    'NO_REENTRY_DAYS = 20',
    'CHANDELIER_MIN_LOOKBACK = 20',
    'KDJ_N = 9; KDJ_M1 = 3; KDJ_M2 = 3',
    'VOL_MA_PERIOD = 5; CHANDELIER_LOOKBACK = 20',
    '',
])

# Action Enum
output_lines.extend([
    '',
    'class Action(Enum):',
    '    HOLD = "持有"',
    '    REDUCE = "减仓"',
    '    CLEAR = "清仓"',
    '',
    'class SellDecision:',
    '    def __init__(self, action=Action.HOLD, code="", sell_pct=0.0, reason="",',
    '                 triggered_layer="", triggered_signals=None):',
    '        self.action = action',
    '        self.code = code',
    '        self.sell_pct = sell_pct',
    '        self.reason = reason',
    '        self.triggered_layer = triggered_layer',
    '        self.triggered_signals = triggered_signals or []',
    '    @staticmethod',
    '    def hold(): return SellDecision()',
    '    @staticmethod',
    '    def reduce(code, pct, reason, layer, signals=None):',
    '        return SellDecision(Action.REDUCE, code, pct, reason, layer, signals or [])',
    '    @staticmethod',
    '    def clear(code, reason, layer, signals=None):',
    '        return SellDecision(Action.CLEAR, code, 1.0, reason, layer, signals or [])',
    '',
    'class SellPositionState:',
    '    def __init__(self, code="", cost_price=0.0, current_shares=0, original_shares=0,',
    '                 highest_price=0.0, entry_date="",',
    '                 warning_reduced=False, warning_trigger_date="", warning_reason="",',
    '                 b1_needs_nextday_check=False, b1_trigger_date="", b1_additional_reduced=False,',
    '                 confirm_reduced=False, confirm_trigger_date="", confirm_reason="",',
    '                 cleared=False, cleared_date="", rebound_restored=False, reduction_volume=0):',
    '        self.code = code; self.cost_price = cost_price',
    '        self.current_shares = current_shares; self.original_shares = original_shares',
    '        self.highest_price = highest_price; self.entry_date = entry_date',
    '        self.warning_reduced = warning_reduced',
    '        self.warning_trigger_date = warning_trigger_date',
    '        self.warning_reason = warning_reason',
    '        self.b1_needs_nextday_check = b1_needs_nextday_check',
    '        self.b1_trigger_date = b1_trigger_date',
    '        self.b1_additional_reduced = b1_additional_reduced',
    '        self.confirm_reduced = confirm_reduced',
    '        self.confirm_trigger_date = confirm_trigger_date',
    '        self.confirm_reason = confirm_reason',
    '        self.cleared = cleared; self.cleared_date = cleared_date',
    '        self.rebound_restored = rebound_restored',
    '        self.reduction_volume = reduction_volume',
    '',
    'def get_trade_state_reason(state):',
    '    if state is None: return "无状态"',
    '    if state.cleared: return "已清仓(%s)" % (state.cleared_date or "?")',
    '    if state.confirm_reduced:',
    '        return "确认已减(%s)" % (state.confirm_reason or "?")',
    '    if state.warning_reduced:',
    '        return "预警已减(%s)" % (state.warning_reason or "?")',
    '    if state.b1_needs_nextday_check: return "B1触过预警(待次日确认)"',
    '    return "正常持有"',
    '',
])

# ============================================================
# SellStrategyEngine class - extracted from code objects
# ============================================================
engine_cls = ns['SellStrategyEngine']
engine_code = engine_cls.__init__.__code__  # placeholder to find __code__

output_lines.append('class SellStrategyEngine:')
output_lines.append('    def __init__(self, strategy_name, account_id,')
output_lines.append('                 state_file, is_intraday=True,')
output_lines.append('                 hard_stop_loss=BOTTOM_LINE_LOSS_PCT):')
output_lines.append('        self.strategy_name = strategy_name')
output_lines.append('        self.account_id = account_id')
output_lines.append('        self.state_file = state_file')
output_lines.append('        self.is_intraday = is_intraday')
output_lines.append('        self.hard_stop_loss = hard_stop_loss')
output_lines.append('        self._states = {}')
output_lines.append('')
output_lines.append('    def load_state(self):')
output_lines.append('        self._states = {}')
output_lines.append('        if not os.path.exists(self.state_file): return')
output_lines.append('        try:')
output_lines.append('            with open(self.state_file, "r", encoding="utf-8") as f:')
output_lines.append('                raw = json.load(f)')
output_lines.append('            for code, data in raw.items():')
output_lines.append('                ok = {k:v for k,v in data.items() if k in SellPositionState.__init__.__code__.co_varnames}')
output_lines.append('                self._states[code] = SellPositionState(**ok)')
output_lines.append('        except Exception: pass')
output_lines.append('')
output_lines.append('    def save_state(self):')
output_lines.append('        if not self._states: return')
output_lines.append('        try:')
output_lines.append('            d = os.path.dirname(self.state_file)')
output_lines.append('            if d: os.makedirs(d, exist_ok=True)')
output_lines.append('            with open(self.state_file, "w", encoding="utf-8") as f:')
output_lines.append('                json.dump({c:s.__dict__ for c,s in self._states.items()}, f, ensure_ascii=False, indent=2)')
output_lines.append('        except Exception: pass')
output_lines.append('')
output_lines.append('    def _get_state(self, code): return self._states.get(code)')
output_lines.append('    def _save_state(self, code, state):')
output_lines.append('        self._states[code] = state; self.save_state()')
output_lines.append('')
output_lines.append('    def is_reentry_allowed(self, code, today, df=None):')
output_lines.append('        st = self._states.get(code)')
output_lines.append('        if not st or not st.cleared or not st.cleared_date: return True')
output_lines.append('        c = datetime.strptime(st.cleared_date, "%Y%m%d")')
output_lines.append('        t = datetime.strptime(today, "%Y%m%d")')
output_lines.append('        if df is not None:')
output_lines.append('            dts = pd.to_datetime(df.index)')
output_lines.append('            ok = len(dts[(dts > pd.Timestamp(st.cleared_date)) & (dts <= pd.Timestamp(today))]) >= NO_REENTRY_DAYS')
output_lines.append('        else:')
output_lines.append('            ok = (t - c).days >= NO_REENTRY_DAYS + 8')
output_lines.append('        if ok: self._states.pop(code, None); self.save_state()')
output_lines.append('        return ok')
output_lines.append('')
output_lines.append('    def confirm_clear(self, code, today):')
output_lines.append('        st = self._get_state(code)')
output_lines.append('        if st: st.cleared = True; st.cleared_date = today; st.current_shares = 0; self._save_state(code, st)')
output_lines.append('')

# Generate evaluate method - complex, need to reconstruct from bytecode
output_lines.append('    def evaluate(self, today, holdings_dict, all_data, positions_data=None):')
output_lines.append('        if positions_data is None: positions_data = {}')
output_lines.append('        decisions = []')
output_lines.append('        if not holdings_dict: return decisions')
output_lines.append('        for code in list(holdings_dict.keys()):')
output_lines.append('            df = all_data.get(code)')
output_lines.append('            if df is None or len(df) < 30: continue')
output_lines.append('            state = self._get_state(code) or SellPositionState(code=code)')
output_lines.append('            close = df["close"].astype(float)')
output_lines.append('            curr = float(close.iloc[-1])')
output_lines.append('            pos = positions_data.get(code, {})')
output_lines.append('            if state.cleared and pos.get("volume", 0) > 0 and self.is_reentry_allowed(code, today, df):')
output_lines.append('                state = SellPositionState(code=code)')
output_lines.append('            cost = pos.get("cost", 0)')
output_lines.append('            if cost > 0: state.cost_price = cost')
output_lines.append('            state.current_shares = pos.get("can_use", 0)')
output_lines.append('            state.highest_price = max(holdings_dict.get(code, curr), curr)')
output_lines.append('            decision = self._evaluate_position(code, df, state, today)')
output_lines.append('            if decision.action != Action.HOLD:')
output_lines.append('                n = int(state.current_shares * decision.sell_pct)')
output_lines.append('                if n >= 100:')
output_lines.append('                    n = (n // 100) * 100')
output_lines.append('                    if decision.action == Action.REDUCE:')
output_lines.append('                        if decision.triggered_layer == "预警层":')
output_lines.append('                            state.warning_reduced = True; state.warning_trigger_date = today')
output_lines.append('                            state.warning_reason = decision.reason; state.reduction_volume += n')
output_lines.append('                        elif decision.triggered_layer == "warning_add":')
output_lines.append('                            state.b1_additional_reduced = True; state.b1_needs_nextday_check = False')
output_lines.append('                            state.reduction_volume += n')
output_lines.append('                        elif decision.triggered_layer == "确认层":')
output_lines.append('                            state.confirm_reduced = True; state.confirm_trigger_date = today')
output_lines.append('                            state.confirm_reason = decision.reason')
output_lines.append('                self._save_state(code, state)')
output_lines.append('                decisions.append((code, decision, n))')
output_lines.append('        return decisions')
output_lines.append('')

# check_rebound, apply_rebound_state
output_lines.append('    def check_rebound(self, code, df, state, today):')
output_lines.append('        if not state.warning_reduced or state.rebound_restored: return False, 0, ""')
output_lines.append('        if not state.warning_trigger_date: return False, 0, ""')
output_lines.append('        d = (datetime.strptime(today, "%Y%m%d") - datetime.strptime(state.warning_trigger_date, "%Y%m%d")).days')
output_lines.append('        if d < 1 or d > REBOUND_WINDOW_DAYS:')
output_lines.append('            if d > REBOUND_WINDOW_DAYS: state.rebound_restored = True')
output_lines.append('            return False, 0, ""')
output_lines.append('        cl = df["close"].astype(float); op = df["open"].astype(float); hi = df["high"].astype(float)')
output_lines.append('        p = float(cl.iloc[-1])')
output_lines.append('        if p <= float(cl.rolling(5).mean().iloc[-1]): return False, 0, ""')
output_lines.append('        if p <= float(op.iloc[-1]): return False, 0, ""')
output_lines.append('        if len(cl) >= 2 and p <= float(hi.iloc[-2]): return False, 0, ""')
output_lines.append('        return (True, state.reduction_volume, "反弹修复") if state.reduction_volume > 0 else (False, 0, "")')
output_lines.append('')
output_lines.append('    def apply_rebound_state(self, code, state):')
output_lines.append('        state.rebound_restored = True; state.warning_reduced = False')
output_lines.append('        state.warning_trigger_date = ""; state.warning_reason = ""')
output_lines.append('        state.b1_needs_nextday_check = False; state.b1_trigger_date = ""')
output_lines.append('        state.b1_additional_reduced = False; state.confirm_reduced = False')
output_lines.append('        state.confirm_trigger_date = ""; state.confirm_reason = ""')
output_lines.append('        state.cleared = False; state.cleared_date = ""; state.reduction_volume = 0')
output_lines.append('        self._save_state(code, state)')
output_lines.append('')

# _evaluate_position
output_lines.append('    def _evaluate_position(self, code, df, state, today):')
output_lines.append('        close = df["close"].astype(float); high = df["high"].astype(float)')
output_lines.append('        low = df["low"].astype(float); open_ = df["open"].astype(float)')
output_lines.append('        vol = df["volume"].astype(float)')
output_lines.append('        d = self._check_bottom_line(close, high, code, state, today)')
output_lines.append('        if d.action != Action.HOLD: return d')
output_lines.append('        if state.cleared: return SellDecision.hold()')
output_lines.append('        d = self._check_clear_level(close, high, low, vol, df, state, today)')
output_lines.append('        if d.action != Action.HOLD: return d')
output_lines.append('        if not state.warning_reduced:')
output_lines.append('            sigs = []')
output_lines.append('            b1, r1 = self._signal_explosive_volume(close, high, open_, vol)')
output_lines.append('            if b1: sigs.append(r1); state.b1_needs_nextday_check = True; state.b1_trigger_date = today')
output_lines.append('            if self._signal_volume_divergence(close, vol): sigs.append("B2:量价背离")')
output_lines.append('            if self._signal_macd_shortening(close): sigs.append("C2:MACD绿柱缩短")')
output_lines.append('            if self._signal_kdj_death(close, high, low): sigs.append("KDJ死叉+MA5走平")')
output_lines.append('            if sigs:')
output_lines.append('                state.warning_reduced = True; state.warning_trigger_date = today')
output_lines.append('                r = " | ".join(sigs); state.warning_reason = r')
output_lines.append('                self._save_state(code, state)')
output_lines.append('                return SellDecision.reduce(code, WARNING_REDUCE_PCT, r, "预警层", sigs)')
output_lines.append('        if state.warning_reduced and not state.confirm_reduced:')
output_lines.append('            if state.b1_needs_nextday_check and not state.b1_additional_reduced:')
output_lines.append('                bd = self._check_b1_nextday_additional(close, open_, code, state, today)')
output_lines.append('                if bd.action != Action.HOLD: return bd')
output_lines.append('            cd = self._check_confirm_level(close, high, low, open_, vol, df, state, today)')
output_lines.append('            if cd.action != Action.HOLD: return cd')
output_lines.append('        return SellDecision.hold()')
output_lines.append('')

# Signal methods
output_lines.append('    def _check_bottom_line(self, close, high, code, state, today):')
output_lines.append('        if len(close) < 2: return SellDecision.hold()')
output_lines.append('        p = float(close.iloc[-1]); sigs = []')
output_lines.append('        if state.cost_price > 0:')
output_lines.append('            l = (p - state.cost_price) / state.cost_price')
output_lines.append('            if l <= BOTTOM_LINE_LOSS_PCT:')
output_lines.append('                sigs.append("累计亏损%.1f%%" % (l*100))')
output_lines.append('                return SellDecision.clear(code, "硬止损:累计亏损%.1f%%" % (l*100), "底线层", sigs)')
output_lines.append('        pc = float(close.iloc[-2])')
output_lines.append('        if pc > 0:')
output_lines.append('            dd = (p - pc) / pc')
output_lines.append('            if dd <= BOTTOM_LINE_DAILY_DROP_PCT:')
output_lines.append('                sigs.append("当日跌停%.1f%%" % (dd*100))')
output_lines.append('                return SellDecision.clear(code, "硬止损:当日跌停%.1f%%" % (dd*100), "底线层", sigs)')
output_lines.append('        return SellDecision.hold()')
output_lines.append('')

output_lines.append('    def _check_b1_nextday_additional(self, close, open_, code, state, today):')
output_lines.append('        if not state.b1_trigger_date or today <= state.b1_trigger_date: return SellDecision.hold()')
output_lines.append('        if self._signal_b1_nextday_unrecovered(close, open_, state):')
output_lines.append('            return SellDecision.reduce(code, WARNING_ADD_REDUCE_PCT, "B1次日未修复", "warning_add", ["B1次日未修复"])')
output_lines.append('        return SellDecision.hold()')
output_lines.append('')

output_lines.append('    def _check_confirm_level(self, close, high, low, open_, volume, df, state, today):')
output_lines.append('        code = state.code if state.code else ""; sigs = []; ma10 = close.rolling(10).mean()')
output_lines.append('        if self._signal_break_ma10(close, ma10): sigs.append("A2:破10日线")')
output_lines.append('        if self._signal_high_long_shadow(high, close, open_): sigs.append("C1:高位长上影")')
output_lines.append('        if self._signal_high_volume_negative(close, open_, volume): sigs.append("B3:高位放量阴")')
output_lines.append('        if sigs: return SellDecision.reduce(code, CONFIRM_REDUCE_PCT, " | ".join(sigs), "确认层", sigs)')
output_lines.append('        return SellDecision.hold()')
output_lines.append('')

output_lines.append('    def _check_clear_level(self, close, high, low, volume, df, state, today):')
output_lines.append('        code = state.code if state.code else ""')
output_lines.append('        if not code: return SellDecision.hold()')
output_lines.append('        ma20 = close.rolling(20).mean(); sigs = []')
output_lines.append('        if self._signal_break_ma20_3days(close, ma20): sigs.append("A3:破20日线")')
output_lines.append('        if self._signal_break_highest_low(close, high, low): sigs.append("C3:跌破起涨低点")')
output_lines.append('        if len(sigs) >= 3:')
output_lines.append('            return SellDecision.clear(code, "清仓信号过多: " + " | ".join(sigs), "清仓层", sigs)')
output_lines.append('        if not (state.warning_reduced and not state.confirm_reduced):')
output_lines.append('            if self._check_trailing_profit(close, high, low, state): sigs.append("移动止盈")')
output_lines.append('        if sigs: return SellDecision.clear(code, " | ".join(sigs), "清仓层", sigs)')
output_lines.append('        return SellDecision.hold()')
output_lines.append('')

output_lines.append('    def _check_trailing_profit(self, close, high, low, state):')
output_lines.append('        if state.cost_price <= 0 or state.highest_price <= 0: return False')
output_lines.append('        p = float(close.iloc[-1])')
output_lines.append('        profit = (p - state.cost_price) / state.cost_price')
output_lines.append('        dd = (state.highest_price - p) / state.highest_price')
output_lines.append('        if profit <= 0: return False')
output_lines.append('        if profit < TRAILING_BREAK_MA5_INTERVAL:')
output_lines.append('            return p < float(close.rolling(5).mean().iloc[-1])')
output_lines.append('        if profit < 0.20: return dd >= TRAILING_DRAWDOWN_LO')
output_lines.append('        if profit < 0.30: return dd >= TRAILING_DRAWDOWN_MID')
output_lines.append('        if dd >= TRAILING_DRAWDOWN_HI: return True')
output_lines.append('        if len(close) >= CHANDELIER_LOOKBACK:')
output_lines.append('            atr = calc_atr(close, high, low, n=14)')
output_lines.append('            lev = state.highest_price - CHANDELIER_ATR_MULTIPLE * float(atr.iloc[-1])')
output_lines.append('            if p <= lev: return True')
output_lines.append('        return False')
output_lines.append('')

# diagnose_position
output_lines.append('    def diagnose_position(self, code, df, cost_price, current_price, highest_price):')
output_lines.append('        state = self._states.get(code)')
output_lines.append('        close = df["close"].astype(float)')
output_lines.append('        high = df["high"].astype(float)')
output_lines.append('        low = df["low"].astype(float)')
output_lines.append('        open_ = df["open"].astype(float)')
output_lines.append('        vol = df["volume"].astype(float)')
output_lines.append('')
output_lines.append('        profit_pct = (current_price - cost_price) / cost_price * 100 if cost_price > 0 else 0.0')
output_lines.append('')
output_lines.append('        if state is None:')
output_lines.append('            status = "未跟踪"')
output_lines.append('        elif state.cleared:')
output_lines.append('            status = "已清仓(%s)" % state.cleared_date')
output_lines.append('        elif state.confirm_reduced:')
output_lines.append('            status = "确认已减仓"')
output_lines.append('        elif state.warning_reduced:')
output_lines.append('            status = "预警已减仓"')
output_lines.append('        else:')
output_lines.append('            status = "正常持有"')
output_lines.append('')
output_lines.append('        if state and state.cleared:')
output_lines.append('            current_layer = "清仓层"')
output_lines.append('        elif state and state.confirm_reduced:')
output_lines.append('            current_layer = "确认层"')
output_lines.append('        elif state and state.warning_reduced:')
output_lines.append('            current_layer = "预警层"')
output_lines.append('        else:')
output_lines.append('            current_layer = "正常"')
output_lines.append('')
output_lines.append('        layers = {"bottom_line": {}, "warning": {}, "confirm": {}, "clear": {}, "trailing": {}}')
output_lines.append('')
output_lines.append('        # 底线层')
output_lines.append('        if len(close) >= 2 and cost_price > 0:')
output_lines.append('            curr = float(close.iloc[-1])')
output_lines.append('            loss_pct = (curr - cost_price) / cost_price * 100')
output_lines.append('            layers["bottom_line"]["累计亏损"] = {"triggered": loss_pct <= BOTTOM_LINE_LOSS_PCT * 100, "value": "%.1f%%" % loss_pct}')
output_lines.append('            prev_close = float(close.iloc[-2])')
output_lines.append('            if prev_close > 0:')
output_lines.append('                daily_drop = (curr - prev_close) / prev_close * 100')
output_lines.append('                layers["bottom_line"]["当日暴跌"] = {"triggered": daily_drop <= BOTTOM_LINE_DAILY_DROP_PCT * 100, "value": "%.1f%%" % daily_drop}')
output_lines.append('        else:')
output_lines.append('            layers["bottom_line"]["累计亏损"] = {"triggered": False, "value": "--"}')
output_lines.append('            layers["bottom_line"]["当日暴跌"] = {"triggered": False, "value": "--"}')
output_lines.append('')
output_lines.append('        # 预警层')
output_lines.append('        b1_t = False')
output_lines.append('        b1_ratio = ""')
output_lines.append('        if len(vol) >= 6 and len(close) >= 6:')
output_lines.append('            v5 = vol.rolling(5).mean()')
output_lines.append('            cv = float(vol.iloc[-1])')
output_lines.append('            av = float(v5.iloc[-1])')
output_lines.append('            if av > 0:')
output_lines.append('                ratio = cv / av')
output_lines.append('                if ratio >= VOLUME_RATIO_THRESHOLD:')
output_lines.append('                    sh = detect_long_upper_shadow(high, close, open_)')
output_lines.append('                    if sh.iloc[-1]:')
output_lines.append('                        b1_t = True')
output_lines.append('                b1_ratio = "%.1fx" % ratio')
output_lines.append('        layers["warning"]["B1爆量"] = {"triggered": b1_t, "value": b1_ratio}')
output_lines.append('')
output_lines.append('        b2_t, b2_r = detect_volume_price_divergence(close, vol)')
output_lines.append('        b2_val = "%.1fx" % b2_r if b2_r else ""')
output_lines.append('        layers["warning"]["B2背离"] = {"triggered": b2_t, "value": b2_val}')
output_lines.append('')
output_lines.append('        c2_t = self._signal_macd_shortening(close)')
output_lines.append('        layers["warning"]["C2绿缩"] = {"triggered": c2_t, "value": ""}')
output_lines.append('')
output_lines.append('        kdj_t = self._signal_kdj_death(close, high, low)')
output_lines.append('        layers["warning"]["KDJ死叉"] = {"triggered": kdj_t, "value": ""}')
output_lines.append('')
output_lines.append('        # 确认层')
output_lines.append('        ma10 = close.rolling(10).mean()')
output_lines.append('        a2_t = self._signal_break_ma10(close, ma10)')
output_lines.append('        a2_val = ""')
output_lines.append('        if a2_t and len(close) >= 11:')
output_lines.append('            a2_val = "%.1f%%" % ((float(ma10.iloc[-1]) - float(close.iloc[-1])) / float(ma10.iloc[-1]) * 100)')
output_lines.append('        layers["confirm"]["A2破10"] = {"triggered": a2_t, "value": a2_val}')
output_lines.append('')
output_lines.append('        c1_t = self._signal_high_long_shadow(high, close, open_)')
output_lines.append('        layers["confirm"]["C1上影"] = {"triggered": c1_t, "value": ""}')
output_lines.append('')
output_lines.append('        b3_t = self._signal_high_volume_negative(close, open_, vol)')
output_lines.append('        layers["confirm"]["B3放量"] = {"triggered": b3_t, "value": ""}')
output_lines.append('')
output_lines.append('        # 清仓层')
output_lines.append('        ma20 = close.rolling(20).mean()')
output_lines.append('        a3_t = self._signal_break_ma20_3days(close, ma20)')
output_lines.append('        layers["clear"]["A3破20"] = {"triggered": a3_t, "value": ""}')
output_lines.append('')
output_lines.append('        c3_t = self._signal_break_highest_low(close, high, low)')
output_lines.append('        layers["clear"]["C3破低"] = {"triggered": c3_t, "value": ""}')
output_lines.append('')
output_lines.append('        # 移动止盈')
output_lines.append('        trailing_t = False')
output_lines.append('        trailing_detail = ""')
output_lines.append('        if cost_price > 0 and highest_price > 0:')
output_lines.append('            profit_r = (current_price - cost_price) / cost_price')
output_lines.append('            drawdown_pct = (highest_price - current_price) / highest_price * 100')
output_lines.append('            ppv = profit_r * 100')
output_lines.append('            if ppv > 0:')
output_lines.append('                if ppv < TRAILING_BREAK_MA5_INTERVAL * 100:')
output_lines.append('                    m5 = float(close.rolling(5).mean().iloc[-1]) if len(close) >= 5 else 0')
output_lines.append('                    below = current_price < m5')
output_lines.append('                    trailing_detail = "盈利%+.1f%%<%d%%, %s" % (ppv, int(TRAILING_BREAK_MA5_INTERVAL * 100), "跌破MA5" if below else "未破MA5")')
output_lines.append('                    trailing_t = below')
output_lines.append('                else:')
output_lines.append('                    trailing_detail = "盈利%+.1f%%, 回撤%.1f%%" % (ppv, drawdown_pct)')
output_lines.append('                    if ppv < 20:')
output_lines.append('                        trailing_t = drawdown_pct >= TRAILING_DRAWDOWN_LO * 100')
output_lines.append('                    elif ppv < 30:')
output_lines.append('                        trailing_t = drawdown_pct >= TRAILING_DRAWDOWN_MID * 100')
output_lines.append('                    else:')
output_lines.append('                        trailing_t = drawdown_pct >= TRAILING_DRAWDOWN_HI * 100')
output_lines.append('        layers["trailing"]["移动止盈"] = {"triggered": trailing_t, "detail": trailing_detail}')
output_lines.append('')
output_lines.append('        return {"code": code, "status": status, "cost_price": cost_price,')
output_lines.append('                "current_price": current_price, "profit_pct": profit_pct,')
output_lines.append('                "highest_price": highest_price, "current_layer": current_layer,')
output_lines.append('                "layers": layers}')
output_lines.append('')

# Signal detection methods
signal_methods = {
    '_signal_break_ma5': 'if len(close) < 6: return False\n        return bool(close.iloc[-1] < close.rolling(5).mean().iloc[-1])',
    '_signal_break_ma10': 'if len(close) < 11: return False\n        return bool(close.iloc[-1] < ma10.iloc[-1])',
    '_signal_break_ma20_3days': 'if len(close) < 24: return False\n        if close.iloc[-1] >= ma20.iloc[-1]: return False\n        n = 0\n        for i in range(min(CLEAR_MA20_DAYS, len(close)-1)):\n            if close.iloc[-1-i] < ma20.iloc[-1-i]: n += 1\n            else: break\n        return n >= CLEAR_MA20_DAYS',
    '_signal_explosive_volume': 'if len(vol) < 6: return False, ""\n        v5 = vol.rolling(5).mean(); cv = float(vol.iloc[-1]); av = float(v5.iloc[-1])\n        if av <= 0 or cv/av < VOLUME_RATIO_THRESHOLD: return False, ""\n        sh = detect_long_upper_shadow(high, close, open_)\n        if not sh.iloc[-1]: return False, ""\n        return True, "B1:爆量上影(%.1f倍)" % (cv/av)',
    '_signal_b1_nextday_unrecovered': 'if len(close) < 2: return False\n        p = float(close.iloc[-1]); m5 = float(close.rolling(5).mean().iloc[-1])\n        if p > m5 and p > float(open_.iloc[-1]):\n            state.b1_needs_nextday_check = False; state.b1_additional_reduced = False; return False\n        return True',
    '_signal_volume_divergence': 'r, _ = detect_volume_price_divergence(close, vol); return r',
    '_signal_macd_shortening': 'if len(close) < MACD_SHORTEN_DAYS + 26: return False\n        _, _, bar = self._calc_macd_safe(close)\n        if bar is None or len(bar) < MACD_SHORTEN_DAYS + 1: return False\n        for i in range(MACD_SHORTEN_DAYS + 1):\n            if pd.isna(bar.iloc[-1-i]): return False\n        if bar.iloc[-1] <= 0: return False\n        for i in range(MACD_SHORTEN_DAYS):\n            if bar.iloc[-1-i] >= bar.iloc[-2-i]: return False\n        return True',
    '_signal_kdj_death': 'if len(close) < 15: return False\n        m5 = close.rolling(5).mean()\n        if len(m5) < 3: return False\n        a = calc_angle_simple(m5)\n        if a is None or abs(a) > MA5_SLOPE_FLAT_DEG: return False\n        k, d, j = calc_kdj(close, high, low)\n        if len(k) < 3 or len(d) < 3: return False\n        if pd.isna(k.iloc[-1]) or pd.isna(d.iloc[-1]) or pd.isna(k.iloc[-2]) or pd.isna(d.iloc[-2]): return False\n        return bool(k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2])',
    '_signal_high_long_shadow': 'if len(close) < 10: return False\n        rh = float(close.iloc[-5:].max()); cp = float(close.iloc[-10])\n        if cp <= 0 or (rh-cp)/cp < 0.05: return False\n        return bool(detect_long_upper_shadow(high, close, open_).iloc[-1])',
    '_signal_high_volume_negative': 'if len(close) < 10: return False\n        if len(close) >= 20:\n            if float(close.iloc[-5:].max()) < float(close.iloc[-20:].max()) * 0.95: return False\n        if close.iloc[-1] >= open_.iloc[-1]: return False\n        if len(vol) >= 6:\n            if float(vol.iloc[-1]) < float(vol.rolling(5).mean().iloc[-1]) * VOLUME_RATIO_THRESHOLD: return False\n        return True',
    '_signal_break_highest_low': 'if len(high) < 30: return False\n        r = high.iloc[-30:]; hv = r.max(); hp = 0\n        for i in range(len(r)):\n            if r.iloc[i] >= hv: hp = i; break\n        return float(close.iloc[-1]) < float(low.iloc[-30:].iloc[hp])',
    '_calc_macd_safe': 'if len(close) < 26: return None, None, None\n        try:\n            e12 = close.ewm(span=12, adjust=False).mean()\n            e26 = close.ewm(span=26, adjust=False).mean()\n            d = e12 - e26; de = d.ewm(span=9, adjust=False).mean()\n            return d, de, 2*(d-de)\n        except Exception: return None, None, None',
}

for method_name, method_body in signal_methods.items():
    output_lines.append('    def ' + method_name + '(self, close, high=None, low=None, open_=None, vol=None, ma10=None, ma20=None, state=None):')
    lines = method_body.split('\n')
    for l in lines:
        if l.strip():
            output_lines.append('        ' + l.strip())
        else:
            output_lines.append('')
    output_lines.append('')

# Restructure signal methods to have flexible signatures
# Actually, let me fix the signal methods section by removing the wrong auto-generated ones
# and adding the correct ones

# Hmm, the signal methods above are incorrect because I used a template approach.
# Let me reconsider this approach.

print('Reconstruction in progress... need to fix signal methods')
print(f'Current output: {len(output_lines)} lines')

# Write what we have so far for inspection
with open('risk_only_strategy_reconstructed.py', 'w', encoding='gbk') as f:
    f.write('\n'.join(output_lines))

print('Written partial reconstruction')
