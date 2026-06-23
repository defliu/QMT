# coding=utf-8
"""四层卖出策略引擎 — 底/预警/确认/清仓。纯决策逻辑，无交易执行。"""

import os
import json
import pandas as pd
from datetime import datetime
from enum import Enum

from core.utils import calc_atr, calc_angle_simple, calc_kdj, detect_long_upper_shadow
from core.utils import detect_volume_price_divergence


# ============================================================
#  策略参数
# ============================================================

# ---- 底线层 ----
BOTTOM_LINE_LOSS_PCT = -0.05
BOTTOM_LINE_DAILY_DROP_PCT = -0.07

# ---- 预警层 ----
WARNING_REDUCE_PCT = 0.30
WARNING_ADD_REDUCE_PCT = 0.20
VOLUME_RATIO_THRESHOLD = 1.5
VOLUME_DIVERGE_THRESHOLD = 0.70
MACD_SHORTEN_DAYS = 3
MA5_SLOPE_FLAT_DEG = 15

# ---- 确认层 ----
CONFIRM_REDUCE_PCT = 0.50

# ---- 清仓层 ----
CLEAR_MA20_DAYS = 3

# ---- 反弹检测 ----
REBOUND_WINDOW_DAYS = 3

# ---- 移动止盈 ATR 自适应（V1.1）----
TRAILING_BREAK_MA5_INTERVAL = 0.10
TRAILING_ATR_N = 2.5              # 动态阈值 ATR 倍数
TRAILING_DRAWDOWN_FLOOR = 0.06    # 回撤阈值下限（替代旧 LO，语义合并）
TRAILING_DRAWDOWN_CAP = 0.15      # 回撤阈值上限
CHANDELIER_ATR_MULTIPLE = 3

# ---- 纪律 ----
NO_REENTRY_DAYS = 20
CHANDELIER_MIN_LOOKBACK = 20

# ---- KDJ 参数 ----
KDJ_N = 9
KDJ_M1 = 3
KDJ_M2 = 3

# ---- 成交量均线周期 ----
VOL_MA_PERIOD = 5

# ---- 吊灯止损回溯周期 ----
CHANDELIER_LOOKBACK = 20


# ============================================================
#  数据类型
# ============================================================

class Action(Enum):
    HOLD = "持有"
    REDUCE = "减仓"
    CLEAR = "清仓"


class SellDecision:
    """分层决策结果"""
    def __init__(self, action=Action.HOLD, code='', sell_pct=0.0, reason='',
                 triggered_layer='', triggered_signals=None, triggered_sublayer=None):
        self.action = action
        self.code = code
        self.sell_pct = sell_pct
        self.reason = reason
        self.triggered_layer = triggered_layer
        self.triggered_signals = triggered_signals if triggered_signals is not None else []
        self.triggered_sublayer = triggered_sublayer

    @staticmethod
    def hold():
        return SellDecision()

    @staticmethod
    def reduce(code, pct, reason, layer, signals=None):
        return SellDecision(Action.REDUCE, code, pct, reason, layer, signals or [])

    @staticmethod
    def clear(code, reason, layer, signals=None, sublayer=None):
        return SellDecision(Action.CLEAR, code, 1.0, reason, layer, signals or [], triggered_sublayer=sublayer)


class SellPositionState:
    """每只持仓的卖出状态机。"""
    def __init__(self, code='', cost_price=0.0, current_shares=0, original_shares=0,
                 highest_price=0.0, entry_date='',
                 warning_reduced=False, warning_trigger_date='', warning_reason='',
                 b1_needs_nextday_check=False, b1_trigger_date='', b1_additional_reduced=False,
                 confirm_reduced=False, confirm_trigger_date='', confirm_reason='',
                 cleared=False, cleared_date='',
                 rebound_restored=False, reduction_volume=0):
        self.code = code
        self.cost_price = cost_price
        self.current_shares = current_shares
        self.original_shares = original_shares
        self.highest_price = highest_price
        self.entry_date = entry_date
        self.warning_reduced = warning_reduced
        self.warning_trigger_date = warning_trigger_date
        self.warning_reason = warning_reason
        self.b1_needs_nextday_check = b1_needs_nextday_check
        self.b1_trigger_date = b1_trigger_date
        self.b1_additional_reduced = b1_additional_reduced
        self.confirm_reduced = confirm_reduced
        self.confirm_trigger_date = confirm_trigger_date
        self.confirm_reason = confirm_reason
        self.cleared = cleared
        self.cleared_date = cleared_date
        self.rebound_restored = rebound_restored
        self.reduction_volume = reduction_volume


# ============================================================
#  状态查询（纯函数）
# ============================================================

def get_trade_state_reason(state):
    """将卖出状态转为可读的原因字符串。"""
    if state is None:
        return "无状态"
    if state.cleared:
        d = state.cleared_date or "?"
        return "已清仓(%s)" % d
    if state.confirm_reduced:
        return "确认层减仓(%s)" % (state.confirm_reason or '无')
    if state.warning_reduced:
        return "预警层减仓(%s)" % (state.warning_reason or '无')
    if state.b1_needs_nextday_check:
        return "B1放量预警(待隔日确认)"
    return "持有中"


# ============================================================
#  分层卖出决策引擎
# ============================================================

class SellStrategyEngine:
    """
    分层卖出决策引擎。
    只做条件判断，返回 SellDecision。不调 passorder。
    交易执行由 adapter 层负责。
    """

    def __init__(self, strategy_name, account_id,
                 state_file, is_intraday=True,
                 hard_stop_loss=BOTTOM_LINE_LOSS_PCT):
        """
        参数:
            strategy_name: 策略名称
            account_id: QMT 账号
            state_file: 状态持久化文件路径
            is_intraday: True=盘中, False=尾盘
            hard_stop_loss: 硬止损阈值 (默认 -5%)
        """
        self.strategy_name = strategy_name
        self.account_id = account_id
        self.state_file = state_file
        self.is_intraday = is_intraday
        self.hard_stop_loss = hard_stop_loss

        # 状态缓存: {code: SellPositionState}
        self._states = {}

    # ================================================================
    #  公开入口
    # ================================================================

    def evaluate(self, today, holdings_dict, all_data, positions_data=None, rt_prices=None):
        """
        主入口：执行分层卖出检查，返回决策列表。

        参数:
            today: YYYYMMDD
            holdings_dict: {code: highest_price} 本策略跟踪的持仓
            all_data: {code: DataFrame} 行情数据
            positions_data: {code: {'cost': float, 'can_use': int, 'volume': int}}
                            QMT 持仓数据（由 adapter 层传入）
            rt_prices: {code: float} 盘中实时价格，用于底线层计算

        返回: [(code, SellDecision, shares_to_sell), ...]
        """
        if positions_data is None:
            positions_data = {}
        if rt_prices is None:
            rt_prices = {}

        decisions = []
        if not holdings_dict:
            return decisions

        for code in list(holdings_dict.keys()):
            df = all_data.get(code)
            if df is None or len(df) < 30:
                continue

            state = self._get_state(code)
            if state is None:
                state = SellPositionState(code=code, entry_date=today)

            # ---- 同步外部数据到状态 ----
            close = df['close'].astype(float)
            current_price = float(close.iloc[-1])

            # 从参数获取持仓数据（由 adapter 层传入，代替 trader.get_position）
            pos = positions_data.get(code, {})
            if state.cleared and pos.get('volume', 0) > 0:
                if self.is_reentry_allowed(code, today, df):
                    state = SellPositionState(code=code, entry_date=today)
            cost_price = pos.get('cost', 0)
            if cost_price > 0:
                state.cost_price = cost_price
            state.current_shares = pos.get('can_use', 0)

            # 最高价
            old_highest = holdings_dict.get(code, current_price)
            highest = max(old_highest, current_price)
            state.highest_price = highest

            # ---- 分层评估 ----
            rt_price = rt_prices.get(code)
            decision = self._evaluate_position(code, df, state, today, rt_price)

            if decision.action != Action.HOLD:
                shares_to_sell = int(state.current_shares * decision.sell_pct)
                if shares_to_sell >= 100:
                    shares_to_sell = (shares_to_sell // 100) * 100
                    if decision.action == Action.REDUCE:
                        if decision.triggered_layer == "预警层":
                            state.warning_reduced = True
                            state.warning_trigger_date = today
                            state.warning_reason = decision.reason
                            state.reduction_volume += shares_to_sell
                        elif decision.triggered_layer == "warning_add":
                            state.b1_additional_reduced = True
                            state.b1_needs_nextday_check = False
                            state.reduction_volume += shares_to_sell
                        elif decision.triggered_layer == "确认层":
                            state.confirm_reduced = True
                            state.confirm_trigger_date = today
                            state.confirm_reason = decision.reason

                self._save_state(code, state)
                decisions.append((code, decision, shares_to_sell))

        return decisions

    def run_end_of_day_sell(self, today, holdings_dict, all_data, positions_data=None):
        """收盘后补卖。调用 evaluate 完成。"""
        return self.evaluate(today, holdings_dict, all_data, positions_data)

    def is_reentry_allowed(self, code, today, df=None):
        """检查某股票是否允许重新买入（清仓后 NO_REENTRY_DAYS 禁止期）。"""
        state = self._states.get(code)
        if not state or not state.cleared or not state.cleared_date:
            return True

        cleared = datetime.strptime(state.cleared_date, '%Y%m%d')
        today_dt = datetime.strptime(today, '%Y%m%d')
        diff_days = (today_dt - cleared).days

        if df is not None:
            dates = pd.to_datetime(df.index)
            d1 = pd.Timestamp(state.cleared_date)
            d2 = pd.Timestamp(today)
            trading_days = len(dates[(dates > d1) & (dates <= d2)])
            allowed = trading_days >= NO_REENTRY_DAYS
        else:
            allowed = diff_days >= NO_REENTRY_DAYS + 8

        if allowed:
            self._states.pop(code, None)
            self.save_state()
        return allowed

    def load_state(self):
        """从文件加载状态。"""
        self._states = {}
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            for code, data in raw.items():
                known = {k: v for k, v in data.items()
                         if k in SellPositionState.__init__.__code__.co_varnames}
                self._states[code] = SellPositionState(**known)
        except Exception:
            pass

    def save_state(self):
        """持久化状态到文件。"""
        if not self._states:
            return
        try:
            dirname = os.path.dirname(self.state_file)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            raw = {code: st.__dict__ for code, st in self._states.items()}
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _get_state(self, code):
        """获取持仓状态。"""
        return self._states.get(code)

    def _save_state(self, code, state):
        """更新单只持仓状态并持久化。"""
        self._states[code] = state
        self.save_state()

    def confirm_clear(self, code, today):
        """确认清仓成交后更新状态（由集成层回调）。"""
        state = self._get_state(code)
        if state:
            state.cleared = True
            state.cleared_date = today
            state.current_shares = 0
            self._save_state(code, state)

    # ================================================================
    #  反弹决策（仅返回决策，由 adapter 执行）
    # ================================================================

    def check_rebound(self, code, df, state, today):
        """
        检测预警减仓后是否出现反弹修复。
        返回 (should_buy_back, buy_volume, reason) 或 (False, 0, "").
        """
        if not state.warning_reduced or state.rebound_restored:
            return False, 0, ""

        if not state.warning_trigger_date:
            return False, 0, ""

        trigger_dt = datetime.strptime(state.warning_trigger_date, '%Y%m%d')
        today_dt = datetime.strptime(today, '%Y%m%d')
        days_passed = (today_dt - trigger_dt).days

        if days_passed < 1 or days_passed > REBOUND_WINDOW_DAYS:
            if days_passed > REBOUND_WINDOW_DAYS:
                state.rebound_restored = True
            return False, 0, ""

        close = df['close'].astype(float)
        open_ = df['open'].astype(float)
        high = df['high'].astype(float)

        current_price = float(close.iloc[-1])
        current_open = float(open_.iloc[-1])
        ma5 = float(close.rolling(5).mean().iloc[-1])

        if current_price <= ma5:
            return False, 0, ""
        if current_price <= current_open:
            return False, 0, ""

        if len(close) >= 2:
            prev_high = float(high.iloc[-2])
            if current_price <= prev_high:
                return False, 0, ""

        buy_volume = state.reduction_volume
        if buy_volume > 0:
            return True, buy_volume, "反弹修复"
        return False, 0, ""

    def apply_rebound_state(self, code, state):
        """反弹执行后更新状态机（由 adapter 层回调）。"""
        state.rebound_restored = True
        state.warning_reduced = False
        state.warning_trigger_date = ''
        state.warning_reason = ''
        state.b1_needs_nextday_check = False
        state.b1_trigger_date = ''
        state.b1_additional_reduced = False
        state.confirm_reduced = False
        state.confirm_trigger_date = ''
        state.confirm_reason = ''
        state.cleared = False
        state.cleared_date = ''
        state.reduction_volume = 0
        self._save_state(code, state)

    # ================================================================
    #  分层决策引擎
    # ================================================================

    def _evaluate_position(self, code, df, state, today, rt_price=None):
        """
        按优先级执行分层评估。
        返回 SellDecision。
        """
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        open_ = df['open'].astype(float)
        volume = df['volume'].astype(float)

        # ① 底线层（最高优先级）
        decision = self._check_bottom_line(close, high, code, state, today, rt_price)
        if decision.action != Action.HOLD:
            return decision

        # ② 如果已清仓，跳过所有检查
        if state.cleared:
            return SellDecision.hold()

        # ③ 清仓层
        decision = self._check_clear_level(close, high, low, volume, df, state, today)
        if decision.action != Action.HOLD:
            return decision

        # ④ 预警层
        if not state.warning_reduced:
            warning_signals = []
            b1_triggered, b1_reason = self._signal_explosive_volume(close, high, open_, volume)
            if b1_triggered:
                warning_signals.append(b1_reason)
                state.b1_needs_nextday_check = True
                state.b1_trigger_date = today
            if self._signal_volume_divergence(close, volume):
                warning_signals.append("B2:量价背离")
            if self._signal_macd_shortening(close):
                warning_signals.append("C2:MACD红柱缩短")
            if self._signal_kdj_death(close, high, low):
                warning_signals.append("KDJ死叉+MA5走平")

            if warning_signals:
                state.warning_reduced = True
                state.warning_trigger_date = today
                state.warning_reason = " | ".join(warning_signals)
                self._save_state(code, state)
                return SellDecision.reduce(
                    code, WARNING_REDUCE_PCT,
                    " | ".join(warning_signals), "预警层", warning_signals
                )

        # ⑤ 确认层（预警已触发后检查）
        if state.warning_reduced and not state.confirm_reduced:
            if state.b1_needs_nextday_check and not state.b1_additional_reduced:
                b1_decision = self._check_b1_nextday_additional(close, open_, code, state, today)
                if b1_decision.action != Action.HOLD:
                    return b1_decision

            confirm_decision = self._check_confirm_level(close, high, low, open_, volume, df, state, today)
            if confirm_decision.action != Action.HOLD:
                return confirm_decision

        return SellDecision.hold()

    # ================================================================
    #  底线层
    # ================================================================

    def _check_bottom_line(self, close, high, code, state, today, rt_price=None):
        """底线层：硬止损检查"""
        if len(close) < 2:
            return SellDecision.hold()

        if rt_price is not None:
            current_price = rt_price
        else:
            current_price = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])

        signals = []

        if state.cost_price > 0:
            loss_pct = (current_price - state.cost_price) / state.cost_price
            if loss_pct <= self.hard_stop_loss:
                signals.append("累计亏损%.1f%%" % (loss_pct * 100))
                return SellDecision.clear(
                    code, "硬止损:累计亏损%.1f%%" % (loss_pct * 100), "底线层", signals
                )

        if prev_close > 0:
            daily_drop = (current_price - prev_close) / prev_close
            if daily_drop <= BOTTOM_LINE_DAILY_DROP_PCT:
                signals.append("单日跌幅%.1f%%" % (daily_drop * 100))
                return SellDecision.clear(
                    code, "硬止损:单日跌幅%.1f%%" % (daily_drop * 100), "底线层", signals
                )

        return SellDecision.hold()

    # ================================================================
    #  预警层
    # ================================================================

    def _check_b1_nextday_additional(self, close, open_, code, state, today):
        if not state.b1_trigger_date or today <= state.b1_trigger_date:
            return SellDecision.hold()
        if self._signal_b1_nextday_unrecovered(close, open_, state):
            return SellDecision.reduce(
                code, WARNING_ADD_REDUCE_PCT,
                "B1次日未修复", "warning_add", ["B1次日未修复"]
            )
        return SellDecision.hold()

    # ================================================================
    #  确认层
    # ================================================================

    def _check_confirm_level(self, close, high, low, open_, volume, df, state, today):
        """检查确认层：3个信号任一个触发 → 再减50%"""
        code = state.code if state.code else ""
        signals = []
        ma10 = close.rolling(10).mean()

        if self._signal_break_ma10(close, ma10):
            signals.append("A2:破10日线")
        if self._signal_high_long_shadow(high, close, open_):
            signals.append("C1:高位长上影")
        if self._signal_high_volume_negative(close, open_, volume):
            signals.append("B3:高位天量收阴")

        if signals:
            return SellDecision.reduce(
                code, CONFIRM_REDUCE_PCT,
                " | ".join(signals), "确认层", signals
            )
        return SellDecision.hold()

    # ================================================================
    #  清仓层
    # ================================================================

    def _check_clear_level(self, close, high, low, volume, df, state, today):
        """检查清仓层：5种条件任一个触发 → 清仓"""
        code = state.code if state.code else ""
        if not code:
            return SellDecision.hold()

        ma20 = close.rolling(20).mean()
        signals = []

        if self._signal_break_ma20_3days(close, ma20):
            signals.append("A3:破20日线")
        if self._signal_break_highest_low(close, high, low):
            signals.append("C3:破最高日低点")

        if len(signals) >= 3:
            return SellDecision.clear(
                code, "三项信号共振: " + " | ".join(signals), "清仓层", signals
            )

        # 预警已减仓但确认层尚未处理时，跳过移动止盈让确认层优先决策
        if not (state.warning_reduced and not state.confirm_reduced):
            if self._check_trailing_profit(close, high, low, state):
                signals.append("移动止盈")

        if signals:
            trailing_sublayer = None
            if len(signals) == 1 and signals[0] == "移动止盈":
                trailing_sublayer = 'trailing'
            return SellDecision.clear(
                code, " | ".join(signals), "清仓层", signals, sublayer=trailing_sublayer
            )
        return SellDecision.hold()

    # ================================================================
    #  移动止盈
    # ================================================================

    def _calc_dynamic_drawdown_threshold(self, highest_price, atr):
        """计算动态回撤阈值。

        公式：max(固定下限, N × ATR / 最高价)
        限制：上限 15%

        参数:
            highest_price: 持仓期间最高价
            atr: ATR(14) 值

        返回:
            float: 动态回撤阈值 (0.06 ~ 0.15)
        """
        if highest_price <= 0 or atr <= 0:
            return TRAILING_DRAWDOWN_FLOOR

        atr_pct = TRAILING_ATR_N * atr / highest_price
        dynamic = max(TRAILING_DRAWDOWN_FLOOR, atr_pct)
        return min(dynamic, TRAILING_DRAWDOWN_CAP)

    def _check_trailing_profit(self, close, high, low, state):
        """检查移动止盈条件（V1.1 ATR 自适应版）。"""
        if state.cost_price <= 0 or state.highest_price <= 0:
            return False

        current_price = float(close.iloc[-1])
        profit_pct = (current_price - state.cost_price) / state.cost_price
        drawdown = (state.highest_price - current_price) / state.highest_price

        if profit_pct <= 0:
            return False

        # 低盈利：MA5 断线
        if profit_pct < TRAILING_BREAK_MA5_INTERVAL:
            ma5 = float(close.rolling(5).mean().iloc[-1])
            if current_price < ma5:
                return True
            return False

        # 计算 ATR（用于动态阈值和吊灯止损）
        atr = None
        if len(close) >= CHANDELIER_LOOKBACK:
            atr_series = calc_atr(close, high, low, n=14)
            atr = float(atr_series.iloc[-1])

        # 动态回撤阈值
        if atr is not None:
            dd_threshold = self._calc_dynamic_drawdown_threshold(
                state.highest_price, atr)
        else:
            dd_threshold = TRAILING_DRAWDOWN_FLOOR

        # 中盈利：动态回撤 + 吊灯止损
        if profit_pct < 0.20:
            if drawdown >= dd_threshold:
                return True
            if atr is not None:
                chandelier_level = state.highest_price - CHANDELIER_ATR_MULTIPLE * atr
                if current_price <= chandelier_level:
                    return True
            return False

        # 高盈利：吊灯止损为主
        if atr is not None:
            chandelier_level = state.highest_price - CHANDELIER_ATR_MULTIPLE * atr
            if current_price <= chandelier_level:
                return True

        # 兜底：动态回撤（高盈利区间用更宽松阈值）
        high_profit_dd = min(dd_threshold * 1.5, TRAILING_DRAWDOWN_CAP)
        return drawdown >= high_profit_dd

    # ================================================================
    #  全层诊断（只读，不修改状态）
    # ================================================================

    def diagnose_position(self, code, df, cost_price, current_price, highest_price):
        """对单只持仓进行五层信号全诊断（只读操作，不修改状态）。

        参数:
            code: 股票代码
            df: DataFrame 行情数据
            cost_price: 持仓成本价
            current_price: 当前价
            highest_price: 持仓期间最高价

        返回:
            dict: {
                'code', 'status', 'cost_price', 'current_price',
                'profit_pct', 'highest_price', 'current_layer',
                'layers': {
                    'bottom_line': {name: {'triggered': bool, 'value': str}},
                    'warning': {name: {'triggered': bool, 'value': str}},
                    'confirm': {...},
                    'clear': {...},
                    'trailing': {'移动止盈': {'triggered': bool, 'detail': str}}
                }
            }
        """
        state = self._get_state(code)
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        open_ = df['open'].astype(float)
        volume = df['volume'].astype(float)

        profit_pct = (current_price - cost_price) / cost_price * 100 if cost_price > 0 else 0.0

        # 状态文字
        if state is None:
            status = '持有中'
        elif state.cleared:
            status = '已清仓(%s)' % state.cleared_date
        elif state.confirm_reduced:
            status = '确认层减仓'
        elif state.warning_reduced:
            status = '预警层减仓'
        else:
            status = '持有中'

        # 当前层次
        if state and state.cleared:
            current_layer = '清仓层'
        elif state and state.confirm_reduced:
            current_layer = '确认层'
        elif state and state.warning_reduced:
            current_layer = '预警层'
        else:
            current_layer = '正常'

        layers = {
            'bottom_line': {},
            'warning': {},
            'confirm': {},
            'clear': {},
            'trailing': {},
        }

        # ---- 底线层 ----
        if len(close) >= 2 and cost_price > 0:
            curr = float(close.iloc[-1])
            loss_pct = (curr - cost_price) / cost_price * 100
            layers['bottom_line']['累积亏损'] = {
                'triggered': loss_pct <= self.hard_stop_loss * 100,
                'value': '%.1f%%' % loss_pct,
            }
            prev_close = float(close.iloc[-2])
            if prev_close > 0:
                daily_drop = (curr - prev_close) / prev_close * 100
                layers['bottom_line']['单日跌幅'] = {
                    'triggered': daily_drop <= BOTTOM_LINE_DAILY_DROP_PCT * 100,
                    'value': '%.1f%%' % daily_drop,
                }
        else:
            layers['bottom_line']['累积亏损'] = {'triggered': False, 'value': '--'}
            layers['bottom_line']['单日跌幅'] = {'triggered': False, 'value': '--'}

        # ---- 预警层 ----
        # B1: 爆量分歧
        b1_t = False
        b1_ratio = ''
        if len(volume) >= 6 and len(close) >= 6:
            v5 = volume.rolling(5).mean()
            cv = float(volume.iloc[-1])
            av = float(v5.iloc[-1])
            if av > 0:
                ratio = cv / av
                if ratio >= VOLUME_RATIO_THRESHOLD:
                    sh = detect_long_upper_shadow(high, close, open_)
                    if sh.iloc[-1]:
                        b1_t = True
                b1_ratio = '%.1fx' % ratio
        layers['warning']['B1爆量'] = {'triggered': b1_t, 'value': b1_ratio}

        # B2: 量价背离
        b2_t, b2_r = detect_volume_price_divergence(close, volume)
        b2_val = ''
        if b2_r:
            b2_val = '%.1fx' % b2_r
        layers['warning']['B2背离'] = {'triggered': b2_t, 'value': b2_val}

        # C2: MACD红柱缩短
        c2_t = self._signal_macd_shortening(close)
        layers['warning']['C2缩短'] = {'triggered': c2_t, 'value': ''}

        # KDJ死叉
        kdj_t = self._signal_kdj_death(close, high, low)
        layers['warning']['KDJ死叉'] = {'triggered': kdj_t, 'value': ''}

        # ---- 确认层 ----
        ma10 = close.rolling(10).mean()
        a2_t = self._signal_break_ma10(close, ma10)
        a2_val = ''
        if a2_t and len(close) >= 11:
            a2_val = '%.1f%%' % ((float(ma10.iloc[-1]) - float(close.iloc[-1])) / float(ma10.iloc[-1]) * 100)
        layers['confirm']['A2破10日'] = {'triggered': a2_t, 'value': a2_val}

        c1_t = self._signal_high_long_shadow(high, close, open_)
        layers['confirm']['C1上影'] = {'triggered': c1_t, 'value': ''}

        b3_t = self._signal_high_volume_negative(close, open_, volume)
        layers['confirm']['B3天量'] = {'triggered': b3_t, 'value': ''}

        # ---- 清仓层 ----
        ma20 = close.rolling(20).mean()
        a3_t = self._signal_break_ma20_3days(close, ma20)
        layers['clear']['A3破20日'] = {'triggered': a3_t, 'value': ''}

        c3_t = self._signal_break_highest_low(close, high, low)
        layers['clear']['C3破低'] = {'triggered': c3_t, 'value': ''}

        # ---- 移动止盈（V1.1 ATR 自适应版）----
        trailing_t = False
        trailing_detail = ''

        if cost_price > 0 and highest_price > 0:
            profit_r = (current_price - cost_price) / cost_price
            drawdown_pct = (highest_price - current_price) / highest_price * 100
            profit_pct_val = profit_r * 100

            if profit_pct_val > 0:
                if profit_pct_val < TRAILING_BREAK_MA5_INTERVAL * 100:
                    ma5_v = float(close.rolling(5).mean().iloc[-1]) if len(close) >= 5 else 0
                    below_ma5 = current_price < ma5_v
                    trailing_detail = '盈利%+.1f%%<%d%%, %s' % (
                        profit_pct_val, int(TRAILING_BREAK_MA5_INTERVAL * 100),
                        '已破MA5' if below_ma5 else '未破MA5')
                    trailing_t = below_ma5
                else:
                    # 计算 ATR
                    atr = None
                    if len(close) >= CHANDELIER_LOOKBACK:
                        atr_series = calc_atr(close, high, low, n=14)
                        atr = float(atr_series.iloc[-1])

                    # 动态回撤阈值
                    if atr is not None:
                        dd_threshold = self._calc_dynamic_drawdown_threshold(
                            highest_price, atr) * 100
                    else:
                        dd_threshold = TRAILING_DRAWDOWN_FLOOR * 100

                    if profit_pct_val < 20:
                        trailing_t = drawdown_pct >= dd_threshold
                        trailing_detail = '盈利%+.1f%%, 回撤%.1f%%, 阈值%.1f%%' % (
                            profit_pct_val, drawdown_pct, dd_threshold)
                    else:
                        # 高盈利：吊灯优先，动态回撤兜底
                        chandelier_t = (atr is not None and
                                        current_price <= highest_price - CHANDELIER_ATR_MULTIPLE * atr)
                        high_profit_dd = min(dd_threshold * 1.5, TRAILING_DRAWDOWN_CAP * 100)
                        trailing_t = chandelier_t or (drawdown_pct >= high_profit_dd)
                        trailing_detail = '盈利%+.1f%%, 吊灯=%s, 回撤%.1f%%, 阈值%.1f%%' % (
                            profit_pct_val, '触发' if chandelier_t else '未触发',
                            drawdown_pct, high_profit_dd)

        layers['trailing']['移动止盈'] = {
            'triggered': trailing_t,
            'detail': trailing_detail,
        }

        return {
            'code': code,
            'status': status,
            'cost_price': cost_price,
            'current_price': current_price,
            'profit_pct': profit_pct,
            'highest_price': highest_price,
            'current_layer': current_layer,
            'layers': layers,
        }

    # ================================================================
    #  信号检测函数
    # ================================================================

    def _signal_break_ma5(self, close):
        """A1: 收盘价跌破 MA5"""
        if len(close) < 6:
            return False
        ma5 = close.rolling(5).mean()
        return bool(close.iloc[-1] < ma5.iloc[-1])

    def _signal_break_ma10(self, close, ma10):
        """A2: 收盘价跌破 MA10"""
        if len(close) < 11:
            return False
        return bool(close.iloc[-1] < ma10.iloc[-1])

    def _signal_break_ma20_3days(self, close, ma20):
        """A3: 跌破 MA20 且 3 日未收复"""
        if len(close) < 24:
            return False
        if close.iloc[-1] >= ma20.iloc[-1]:
            return False
        days_below = 0
        for i in range(min(CLEAR_MA20_DAYS, len(close) - 1)):
            if close.iloc[-1 - i] < ma20.iloc[-1 - i]:
                days_below += 1
            else:
                break
        return days_below >= CLEAR_MA20_DAYS

    def _signal_explosive_volume(self, close, high, open_, volume):
        """
        B1: 爆量分歧
        - 成交量 > 均量5 × 1.5
        - 长上影线
        """
        if len(volume) < 6 or len(close) < 6:
            return False, ""

        vol_ma5 = volume.rolling(5).mean()
        current_vol = float(volume.iloc[-1])
        avg_vol = float(vol_ma5.iloc[-1])

        if avg_vol <= 0:
            return False, ""

        vol_ratio = current_vol / avg_vol
        if vol_ratio < VOLUME_RATIO_THRESHOLD:
            return False, ""

        has_long_shadow = detect_long_upper_shadow(high, close, open_)
        if not has_long_shadow.iloc[-1]:
            return False, ""

        return True, "B1:爆量分歧(%.1f倍)" % vol_ratio

    def _signal_b1_nextday_unrecovered(self, close, open_, state):
        """B1 隔日检查：次日不修复 → 追加减仓 20%"""
        if len(close) < 2:
            return False

        current_price = float(close.iloc[-1])
        ma5 = float(close.rolling(5).mean().iloc[-1])

        if current_price > ma5 and current_price > float(open_.iloc[-1]):
            state.b1_needs_nextday_check = False
            state.b1_additional_reduced = False
            return False

        return True

    def _signal_volume_divergence(self, close, volume):
        """B2: 量价背离"""
        diverged, _ = detect_volume_price_divergence(close, volume)
        return diverged

    def _signal_macd_shortening(self, close):
        """C2: MACD 红柱连续缩短 3 日"""
        if len(close) < MACD_SHORTEN_DAYS + 26:
            return False

        _, _, macd_bar = self._calc_macd_safe(close)

        if len(macd_bar) < MACD_SHORTEN_DAYS + 1:
            return False

        for i in range(MACD_SHORTEN_DAYS + 1):
            if pd.isna(macd_bar.iloc[-1 - i]):
                return False

        if macd_bar.iloc[-1] <= 0:
            return False

        for i in range(MACD_SHORTEN_DAYS):
            if macd_bar.iloc[-1 - i] >= macd_bar.iloc[-2 - i]:
                return False

        return True

    def _signal_kdj_death(self, close, high, low):
        """5日线斜率走平 + KDJ 死叉"""
        if len(close) < 15:
            return False

        ma5 = close.rolling(5).mean()
        if len(ma5) < 3:
            return False
        angle = calc_angle_simple(ma5)
        if angle is None or abs(angle) > MA5_SLOPE_FLAT_DEG:
            return False

        k, d, j = calc_kdj(close, high, low)
        if len(k) < 3 or len(d) < 3:
            return False
        if pd.isna(k.iloc[-1]) or pd.isna(d.iloc[-1]):
            return False
        if pd.isna(k.iloc[-2]) or pd.isna(d.iloc[-2]):
            return False

        return bool(k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2])

    def _signal_high_long_shadow(self, high, close, open_):
        """C1: 高位长上影线"""
        if len(close) < 10:
            return False

        recent_high = float(close.iloc[-5:].max())
        compare_price = float(close.iloc[-10])
        if compare_price <= 0:
            return False
        price_increase = (recent_high - compare_price) / compare_price
        if price_increase < 0.05:
            return False

        shadow = detect_long_upper_shadow(high, close, open_)
        return bool(shadow.iloc[-1])

    def _signal_high_volume_negative(self, close, open_, volume):
        """B3: 高位天量收阴"""
        if len(close) < 10:
            return False

        if len(close) >= 20:
            recent_max = float(close.iloc[-5:].max())
            period_max = float(close.iloc[-20:].max())
            if recent_max < period_max * 0.95:
                return False

        if close.iloc[-1] >= open_.iloc[-1]:
            return False

        if len(volume) >= 6:
            vol_ma5 = volume.rolling(5).mean()
            if float(volume.iloc[-1]) < float(vol_ma5.iloc[-1]) * VOLUME_RATIO_THRESHOLD:
                return False

        return True

    def _signal_break_highest_low(self, close, high, low):
        """C3: 跌破最高价当日最低点"""
        if len(high) < 30:
            return False

        recent_high = high.iloc[-30:]
        highest_val = recent_high.max()
        highest_pos = 0
        for i in range(len(recent_high)):
            if recent_high.iloc[i] >= highest_val:
                highest_pos = i
                break

        lowest_of_highest_day = float(low.iloc[-30:].iloc[highest_pos])
        current_price = float(close.iloc[-1])
        return current_price < lowest_of_highest_day

    # ================================================================
    #  辅助方法
    # ================================================================

    def _calc_macd_safe(self, close):
        """安全计算 MACD，处理 NaN。"""
        if len(close) < 26:
            return None, None, None
        try:
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            diff = ema12 - ema26
            dea = diff.ewm(span=9, adjust=False).mean()
            macd = 2 * (diff - dea)
            return diff, dea, macd
        except Exception:
            return None, None, None


# ============================================================
#  方案B诊断格式化输出
# ============================================================

def format_plan_b_diagnosis(diagnosis_list, today_str, now_str=''):
    """将 diagnose_position() 返回的诊断列表格式化为方案B输出。

    参数:
        diagnosis_list: list of dict (diagnose_position 返回值)
        today_str: 日期字符串 (YYYYMMDD)
        now_str: 时间字符串 (HHMM)

    返回:
        list of str: 格式化后的文本行
    """
    lines = []
    lines.append('=' * 70)
    lines.append('[风控专岗] 持仓风控明细 - %s %s' % (today_str, now_str))
    lines.append('')

    # 分类计数
    cnt_normal = 0
    cnt_warning = 0
    cnt_confirm = 0
    cnt_clear = 0

    for diag in diagnosis_list:
        code = diag['code']
        status = diag['status']
        cost = diag['cost_price']
        curr = diag['current_price']
        profit = diag['profit_pct']
        highest = diag['highest_price']

        # 统计
        layer = diag['current_layer']
        if layer == '正常':
            cnt_normal += 1
        elif layer == '预警层':
            cnt_warning += 1
        elif layer == '确认层':
            cnt_confirm += 1
        elif layer == '清仓层':
            cnt_clear += 1

        lines.append(' %s ( %s . 成本%.2f . 现价%.2f . 盈利%+.1f%% . 最高%.2f )' % (
            code, status, cost, curr, profit, highest))
        lines.append(' ' + '-' * 65)

        layers = diag['layers']

        def _sym(t):
            return '√' if t else '×'

        # ---- 底线层 ----
        bl_parts = []
        for name, info in layers['bottom_line'].items():
            if info['value'] and info['value'] != '--':
                bl_parts.append('%s: %s(%s)' % (name, _sym(info['triggered']), info['value']))
            else:
                bl_parts.append('%s: %s' % (name, _sym(info['triggered'])))
        if bl_parts:
            lines.append(' 底线层   ' + ' | '.join(bl_parts))

        # ---- 预警层 ----
        w_names = list(layers['warning'].keys())
        w_parts1 = []
        w_parts2 = []
        for name in w_names:
            info = layers['warning'][name]
            if info['value']:
                s = '%s: %s(%s)' % (name, _sym(info['triggered']), info['value'])
            else:
                s = '%s: %s' % (name, _sym(info['triggered']))
            if len(w_parts1) < 2:
                w_parts1.append(s)
            else:
                w_parts2.append(s)
        if w_parts1:
            lines.append(' 预警层   ' + ' | '.join(w_parts1))
        if w_parts2:
            lines.append('          ' + ' | '.join(w_parts2))

        # ---- 确认层 ----
        c_parts = []
        for name, info in layers['confirm'].items():
            if info['value']:
                c_parts.append('%s: %s(%s)' % (name, _sym(info['triggered']), info['value']))
            else:
                c_parts.append('%s: %s' % (name, _sym(info['triggered'])))
        if c_parts:
            lines.append(' 确认层   ' + ' | '.join(c_parts))

        # ---- 清仓层 ----
        cl_parts = []
        for name, info in layers['clear'].items():
            if info['value']:
                cl_parts.append('%s: %s(%s)' % (name, _sym(info['triggered']), info['value']))
            else:
                cl_parts.append('%s: %s' % (name, _sym(info['triggered'])))
        if cl_parts:
            lines.append(' 清仓层   ' + ' | '.join(cl_parts))

        # ---- 移动止盈 ----
        t_info = layers['trailing']['移动止盈']
        if t_info.get('detail'):
            lines.append(' 移动止盈  %s  %s' % (_sym(t_info['triggered']), t_info['detail']))
        else:
            lines.append(' 移动止盈  %s' % _sym(t_info['triggered']))

    lines.append('=' * 70)
    total = len(diagnosis_list)
    lines.append(' 汇总: 持仓%d只 | 持有中%d | 预警%d | 确认%d | 清仓%d' % (
        total, cnt_normal, cnt_warning, cnt_confirm, cnt_clear))

    return lines
