# coding=utf-8
"""
QMT 适配层 — core/ 决策层与 QMT 运行时的桥接。
包含 Trader、StrategyRunner、QMT 生命周期、数据加载、订单管理、文件操作。

最后修改: 2026-06-10
修改内容:
  - _retry_pending_sell: 失败路径保留状态并递增 retries
  - Trader.sell: 新增 use_market 参数, retries>=1 自动市价单
  - _all_day_decision_matrix: 修正 evaluate 调用签名
  - handlebar: 捕获 KeyboardInterrupt 静默退出
  - 风控红线: 移除卖出 retries>=3 放弃, 非跌停无限重试
  - 买入重试: 移除3次上限, 失败立即转补买
  - TEST_MODE: 跳过尾盘14:40等待门，全天可触发 _execute_trade（dev/回测用，生产=False）
  - 未成交撤单: 同步递增 retries 触发市价单切换
"""
import os
import json
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from core.utils import calc_bias, ema, ma, safe_last
from core.signal_main_rise import SectorAnalyzer, check_buy
from core.scoring.switch_scorer import SwitchScorer
from core.signal_main_rise import REQUIRED_BARS, MIN_BARS
from core.signal_main_rise import MARKET_INDEX_CODE, MARKET_MA20, MARKET_MA60
from core.signal_main_rise import SECTOR_HOT_TOP_N
from core.risk_manager import Action, SellDecision, SellPositionState, SellStrategyEngine, get_trade_state_reason, format_plan_b_diagnosis


_DEFAULT_CONFIG = {
    'paths': {},
    'safemode': {
        'enabled': False,
        'log_dir': 'D:/QMT_POOL/safemode_logs/',
        'block_passorder': True,
        'block_file_write': False,
    },
    'debug_mode': {'enabled': False},
    'strategy': {'capital_base': 100000},
}


def _lightweight_yaml_parse(text):
    """轻量 YAML 解析，仅支持本项目 global_config.yaml 的简单格式。

    支持：顶层 section、key: value、bool、数字、字符串路径。
    """
    result = {}
    current_section = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.rstrip()
        value = value.strip()
        if not value:
            current_section = key
            result.setdefault(current_section, {})
            continue
        val = value.strip('"').strip("'")
        if val.lower() in ('true', 'yes'):
            parsed = True
        elif val.lower() in ('false', 'no'):
            parsed = False
        else:
            try:
                parsed = int(val)
            except ValueError:
                try:
                    parsed = float(val)
                except ValueError:
                    parsed = val
        if current_section is not None:
            result[current_section][key] = parsed
        else:
            result[key] = parsed
    return result


def _load_config():
    """从 config/global_config.yaml 加载路径和 safemode 配置。

    PyYAML 可用时使用 yaml.safe_load；不可用时使用内置轻量解析器。
    配置文件缺失/读取失败/解析失败时，返回内置默认配置。
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(os.path.dirname(script_dir), 'config', 'global_config.yaml')
    except NameError:
        config_path = 'D:/QMT_STRATEGIES/config/global_config.yaml'

    try:
        with open(config_path, encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print('[配置] 读取配置失败，使用内置默认配置: %s' % e)
        return dict(_DEFAULT_CONFIG)

    try:
        import yaml
        cfg = yaml.safe_load(text) or {}
    except ImportError:
        print('[配置] PyYAML 不可用，使用内置默认配置')
        cfg = _lightweight_yaml_parse(text)
    except Exception as e:
        print('[配置] YAML 解析失败，使用内置默认配置: %s' % e)
        cfg = _lightweight_yaml_parse(text)

    if not cfg:
        cfg = dict(_DEFAULT_CONFIG)
    return cfg

_full_config = _load_config()
_path_config = _full_config.get('paths', {})
_safemode_config = _full_config.get('safemode', {})

SAFEMODE_ENABLED = _safemode_config.get('enabled', False)
SAFEMODE_LOG_DIR = _safemode_config.get('log_dir', 'D:/QMT_POOL/safemode_logs/')
SAFEMODE_BLOCK_PASSORDER = _safemode_config.get('block_passorder', True)
SAFEMODE_BLOCK_FILE_WRITE = _safemode_config.get('block_file_write', False)

_debug_config = _full_config.get('debug_mode', {})
DEBUG_MODE = _debug_config.get('enabled', False)

_strategy_config = _full_config.get('strategy', {})


# ============================================================
#  参数常量
# ============================================================

ACCOUNT_ID = '67014907'
STRATEGY_NAME = '双带主升浪_尾盘_外部池_beat四层版'

STRATEGY_CAPITAL = float(_strategy_config.get('capital_base', 100000))
MAX_HOLD = 3
TARGET_RATIO = 0.30
MAX_TOTAL_RATIO = 0.90
FIXED_AMOUNT_PER_STOCK = 30000
HARD_STOP_LOSS = -0.08
N_SELL = 7

BATCH_SIZE = 500
MAX_BUY_BIAS5 = 10.0
MAX_SELL_RETRIES = 5

POOL_FILE = _path_config.get('pool_file', 'D:/QMT_POOL/QMTselected.txt')
INTRADAY_HOLD_FILE = _path_config.get('intraday_hold_file', 'D:/QMT_POOL/endofday_holdings_beat.txt')
ENDOFDAY_HOLD_FILE = _path_config.get('endofday_hold_file', 'D:/QMT_POOL/intraday_holdings.txt')
INTRADAY_NAV_FILE = _path_config.get('intraday_nav_file', 'D:/QMT_POOL/endofday_nav_beat.txt')
ENDOFDAY_NAV_FILE = _path_config.get('endofday_nav_file', 'D:/QMT_POOL/endofday_nav.txt')
SECTOR_HEAT_FILE = _path_config.get('sector_heat_file', 'D:/QMT_POOL/sector_heat.json')
POOL_PATH = _path_config.get('pool_path', 'D:/QMT_POOL/selected.txt')
TRADE_LOG_FILE = _path_config.get('trade_log_file', 'D:/QMT_POOL/成交记录_尾盘_外部池_beat.txt')
SCORE_HISTORY_FILE = _path_config.get('score_history_file', 'D:/QMT_POOL/endofday_score_history_beat.json')
INTRADAY_SELL_STATE_FILE = _path_config.get('intraday_sell_state_file', 'D:/QMT_POOL/endofday_sell_state_beat.json')

TEST_MODE = False
QUIET_MODE = False

# ==== 全天调试版路径覆盖 ====
# DEBUG_MODE=True 时使用独立持仓/净值/日志文件，避免与尾盘版互相干扰
if DEBUG_MODE:
    STRATEGY_NAME = '全天测试版'
    INTRADAY_HOLD_FILE = 'D:/QMT_POOL/allday_holdings.txt'
    ENDOFDAY_HOLD_FILE = 'D:/QMT_POOL/allday_endofday.txt'
    INTRADAY_NAV_FILE = 'D:/QMT_POOL/allday_nav.txt'
    TRADE_LOG_FILE = 'D:/QMT_POOL/成交记录_全天版.txt'
    # POOL_FILE/POOL_PATH 共享外部池，保持一致
    POOL_FILE = _path_config.get('pool_file', 'D:/QMT_POOL/QMTselected.txt')
    POOL_PATH = _path_config.get('pool_path', 'D:/QMT_POOL/selected.txt')

# ==== 全天调试版参数 ====
ALLDAY_MORNING_START = '0924'
ALLDAY_MORNING_END   = '1130'
ALLDAY_AFTERNOON_START = '1300'
ALLDAY_AFTERNOON_END   = '1500'

# 操作点（整:分格式）
OPERATION_POINTS = ['0924', '1000', '1330', '1430']
# 0924 = 策略首次启动时执行一次全流程
# 1000 = 方向确立后的首次决策
# 1330 = 下午方向确认后的决策
# 1430 = 尾盘冲刺前的最后一次决策

# 生产版买入委托窗口（保持外部通达信池与其他逻辑不变，仅前移买入时间）
BUY_WINDOW_START = '1000'
BUY_WINDOW_END = '1010'
BUY_WINDOW_LABEL = '10:00-10:10'


# ============================================================
#  全局状态
# ============================================================

_g_init_done = False
_g_trader = None
_g_scorer = None
_g_all_data = {}
_g_stock_list = []
_g_index_data = None
_g_my_codes = {}
_g_cumulative_pnl = 0.0
_g_last_date = ''
_g_today_done = False
_g_data_loaded = False
_g_wait_printed = False
_g_pending_buys = {}
_g_retry_queue = []
_g_candidate_queue = []
_g_strategy_start_ts = None   # 策略启动时间戳（cooling-off 用）
_g_cooling_printed = False        # P2: cooling-off 首次提示防刷屏
_g_timegate_skip_printed = set()  # P2: 防刷屏 — 已打印的"时段拦截"事件 (kind, code, key)

# ===== P3: 集合竞价预埋硬止损 =====
PREMARKET_HARD_STOP_MODE = 'OFF'  # 'OFF' / 'G3_ONLY' / 'G2_AND_G3'  P3 观察期: 验日K字段后切回 'G3_ONLY'
_g_premarket_check_done = False       # 单日跑一次的防重入 flag（日切清空）
_g_premarket_orders = {}              # code -> {order_id, grade, price, shares, ref_price}

_g_per_stock_amount = 0
_g_pending_sells = {}
_g_pending_limitdown_sells = {}  # {code: {info dict}} - limit-down deferred sell queue
_g_sell_engine = None
_g_op_executed = {}  # {operation_point_str: bool} - 操作点执行记录（全天版）
_g_startup_done = False  # 启动时是否已执行全流程（全天版）

# 防刷屏守卫
_g_last_sell_fingerprint = ''    # 上次打印的诊断指纹，无变化时不重复打印
_g_sell_skip_printed = set()     # 已打印过"[跳过]"的股票
_g_price_skip_printed = set()    # 已打印过"[卖出跳过]"的股票
_g_retry_skip_printed = set()    # 已打印过"[卖出重试]"的股票
_g_failed_printed = set()          # 当日卖出委托失败的股票，避免重复尝试
_g_sell_fail_cooldown = {}         # {code: timestamp} 卖出失败60秒冷却

# ============================================================
#  策略日志缓冲区
# ============================================================

_g_log_entries = []  # [(timestamp, message), ...]
_g_trade_records = []  # [{type, code, direction, volume, price, amount, status}, ...]
_g_log_written_today = False


# ============================================================
#  策略日志
# ============================================================

def _append_log(timestamp=None, message=''):
    global _g_log_entries
    # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
    ts = timestamp or datetime.now().strftime('%H:%M:%S')
    _g_log_entries.append((ts, message))


def _reset_log_buffers():
    global _g_log_entries, _g_trade_records, _g_log_written_today
    _g_log_entries = []
    _g_trade_records = []
    _g_log_written_today = False


# ============================================================
#  SAFEMODE 安全壳
# ============================================================

def _safemode_log_trade_blocked(stock_code, direction, volume, price, remark, source_function):
    """记录被拦截的交易到 CSV 日志。"""
    if not SAFEMODE_ENABLED:
        return
    os.makedirs(SAFEMODE_LOG_DIR, exist_ok=True)
    # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
    today = datetime.now().strftime('%Y%m%d')
    log_path = os.path.join(SAFEMODE_LOG_DIR, 'trades_blocked_%s.csv' % today)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    import csv
    file_exists = os.path.exists(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['timestamp', 'stock_code', 'direction', 'volume', 'price', 'remark', 'source_function'])
        writer.writerow([timestamp, stock_code, direction, volume, price, remark, source_function])


def _safemode_log_signal(stock_code, score_8d, buy_points, sector_heat, details=None):
    """记录信号日志到 CSV。"""
    if not SAFEMODE_ENABLED:
        return
    os.makedirs(SAFEMODE_LOG_DIR, exist_ok=True)
    # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
    today = datetime.now().strftime('%Y%m%d')
    log_path = os.path.join(SAFEMODE_LOG_DIR, 'signals_%s.csv' % today)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    import csv
    file_exists = os.path.exists(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['timestamp', 'stock_code', 'score_8d', 'buy_points', 'sector_heat'])
        writer.writerow([timestamp, stock_code, score_8d, buy_points, sector_heat])


# ============================================================
#  Trader — QMT 交易员
# ============================================================

class Trader:
    """封装 passorder、持仓查询、资金查询。"""

    def __init__(self, context, account_id, account_type='STOCK', strategy_name='Trader'):
        self.C = context
        self.acct = account_id
        self.acct_type = account_type
        self.strategy_name = strategy_name
        self.BUY_CODE = 23 if account_type == 'STOCK' else 33
        self.SELL_CODE = 24 if account_type == 'STOCK' else 34

    def _passorder(self, order_type, stock_code, volume, remark='', price_type=5, price=-1):
        # ===== SAFEMODE 金丝雀断言 =====
        # 防御性编程：如果 SAFEMODE 开启且走到这里，说明上层漏了拦截，直接崩
        if SAFEMODE_ENABLED:
            assert False, "[SAFEMODE_CRASH] 代码路径遗漏！尝试真实交易: %s" % stock_code

        if volume <= 0:
            return False
        vol = int(volume)
        full_remark = "%s|%s" % (self.strategy_name, remark) if remark else self.strategy_name
        try:
            order_id = passorder(
                order_type, 1101, self.acct, stock_code,
                price_type, price, vol,
                full_remark, 2, "", self.C
            )
            return order_id
        except Exception as e:
            err = str(e).strip().split('\n')[0]
            if 'signature' in err or 'match' in err:
                print("[交易] 委托失败: 参数类型不匹配")
            else:
                print("[交易] 委托失败: %s" % err)
            return None

    def _get_ask1_price(self, stock_code):
        """获取卖一价"""
        try:
            tick = self.C.get_full_tick([stock_code])
            if tick and stock_code in tick:
                ask1 = tick[stock_code].get('askPrice1', 0) or tick[stock_code].get('askPrice', 0)
                # 处理 askPrice 是列表的情况（5档卖价数组）
                if isinstance(ask1, (list, tuple)):
                    ask1 = ask1[0] if ask1 else 0
                if ask1 and ask1 > 0:
                    return float(ask1)
            # 回退：使用最新成交价
            if tick and stock_code in tick:
                last = tick[stock_code].get('lastPrice', 0)
                if isinstance(last, (list, tuple)):
                    last = last[0] if last else 0
                if last and last > 0:
                    return float(last)
        except Exception as e:
            print("  [卖一价] %s 获取失败: %s" % (stock_code, e))
        return None

    def buy(self, stock_code, volume, remark=''):
        if SAFEMODE_ENABLED:
            price = 0.0
            print("[SAFEMODE] [X] 买入被拦截: %s %d股 %s" % (stock_code, volume, remark))
            _safemode_log_trade_blocked(stock_code, 'buy', volume, price, remark, 'buy')
            from datetime import datetime as _dt
            return "safemode_" + _dt.now().strftime('%Y%m%d%H%M%S%f')
        vol = (volume // 100) * 100
        if vol < 100:
            print("[交易] 买入 %s 数量不足100股: %s" % (stock_code, volume))
            return None
        t_before = time.time()
        self._passorder(self.BUY_CODE, stock_code, vol, remark)
        order_id = self._lookup_recent_order_id(stock_code, vol, 'buy', t_before)
        if order_id is None:
            print("  [买入反查失败] %s %d股 委托可能未到达交易所" % (stock_code, vol))
            return None
        return order_id

    def sell(self, stock_code, volume, remark='', use_market=False):
        """
        卖出委托。
        use_market=False: 限价卖一价挂单，获取不到时回退市价单
        use_market=True:  直接市价卖出，确保成交
        """
        if SAFEMODE_ENABLED:
            price = 0.0
            print("[SAFEMODE] [X] 卖出被拦截: %s %d股 %s" % (stock_code, volume, remark))
            _safemode_log_trade_blocked(stock_code, 'sell', volume, price, remark, 'sell')
            from datetime import datetime as _dt
            return "safemode_" + _dt.now().strftime('%Y%m%d%H%M%S%f')
        vol = int(volume)
        if vol <= 0:
            return None

        t_before = time.time()

        if use_market:
            self._passorder(self.SELL_CODE, stock_code, vol, remark, price_type=5, price=-1)
        else:
            sell_price = self._get_ask1_price(stock_code)
            if not sell_price or sell_price <= 0:
                print("  [卖出] %s 无法获取卖一价，使用市价单" % stock_code)
                self._passorder(self.SELL_CODE, stock_code, vol, remark, price_type=5, price=-1)
            else:
                self._passorder(self.SELL_CODE, stock_code, vol, remark, price_type=0, price=sell_price)

        order_id = self._lookup_recent_order_id(stock_code, vol, 'sell', t_before)
        if order_id is None:
            print("  [卖出反查失败] %s %d股 委托可能未到达交易所，按失败处理" % (stock_code, vol))
            return None
        return order_id

    def cancel_order(self, order_id, stock_code):
        try:
            passorder(24, 1101, self.acct, stock_code, 5, order_id, 0,
                      "%s|撤单" % self.strategy_name, 2, "", self.C)
            return True
        except Exception as e:
            print("  [撤单] %s: 订单%s 失败: %s" % (stock_code, order_id, e))
            return False

    def _lookup_recent_order_id(self, stock_code, expected_vol, direction, t_before):
        """
        passorder 调用后反查委托簿，找到刚刚下的那笔委托的 m_nOrderID。
        v3: remark 不再硬过滤，仅作为多候选优先级信号。

        stock_code: '600110.SH'
        expected_vol: 期望股数（与 passorder 传入的 vol 一致）
        direction: 'sell' or 'buy'
        t_before: passorder 调用前的 time.time() 时间戳

        过滤条件（全部 AND）：
          1. stock_code 匹配
          2. vol == expected_vol
          3. status not in (54, 55, 57)
          4. direction: m_strOptName 含 '卖'/'买'；字段为空时放宽不卡
          5. t_before: m_strInsertTime HHMMSS >= t_before HHMMSS - 1；解析失败时放宽不卡

        多候选排序：remark 含 strategy_name 优先；同级按插入时间越近越优先。

        返回 m_nOrderID（int）；找不到返回 None。
        """
        try:
            import time as _time
            orders = get_trade_detail_data(self.acct, self.acct_type, 'order')
            if not orders:
                return None

            t_struct = _time.localtime(t_before)
            t_before_hms = t_struct.tm_hour * 10000 + t_struct.tm_min * 100 + t_struct.tm_sec
            t_threshold_hms = t_before_hms - 1

            candidates = []
            for o in reversed(orders):
                code = "%s.%s" % (getattr(o, 'm_strInstrumentID', ''), getattr(o, 'm_strExchangeID', ''))
                if code != stock_code:
                    continue

                vol = getattr(o, 'm_nOrderVolume', 0)
                if vol != expected_vol:
                    continue

                status = getattr(o, 'm_nOrderStatus', None)
                if status in (54, 55, 57):
                    continue

                op_name = getattr(o, 'm_strOptName', '')
                if direction == 'sell' and op_name and '卖' not in op_name and 'sell' not in op_name.lower():
                    continue
                if direction == 'buy' and op_name and '买' not in op_name and 'buy' not in op_name.lower():
                    continue

                ot_str = getattr(o, 'm_strInsertTime', '')
                ot_hms = None
                if ot_str:
                    try:
                        ot_hms = int(ot_str[-6:])
                    except Exception:
                        ot_hms = None
                    if ot_hms is not None and ot_hms < t_threshold_hms:
                        continue

                remark = getattr(o, 'm_strRemark', '')
                remark_match = 1 if self.strategy_name in remark else 0
                candidates.append((remark_match, ot_hms if ot_hms is not None else -1, o))

            if not candidates:
                return None

            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            return getattr(candidates[0][2], 'm_nOrderID', None)
        except Exception as e:
            print("  [反查订单] %s 失败: %s" % (stock_code, e))
            return None

    def get_position(self, stock_code):
        try:
            positions = get_trade_detail_data(self.acct, self.acct_type, 'position')
            for pos in positions:
                code = "%s.%s" % (pos.m_strInstrumentID, pos.m_strExchangeID)
                if code == stock_code:
                    return {
                        'volume': getattr(pos, 'm_nVolume', 0),
                        'can_use': getattr(pos, 'm_nCanUseVolume', 0),
                        'cost': getattr(pos, 'm_dOpenPrice', 0),
                        'profit': getattr(pos, 'm_dTodayBSPnl', 0),
                    }
        except Exception as e:
            print("[交易] 查询持仓失败: %s" % e)
        return None

    def get_holdings(self):
        holdings = {}
        try:
            positions = get_trade_detail_data(self.acct, self.acct_type, 'position')
            for pos in positions:
                code = "%s.%s" % (pos.m_strInstrumentID, pos.m_strExchangeID)
                holdings[code] = {
                    'volume': getattr(pos, 'm_nVolume', 0),
                    'can_use': getattr(pos, 'm_nCanUseVolume', 0),
                    'cost': getattr(pos, 'm_dOpenPrice', 0),
                    'profit': getattr(pos, 'm_dTodayBSPnl', 0),
                }
        except Exception as e:
            print("[交易] 查询持仓失败: %s" % e)
        return holdings

    def get_available_cash(self):
        try:
            accounts = get_trade_detail_data(self.acct, self.acct_type, 'account')
            if accounts:
                return float(accounts[0].m_dAvailable)
        except Exception as e:
            print("[交易] 查询资金失败: %s" % e)
        return 0.0

    def get_total_asset(self):
        try:
            accounts = get_trade_detail_data(self.acct, self.acct_type, 'account')
            if accounts:
                acct = accounts[0]
                for attr in ('m_dAssetBalance', 'm_dBalance', 'm_dAssureAsset',
                             'm_dTotalAsset', 'totalAsset', 'm_dTotal'):
                    val = getattr(acct, attr, None)
                    if val is not None and float(val) > 0:
                        return float(val)
                avail = float(getattr(acct, 'm_dAvailable', 0) or 0)
                mv = float(getattr(acct, 'm_dStockValue', 0) or
                           getattr(acct, 'm_dInstrumentValue', 0) or 0)
                if avail > 0 or mv > 0:
                    return avail + mv
        except Exception as e:
            print("[交易] 查询总资产失败: %s" % e)
        return 0.0

    def get_market_value(self):
        try:
            accounts = get_trade_detail_data(self.acct, self.acct_type, 'account')
            if accounts:
                acct = accounts[0]
                for attr in ('m_dStockValue', 'm_dInstrumentValue', 'm_dMarketValue'):
                    val = getattr(acct, attr, None)
                    if val is not None and float(val) > 0:
                        return float(val)
        except Exception as e:
            print("[交易] 查询市值失败: %s" % e)
        return 0.0


# ============================================================
#  QMT 时间/名称 工具
# ============================================================

def _get_qmt_time(C):
    try:
        return C.get_current_time()
    except Exception:
        tick_ms = C.get_tick_timetag()
        return datetime.fromtimestamp(tick_ms / 1000)


def _market_now(C):
    """策略权威时间：优先 QMT 行情时间，盘前无行情时用最新K线日期兜底。

    设备时钟不可信（CMOS电池没电会错乱），策略绝对时间一律走此函数，
    不用 datetime.now()。相对计时（time.time()差值）不受影响，仍用设备时钟。
    """
    # 1. 优先 QMT 行情时间
    try:
        dt = _get_qmt_time(C)
        if dt is not None:
            if dt.year >= 2020:
                return dt
    except Exception:
        pass
    # 2. 兜底：最新K线日期（盘前9:25前无行情时）
    try:
        if _g_all_data:
            for code, df in _g_all_data.items():
                if df is not None and len(df) > 0:
                    last_idx = df.index[-1]
                    if hasattr(last_idx, 'to_pydatetime'):
                        return last_idx.to_pydatetime()
                    return datetime.strptime(str(last_idx)[:10], '%Y-%m-%d')
    except Exception:
        pass
    # 3. 最后兜底：设备时间（仅当行情和K线都拿不到，记录警告）
    print("  [时间警告] 行情时间与K线均不可用，回退设备时间")
    return datetime.now()


def _get_stock_name_safe(C, code):
    try:
        name = C.get_stock_name(code)
        if name:
            return name
    except Exception:
        pass
    return code


def _is_trading_time(dt):
    """判断当前时间是否在A股交易时段内（9:30-11:30, 13:00-15:00）。"""
    now_str = dt.strftime('%H%M')
    if '0930' <= now_str <= '1130':
        return True
    if '1300' <= now_str <= '1500':
        return True
    return False


def _is_buy_window(now):
    """生产买入委托窗口：盘中 10:00-10:10。"""
    return BUY_WINDOW_START <= now <= BUY_WINDOW_END


# ============================================================
#  文件操作 — 持仓 / 净值 / 成交记录 / 评分历史
# ============================================================

def read_holdings_file(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        result = {}
        with open(filepath, 'r', encoding='gbk') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                code = parts[0]
                highest = float(parts[1]) if len(parts) > 1 and parts[1] else 0
                result[code] = highest
        return result
    except Exception:
        return {}


def write_holdings_file(filepath, holdings):
    try:
        dirname = os.path.dirname(filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(filepath, 'w', encoding='gbk') as f:
            for code in sorted(holdings.keys()):
                highest = holdings[code] if holdings.get(code) else 0
                f.write("%s,%.2f\n" % (code, highest))
    except Exception as e:
        print("  [持仓文件] 写入失败 %s: %s" % (filepath, e))


def get_account_holdings(account_id, account_type='STOCK'):
    holdings = set()
    try:
        positions = get_trade_detail_data(account_id, account_type, 'position')
        for pos in positions:
            if pos.m_nVolume > 0:
                code = "%s.%s" % (pos.m_strInstrumentID, pos.m_strExchangeID)
                holdings.add(code)
    except Exception as e:
        print("  [持仓查询] 失败: %s" % e)
    return holdings


def _sync_holdings_from_account(C, today):
    """用实际账户持仓强制同步 _g_my_codes 与卖出引擎 current_shares。

    修 603618 类残留：卖出反查失败误判后，实盘已清仓但 _g_my_codes 残留占名额。
    - 实际 volume<=0 的 _g_my_codes 票：pop 掉，卖出引擎标 cleared
    - 实际有 volume 但 _g_my_codes 没有的：不自动加入（避免误纳手动仓），只打印诊断
    返回同步后实际有持仓(volume>0)的 code set。
    """
    global _g_my_codes
    if _g_trader is None:
        return set()
    removed = []
    for code in list(_g_my_codes.keys()):
        try:
            pos = _g_trader.get_position(code)
        except Exception:
            pos = None
        vol = pos.get('volume', 0) if pos else 0
        if vol <= 0:
            _g_my_codes.pop(code, None)
            removed.append(code)
            if _g_sell_engine is not None:
                state = _g_sell_engine._states.get(code)
                if state is not None and not state.cleared:
                    state.cleared = True
                    state.cleared_date = today
                    state.current_shares = 0
    if removed:
        print("  [持仓同步] 移除已清仓 %d 只: %s" % (len(removed), sorted(removed)))
        try:
            write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)
        except Exception as e:
            print("  [持仓同步] 写持仓文件失败: %s" % e)
        if _g_sell_engine is not None:
            try:
                _g_sell_engine.save_state()
            except Exception as e:
                print("  [持仓同步] 保存卖出引擎状态失败: %s" % e)
    held = set()
    for code in _g_my_codes.keys():
        try:
            pos = _g_trader.get_position(code)
        except Exception:
            pos = None
        if pos and pos.get('volume', 0) > 0:
            held.add(code)
    return held


def read_nav_file(filepath):
    if not os.path.exists(filepath):
        return 0.0
    try:
        with open(filepath, 'r', encoding='gbk') as f:
            line = f.readline().strip()
            if line:
                return float(line)
        return 0.0
    except Exception as e:
        print("  [净值文件] 读取失败 %s: %s" % (filepath, e))
        return 0.0


def write_nav_file(filepath, cumulative_pnl):
    try:
        dirname = os.path.dirname(filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(filepath, 'w', encoding='gbk') as f:
            f.write("%.2f\n" % cumulative_pnl)
    except Exception as e:
        print("  [净值文件] 写入失败 %s: %s" % (filepath, e))


def calc_floating_pnl(account_id, account_type='STOCK'):
    floating = 0.0
    try:
        positions = get_trade_detail_data(account_id, account_type, 'position')
        for pos in positions:
            volume = getattr(pos, 'm_nVolume', 0)
            can_use = getattr(pos, 'm_nCanUseVolume', 0)
            if volume > 0 and can_use > 0:
                price = getattr(pos, 'm_dPrice', 0)
                open_price = getattr(pos, 'm_dOpenPrice', 0)
                pnl = (price - open_price) * volume
                floating += pnl
    except Exception as e:
        print("  [浮动盈亏] 计算失败: %s" % e)
    return floating


# ============================================================
#  代码转换 / 外部池加载
# ============================================================

def _tq_to_std(tq_code):
    code = str(tq_code).strip()
    if len(code) != 7:
        return None
    market_flag = code[0]
    real_code = code[1:]
    if market_flag == '0':
        return "%s.SZ" % real_code
    elif market_flag == '1':
        return "%s.SH" % real_code
    elif market_flag == '2':
        return "%s.BJ" % real_code
    return None


def _code6_to_std(code6):
    code = str(code6).strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith('6') or code.startswith('5'):
        return "%s.SH" % code
    if code.startswith('688') or code.startswith('689'):
        return "%s.SH" % code
    if code.startswith('0') or code.startswith('002') or code.startswith('003') \
       or code.startswith('300') or code.startswith('301'):
        return "%s.SZ" % code
    if code.startswith('4') or code.startswith('8'):
        return "%s.BJ" % code
    return None


def _parse_pool_line(line):
    text = line.strip()
    if not text:
        return None
    if '\t' in text:
        parts = text.split('\t')
        if len(parts) >= 2:
            code6 = parts[0].strip()
            std = _code6_to_std(code6)
            if std:
                return std
            code6 = parts[1].strip()
            return _code6_to_std(code6)
        return None
    return _tq_to_std(text)


def _load_pool():
    if not os.path.exists(POOL_PATH):
        print("  [外部池] 文件不存在: %s" % POOL_PATH)
        return []
    result = []
    seen_codes = set()
    try:
        with open(POOL_PATH, 'r', encoding='gbk') as f:
            for line in f:
                std_code = _parse_pool_line(line)
                if std_code and std_code not in seen_codes:
                    seen_codes.add(std_code)
                    result.append({
                        'code': std_code,
                        'buy_type': 'pool',
                        'signal': '外部池',
                    })
        print("  [外部池] 读取 %d 只股票（来自 %s）" % (len(result), POOL_PATH))
        for r in result[:10]:
            print("    %s" % r['code'])
        if len(result) > 10:
            print("    ... 还有 %d 只" % (len(result) - 10))
    except Exception as e:
        print("  [外部池] 读取失败: %s" % e)
        return []
    return result


def _is_st_stock(code, C):
    try:
        name = C.get_stock_name(code)
        if name:
            return 'ST' in str(name).upper()
    except Exception:
        pass
    return False


# ============================================================
#  数据加载
# ============================================================

def _load_data(C, dt=None):
    global _g_stock_list, _g_all_data, _g_index_data, _g_scorer

    target_codes = []
    if os.path.exists(POOL_PATH):
        try:
            with open(POOL_PATH, 'r', encoding='gbk') as f:
                for line in f:
                    std_code = _parse_pool_line(line)
                    if std_code:
                        target_codes.append(std_code)
            print("  外部池: %s  -> %d 只目标股票" % (POOL_PATH, len(target_codes)))
        except Exception as e:
            print("  读取外部池失败: %s" % e)
    else:
        print("  WARNING: 外部池文件不存在: %s" % POOL_PATH)

    _g_stock_list = target_codes

    _g_all_data = {}
    total = len(target_codes)
    for i in range(0, total, BATCH_SIZE):
        batch = target_codes[i:i + BATCH_SIZE]
        try:
            data = C.get_market_data_ex(
                stock_code=batch,
                period='1d',
                count=REQUIRED_BARS
            )
            if data:
                _g_all_data.update(data)
        except Exception as e:
            print("  批次 %d-%d 失败: %s" % (i, i + BATCH_SIZE, e))
            continue
        print("  数据加载: %d/%d" % (min(i + BATCH_SIZE, total), total))

    print("  有效数据: %d / %d 只" % (len(_g_all_data), total))

    try:
        idx_data = C.get_market_data_ex(
            stock_code=[MARKET_INDEX_CODE],
            period='1d',
            count=120
        )
        if idx_data and MARKET_INDEX_CODE in idx_data:
            _g_index_data_tmp = idx_data[MARKET_INDEX_CODE]
            if _g_index_data_tmp is not None and not _g_index_data_tmp.empty and 'close' in _g_index_data_tmp.columns:
                _g_index_data = _g_index_data_tmp
                print("  大盘数据: %s 已加载" % MARKET_INDEX_CODE)
            else:
                _g_index_data = None
                print("  大盘数据: %s 无可用数据（回测未包含该指数）" % MARKET_INDEX_CODE)
    except Exception as e:
        print("  大盘数据获取失败: %s" % e)

    # 板块热度 — 优先文件，无则 QMT API 回退
    try:
        bonus_map = _run_sector_analysis(C, dt)
        if bonus_map:
            print("  板块热度映射: %d 只股票获得加分" % len(bonus_map))
            if _g_scorer:
                _g_scorer.update_sector_bonus(bonus_map)
    except Exception as e:
        err = str(e).strip().split('\n')[0]
        print("  板块热度分析跳过: %s" % err)

    _append_log('数据加载: %d只, 大盘%s' % (len(_g_all_data), MARKET_INDEX_CODE))
    print("  数据加载完成")


def _run_sector_analysis(C, dt):
    """板块热度：优先预计算文件，失败则走 QMT API，最后用行情数据兜底。"""
    analyzer = SectorAnalyzer()
    bonus = analyzer.calc_top10(dt=dt)
    if bonus:
        return bonus
    # QMT API fallback
    bonus = _calc_sector_heat_qmt(C, dt)
    if bonus:
        return bonus
    # 最终兜底：基于已加载行情数据模拟板块热度
    return _calc_sector_heat_from_ohlcv()


def _calc_sector_heat_from_ohlcv(lookback=5):
    """基于已加载的日K线数据模拟板块热度。

    对池中每只股票计算 (close[-1] / close[-1-lookback] - 1)，
    按涨幅排序分段赋分：
      - top 20%  → 6-10 分（线性映射）
      - 中间 40% → 1-5 分
      - 底部 40% → 0 分
    若有效样本不足 3 只，返回空。

    返回: {stock_code: heat_score, ...}，code 带后缀如 "000001.SZ"
    """
    global _g_all_data

    if not _g_all_data or len(_g_all_data) < 3:
        return {}

    returns = {}
    for code, df in _g_all_data.items():
        if df is None or len(df) <= lookback:
            continue
        try:
            close_now = float(df['close'].iloc[-1])
            close_before = float(df['close'].iloc[-1 - lookback])
            if close_before > 0:
                ret = (close_now - close_before) / close_before * 100.0
                returns[code] = ret
        except (IndexError, ValueError, TypeError, KeyError):
            continue

    n = len(returns)
    if n < 3:
        print("  [板块] 基于K线兜底：有效样本不足 %d 只，跳过" % n)
        return {}

    sorted_codes = sorted(returns.keys(), key=lambda c: returns[c], reverse=True)
    bottom_n = int(n * 0.4)
    top_n = max(int(n * 0.2), 1)
    mid_n = n - bottom_n - top_n

    heat_map = {}

    # 底部 40% → 0 分
    for code in sorted_codes[top_n + mid_n:]:
        heat_map[code] = 0.0

    # 中间 40% → 1-5 分（线性）
    for i, code in enumerate(sorted_codes[top_n:top_n + mid_n]):
        if mid_n > 1:
            score = 1.0 + (float(i) / (mid_n - 1)) * 4.0
        else:
            score = 3.0
        heat_map[code] = round(score, 1)

    # 顶部 20% → 6-10 分（线性）
    for i, code in enumerate(sorted_codes[:top_n]):
        if top_n > 1:
            score = 6.0 + (float(i) / (top_n - 1)) * 4.0
        else:
            score = 8.0
        heat_map[code] = round(score, 1)

    print("  [板块] 基于K线兜底：%d 只股票，top 5 日涨幅 %.1f%% ~ %.1f%%" % (
        n, returns[sorted_codes[0]], returns[sorted_codes[-1]]))
    return heat_map


def _calc_sector_heat_qmt(C, dt):
    """使用 QMT API 计算板块热度。"""
    print("  [板块] QMT API 计算 D概念 板块热度...")

    sectors = _get_all_d_concept_sectors(C)
    if not sectors:
        print("  [板块] 未找到概念板块数据")
        return {}

    sector_ratios = []
    for sec in sectors:
        try:
            codes = C.get_stock_list_in_sector(sec)
            if not codes or len(codes) < 5:
                continue
            df = C.get_market_data_ex(
                stock_code=codes,
                period='1d',
                count=2
            )
            if not df:
                continue
            total = 0
            up = 0
            for code, data in df.items():
                if data is None or len(data) < 2:
                    continue
                close = float(data['close'].iloc[-1])
                pre_close = float(data['close'].iloc[-2])
                total += 1
                if close > pre_close:
                    up += 1
            if total > 0:
                ratio = float(up) / total
                sector_ratios.append((sec, ratio, codes))
        except Exception:
            continue

    sector_ratios.sort(key=lambda x: x[1], reverse=True)

    bonus_map = {}
    top_n = min(SECTOR_HOT_TOP_N, len(sector_ratios))
    for rank in range(top_n):
        sec_name, ratio, codes = sector_ratios[rank]
        bonus = top_n - rank
        for code in codes:
            if code not in bonus_map:
                bonus_map[code] = bonus
            else:
                bonus_map[code] = max(bonus_map[code], bonus)

    print("  [板块] 排名前%d:" % top_n)
    for rank in range(top_n):
        sec_name, ratio, _ = sector_ratios[rank]
        bonus = top_n - rank
        short_name = sec_name.split('\\')[-1]
        print("    %d. %s  热度=%.2f%%  +%d分" % (rank + 1, short_name, ratio * 100, bonus))

    return bonus_map


def _get_all_d_concept_sectors(C):
    sectors = []
    try:
        all_sectors = C.get_sector_list()
        total = len(all_sectors)
        matched = 0
        for sec in all_sectors:
            if sec.startswith('D概念'):
                sectors.append(sec)
                matched += 1
            elif sec.startswith('概念'):
                sectors.append(sec)
                matched += 1
        print("  [板块] 匹配到 %d 个概念板块 (过滤条件: 'D概念' 或 '概念' 前缀)" % matched)
    except AttributeError:
        pass
    except Exception as e:
        print("  [板块] 获取概念板块列表失败: %s" % e)
    return sectors


def _refresh_trade_data(C):
    global _g_all_data, _g_index_data, _g_stock_list

    target_codes = []
    if os.path.exists(POOL_PATH):
        try:
            with open(POOL_PATH, 'r', encoding='gbk') as f:
                for line in f:
                    std_code = _parse_pool_line(line)
                    if std_code:
                        target_codes.append(std_code)
        except Exception as e:
            print("  读取外部池失败: %s" % e)
    _g_stock_list = target_codes

    all_codes = set(target_codes)
    all_codes.update(_g_my_codes.keys())
    if not all_codes:
        print("  [数据刷新] 无数据需要刷新")
        return

    total = len(all_codes)
    for i in range(0, total, BATCH_SIZE):
        batch = list(all_codes)[i:i + BATCH_SIZE]
        try:
            data = C.get_market_data_ex(
                stock_code=batch,
                period='1d',
                count=REQUIRED_BARS
            )
            if data:
                _g_all_data.update(data)
        except Exception as e:
            print("  数据刷新: 批次 %d-%d 失败: %s" % (i, i + BATCH_SIZE, e))

    try:
        idx_data = C.get_market_data_ex(
            stock_code=[MARKET_INDEX_CODE],
            period='1d',
            count=120
        )
        if idx_data and MARKET_INDEX_CODE in idx_data:
            _g_index_data_tmp = idx_data[MARKET_INDEX_CODE]
            if _g_index_data_tmp is not None and not _g_index_data_tmp.empty and 'close' in _g_index_data_tmp.columns:
                _g_index_data = _g_index_data_tmp
            else:
                _g_index_data = None
    except Exception as e:
        print("  大盘数据刷新失败: %s" % e)

    print("  [数据刷新] 股票池 %d 只 + 持仓 %d 只, 行情已更新" % (len(target_codes), len(_g_my_codes)))


# ============================================================
#  选股 & 打分
# ============================================================

def _score_display(d, key):
    """Format score dimension value as %.2f; keep string defaults (e.g. '--') unchanged."""
    v = d.get(key, '--')
    return "%.2f" % v if isinstance(v, (int, float)) else v


def _calc_buy_bias5(df):
    if df is None or len(df) < 5 or 'close' not in df.columns:
        return 0.0
    close = df['close']
    return calc_bias(safe_last(close), safe_last(ma(close, 5)))


def _passes_buy_bias_filter(code, df, label='买入过滤'):
    bias5 = _calc_buy_bias5(df)
    if bias5 > MAX_BUY_BIAS5:
        print("  [%s] %s MA5乖离率 %.2f%% > %.2f%%，跳过" % (label, code, bias5, MAX_BUY_BIAS5))
        return False
    return True


def _run_selection(C):
    result = []
    for code, df in _g_all_data.items():
        if df is None or len(df) < MIN_BARS:
            continue
        buy, signal, buy_type = check_buy(df)
        if not buy:
            continue
        if not _passes_buy_bias_filter(code, df):
            continue
        if _is_st_stock(code, C):
            continue
        result.append({'code': code, 'buy_type': buy_type, 'signal': signal})

    print("  [选股] %d 只通过信号筛选（已排除ST）" % len(result))
    for r in result[:10]:
        print("    %s  %s  类型=%s" % (r['code'], r['signal'], r['buy_type']))
    if len(result) > 10:
        print("    ... 还有 %d 只" % (len(result) - 10))
    return result


def _fetch_pe_data(stock_code):
    """通过腾讯接口获取PE/PB数据
    返回 (pe_ttm, pe_static, pb, circ_value) 或抛出异常
    """
    import re
    import urllib.request
    code = stock_code.replace('.SH','').replace('.SZ','').replace('.BJ','')
    prefix = 'sh' if code.startswith(('6','9')) else 'sz'
    url = 'https://qt.gtimg.cn/q=' + prefix + code
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    resp = urllib.request.urlopen(req, timeout=5)
    raw = resp.read().decode('gbk')
    vals = raw.split('"')[1].split('~')
    pe_static = float(vals[38]) if len(vals) > 38 and vals[38] else None
    pe_ttm = float(vals[39]) if len(vals) > 39 and vals[39] else None
    pb = float(vals[46]) if len(vals) > 46 and vals[46] else None
    circ_str = vals[44] if len(vals) > 44 and vals[44] else None
    circ_value = None
    if circ_str:
        m = re.match(r'([\d.]+)', circ_str)
        if m:
            num = float(m.group(1))
            if '亿' in circ_str:
                circ_value = num * 1e8
            elif '万' in circ_str:
                circ_value = num * 1e4
            else:
                circ_value = num
    return pe_ttm, pe_static, pb, circ_value


def _run_scoring(C, candidates, dt):
    # 批量获取PE数据
    pe_map = {}
    for s in candidates:
        code = s['code']
        try:
            pe_ttm, pe_static, pb, _ = _fetch_pe_data(code)
            pe_map[code] = {'dynamic_pe': pe_ttm, 'static_pe': pe_static}
        except:
            pe_map[code] = None

    # 计算全池5日收益率
    ret_series_data = {}
    for s in candidates:
        code = s['code']
        df = _g_all_data.get(code)
        if df is not None and len(df) >= 7:
            try:
                ret = float(df['close'].iloc[-1] / df['close'].iloc[-6] - 1)
                ret_series_data[code] = ret
            except:
                pass
    pool_5d_returns = pd.Series(ret_series_data).dropna()

    scored = []
    for s in candidates:
        code = s['code']
        df = _g_all_data.get(code)
        if df is None:
            continue

        try:
            pe_info = pe_map.get(code)
            result = _g_scorer.score_single(
                stock_code=code, df=df,
                dynamic_pe=pe_info['dynamic_pe'] if pe_info else None,
                static_pe=pe_info['static_pe'] if pe_info else None,
                pool_5d_returns=pool_5d_returns,
            )
            scored.append({
                'code': code,
                'score': result['score_total'],
                'raw_score': result['score_total'],
                'signal': s['signal'],
                'buy_type': s['buy_type'],
                'details': result,
            })
        except Exception as e:
            print("    打分异常 %s: %s" % (code, e))
            continue

    scored.sort(key=lambda x: x['score'], reverse=True)

    if scored:
        print("  %s %s %s %s %s %s %s %s %s %s %s 信号" % (
            '排名', '代码', '总分', '突破', '趋势', '回踩', '量价', 'MACD', '估值', '情绪', '板块'))
        print("  " + "-" * 70)
        print("  [打分] 评分器: %s" % _g_scorer.active_name)
        for i, s in enumerate(scored[:10]):
            d = s['details']
            print("  %d  %s  %.2f %s %s %s %s %s %s %.2f %.2f %s" % (
                i + 1, s['code'], s['score'],
                _score_display(d, 'score_breakout'),
                _score_display(d, 'score_trend'),
                _score_display(d, 'score_consolidation'),
                _score_display(d, 'score_volumeprice'),
                _score_display(d, 'score_macd'),
                _score_display(d, 'score_valuation'),
                d.get('score_sentiment', 0),
                d.get('score_sector', 0),
                s['signal']))
        if len(scored) > 10:
            print("  ... 还有 %d 只" % (len(scored) - 10))

    if scored:
        _append_log('6+2评分: %d只完成, 最高=%.2f(%s)' % (len(scored), scored[0]['score'], scored[0]['code']))
    else:
        _append_log('评分: 无结果')
    return scored


# ============================================================
#  价格工具
# ============================================================

def _get_current_price(code, C=None):
    if C is not None:
        try:
            tick = C.get_full_tick([code])
            return _price_from_tick(code, tick)
        except Exception:
            pass
    return _fallback_close_price(code)


def _price_from_tick(code, tick):
    if tick and code in tick and tick[code].get('lastPrice', 0) > 0:
        return float(tick[code]['lastPrice'])
    return None


def _fallback_close_price(code):
    df = _g_all_data.get(code)
    if df is None:
        return None
    return float(df['close'].iloc[-1])


def _get_current_prices(codes, C=None):
    prices = {}
    if C is not None and codes:
        try:
            tick = C.get_full_tick(list(codes))
            for code in codes:
                p = _price_from_tick(code, tick)
                if p and p > 0:
                    prices[code] = p
        except Exception:
            pass
    for code in codes:
        if code not in prices:
            p = _fallback_close_price(code)
            if p and p > 0:
                prices[code] = p
    return prices


def _is_limit_up(code, C):
    try:
        tick = C.get_full_tick([code])
        if tick and code in tick:
            last = float(tick[code].get('lastPrice', 0))
            pre = float(tick[code].get('preClose', 0))
            if last > 0 and pre > 0:
                pct = (last - pre) / pre * 100
                base = code.split('.')[0]
                if code.endswith('.BJ'):
                    return pct >= 29.5
                if base.startswith('688') or base.startswith('689') \
                   or base.startswith('300') or base.startswith('301'):
                    return pct >= 19.5
                return pct >= 9.5
    except Exception:
        pass
    df = _g_all_data.get(code)
    if df is not None and len(df) >= 2:
        close = float(df['close'].iloc[-1])
        pre_close = float(df['close'].iloc[-2])
        if pre_close > 0:
            pct = (close - pre_close) / pre_close * 100
            base = code.split('.')[0]
            if code.endswith('.BJ'):
                return pct >= 29.5
            if base.startswith('688') or base.startswith('689') \
               or base.startswith('300') or base.startswith('301'):
                return pct >= 19.5
            return pct >= 9.5
    return False


def _is_limit_down(code, C):
    try:
        tick = C.get_full_tick([code])
        if tick and code in tick:
            last = float(tick[code].get('lastPrice', 0))
            pre = float(tick[code].get('preClose', 0))
            if last > 0 and pre > 0:
                pct = (last - pre) / pre * 100
                base = code.split('.')[0]
                if code.endswith('.BJ'):
                    return pct <= -29.5
                if base.startswith('688') or base.startswith('689') \
                   or base.startswith('300') or base.startswith('301'):
                    return pct <= -19.5
                return pct <= -9.5
    except Exception:
        pass
    df = _g_all_data.get(code)
    if df is not None and len(df) >= 2:
        close = float(df['close'].iloc[-1])
        pre_close = float(df['close'].iloc[-2])
        if pre_close > 0:
            pct = (close - pre_close) / pre_close * 100
            base = code.split('.')[0]
            if code.endswith('.BJ'):
                return pct <= -29.5
            if base.startswith('688') or base.startswith('689') \
               or base.startswith('300') or base.startswith('301'):
                return pct <= -19.5
            return pct <= -9.5
    return False


# ============================================================
#  诊断打印
# ============================================================

def print_sell_diagnostics(holdings_dict, all_data, sell_engine, trader):
    if not holdings_dict:
        return

    print("\n  ┌─ 分层卖出诊断 " + "-" * 50)
    print("  │ %s %s %s %s %s %s %s" % (
        '代码', '成本', '现价', '盈亏', '层', '状态', '信号'))

    for code in sorted(holdings_dict.keys()):
        df = all_data.get(code)
        if df is None:
            continue
        close = df['close'].astype(float)
        current_price = float(close.iloc[-1])

        state = sell_engine._states.get(code)
        if state is None:
            layer_display = "正常"
            status = "持有"
            signals = ""
        else:
            if state.cleared:
                layer_display = "清仓层"
                status = "已清仓(%s)" % state.cleared_date
                signals = ""
            elif state.confirm_reduced:
                layer_display = "确认层"
                status = "已减仓50%"
                signals = state.confirm_reason
            elif state.warning_reduced:
                layer_display = "预警层"
                status = "已减仓30%%(%s)" % state.warning_trigger_date
                signals = state.warning_reason
            else:
                layer_display = "正常"
                status = "持有"
                signals = ""

        cost_price = state.cost_price if state else 0
        if cost_price > 0:
            profit_pct = (current_price - cost_price) / cost_price
            profit_str = "%+.1f%%" % (profit_pct * 100)
        else:
            profit_str = "--"

        print("  │ %s %8.2f %8.2f %s %s %s %s" % (
            code, cost_price, current_price,
            profit_str, layer_display, status, signals))

    print("  └" + "-" * 55)


def _print_holdings_report(C, today):
    global _g_my_codes, _g_sell_engine, _g_all_data, _g_index_data, _g_scorer
    print("\n" + "=" * 55)
    print("  持仓收盘报告 %s" % today)
    print("=" * 55)

    策略持仓 = _g_my_codes or {}
    print("\n  【盘前持仓】%d 只" % len(策略持仓))
    if 策略持仓:
        for idx, code in enumerate(sorted(策略持仓.keys()), 1):
            name = _get_stock_name_safe(C, code)
            state = _g_sell_engine._states.get(code) if _g_sell_engine else None
            reason = get_trade_state_reason(state)
            _append_log('持仓报告: %s %s %s' % (code, name, reason))
            print("  %d. %s  %s  %s" % (idx, code, name, reason))
    else:
        print("  (空)")

    try:
        账户持仓 = get_account_holdings(ACCOUNT_ID)
    except Exception:
        账户持仓 = set()
    print("\n  【账户持仓】%d 只" % len(账户持仓))
    if 账户持仓:
        for idx, code in enumerate(sorted(账户持仓), 1):
            name = _get_stock_name_safe(C, code)
            in_strategy = "★策略" if code in 策略持仓 else "其他"
            print("  %d. %s  %s  %s" % (idx, code, name, in_strategy))
    else:
        print("  (空)")

    策略数 = len(策略持仓)
    账户数 = len(账户持仓)
    print("\n  策略跟踪: %d 只 | 账户持有: %d 只" % (策略数, 账户数))

    # 评分对比 & 换股建议
    need_codes = list(策略持仓.keys())
    try:
        if os.path.exists(POOL_PATH):
            with open(POOL_PATH, 'r', encoding='gbk') as f:
                for line in f:
                    std_code = _parse_pool_line(line)
                    if std_code:
                        need_codes.append(std_code)
    except Exception:
        pass

    missing = [c for c in need_codes if c not in (_g_all_data or {})]
    if missing:
        try:
            batch = list(set(missing))
            for i in range(0, len(batch), BATCH_SIZE):
                sub = batch[i:i + BATCH_SIZE]
                data = C.get_market_data_ex(stock_code=sub, period='1d', count=REQUIRED_BARS)
                if data:
                    if _g_all_data is None:
                        _g_all_data = {}
                    _g_all_data.update(data)
            if _g_index_data is None:
                idx = C.get_market_data_ex(stock_code=[MARKET_INDEX_CODE], period='1d', count=120)
                if idx:
                    _g_index_data = idx.get(MARKET_INDEX_CODE)
        except Exception:
            pass

    if not _g_all_data:
        print("=" * 55 + "\n")
        return

    held_codes = sorted(策略持仓.keys())
    held_scores = {}
    if held_codes:
        for code in held_codes:
            df = _g_all_data.get(code)
            if df is None or len(df) < 60:
                continue
            try:
                r = _g_scorer.score_single(stock_code=code, df=df)
                held_scores[code] = r
            except Exception:
                continue

    candidate_scores = []
    try:
        pool_codes = []
        if os.path.exists(POOL_PATH):
            with open(POOL_PATH, 'r', encoding='gbk') as f:
                for line in f:
                    std_code = _parse_pool_line(line)
                    if std_code and std_code not in held_codes:
                        pool_codes.append(std_code)

        if pool_codes:
            for code in pool_codes:
                df = _g_all_data.get(code)
                if df is None or len(df) < 60:
                    continue
                if not _passes_buy_bias_filter(code, df, label='换股候选过滤'):
                    continue
                try:
                    r = _g_scorer.score_single(stock_code=code, df=df)
                    name = _get_stock_name_safe(C, code)
                    candidate_scores.append((code, name, r))
                except Exception:
                    continue

            candidate_scores.sort(key=lambda x: x[2]['score_total'], reverse=True)
    except Exception:
        pass

    print("\n  ┌─ 评分对比与换股建议 " + "-" * 40)
    print("  │ %s %s %s %s %s %s %s %s %s %s %s %s" % (
        '类型', '代码', '名称', '总分', '突破', '趋势', '回踩', '量价', 'MACD', '估值', '情绪', '板块'))
    print("  │ " + "-" * 90)

    if held_scores:
        for code in held_codes:
            r = held_scores.get(code)
            if r is None:
                continue
            name = _get_stock_name_safe(C, code)
            print("  │ %s %s %s %.2f %s %s %s %s %s %s %.2f %.2f" % (
                '持仓', code, name,
                r.get('score_total', 0),
                _score_display(r, 'score_breakout'),
                _score_display(r, 'score_trend'),
                _score_display(r, 'score_consolidation'),
                _score_display(r, 'score_volumeprice'),
                _score_display(r, 'score_macd'),
                _score_display(r, 'score_valuation'),
                r.get('score_sentiment', 0),
                r.get('score_sector', 0)))

    if candidate_scores:
        top_n = min(5, len(candidate_scores))
        for code, name, r in candidate_scores[:top_n]:
            print("  │ %s %s %s %.2f %s %s %s %s %s %s %.2f %.2f" % (
                '候选', code, name,
                r.get('score_total', 0),
                _score_display(r, 'score_breakout'),
                _score_display(r, 'score_trend'),
                _score_display(r, 'score_consolidation'),
                _score_display(r, 'score_volumeprice'),
                _score_display(r, 'score_macd'),
                _score_display(r, 'score_valuation'),
                r.get('score_sentiment', 0),
                r.get('score_sector', 0)))

    print("  │ " + "-" * 90)

    swap_suggestions = []
    for code in held_codes:
        hr = held_scores.get(code)
        if hr is None:
            continue
        h_score = hr.get('score_total', 0)

        if h_score >= 60:
            swap_suggestions.append((code, h_score, None, 0, "评分健康，继续持有"))
            continue

        best_gap = 0
        best_cand = None
        for cand_code, cand_name, cr in candidate_scores:
            gap = cr.get('score_total', 0) - h_score
            if gap >= 12 and gap > best_gap:
                best_gap = gap
                best_cand = (cand_code, cand_name, cr.get('score_total', 0))
        if best_cand:
            swap_suggestions.append((code, h_score, best_cand, best_gap,
                "建议换股 -> %s (%s, %.2f分)" % (best_cand[0], best_cand[1], best_cand[2])))
        else:
            swap_suggestions.append((code, h_score, None, 0, "评分偏低，但无合适候选"))

    if swap_suggestions:
        print("  │  换股建议:")
        for code, h_score, cand, gap, advice in swap_suggestions:
            name = _get_stock_name_safe(C, code)
            symbol = "->" if cand else chr(0x2713)
            print("  │    %s %s %s %.2f  %s" % (symbol, code, name, h_score, advice))
            _append_log('平仓委托: %s %s, 原因=%s' % (code, name, advice))

    print("  └" + "-" * 55)

    # 方案B持仓诊断
    if _g_sell_engine and _g_my_codes:
        diagnosis_list = []
        for code in sorted(_g_my_codes.keys()):
            df = _g_all_data.get(code)
            if df is None or len(df) < 5:
                continue
            try:
                pos = _g_trader.get_position(code)
            except Exception:
                pos = None
            if pos is None:
                cp = float(df['close'].astype(float).iloc[-1])
                cost = 0
                hp = _g_my_codes.get(code, cp)
            else:
                cp = float(df['close'].astype(float).iloc[-1])
                cost = pos.get('cost', 0)
                hp = max(pos.get('cost', 0), cp)
            try:
                diag = _g_sell_engine.diagnose_position(code, df, cost, cp, hp)
                diagnosis_list.append(diag)
            except Exception as e:
                err = str(e).strip().split('\n')[0]
                print("  [诊断异常] %s: %s" % (code, err))
                continue
        if diagnosis_list:
            for line in format_plan_b_diagnosis(diagnosis_list, today):
                print(line)

    print("=" * 55 + "\n")

    # Write daily log after holdings report
    _write_daily_log(today, C)


def _write_daily_log(today, C):
    global _g_log_written_today, _g_log_entries, _g_trade_records, _g_my_codes
    global _g_all_data, _g_scorer, _g_sell_engine, _g_trader, _g_cumulative_pnl

    if _g_log_written_today:
        return
    _g_log_written_today = True

    weekday_names = ['星期一','星期二','星期三','星期四','星期五','星期六','星期日']
    try:
        dt = datetime.strptime(today, '%Y%m%d')
        date_str = dt.strftime('%Y-%m-%d') + ' ' + weekday_names[dt.weekday()]
    except Exception:
        date_str = today

    lines = []
    line_width = 66
    sep = '─' * 44

    # ┌─ Header ─┐
    top = '┌' + '─' * line_width + '┐'
    bot = '└' + '─' * line_width + '┘'
    bar = '│'
    lines.append(top)
    title = '策略执行日志 . ' + STRATEGY_NAME
    lines.append(bar + title.center(line_width) + bar)
    lines.append(bar + date_str.center(line_width) + bar)
    lines.append(bot)
    lines.append('')

    # 一、运行环境
    lines.append(sep)
    lines.append(' 一、运行环境')
    lines.append(sep)
    debug_status = '开启' if DEBUG_MODE else '关闭'
    test_status = '开启·全天候交易' if TEST_MODE else ('开启' if DEBUG_MODE else '关闭')
    lines.append(' 账号        ' + ACCOUNT_ID + '（模拟端）')
    lines.append(' 策略本金    ' + '{:,}'.format(STRATEGY_CAPITAL))
    lines.append(' 评分器      6+2 全维度')
    lines.append(' 调试模式    ' + debug_status)
    lines.append(' 测试模式    ' + test_status)
    lines.append('')

    # 二、执行过程
    lines.append(sep)
    lines.append(' 二、执行过程')
    lines.append(sep)
    lines.append('')
    if _g_log_entries:
        for ts, msg in _g_log_entries:
            lines.append(' [' + ts + '] ' + msg)
    else:
        lines.append(' （无执行记录）')
    lines.append('')

    # 三、委托成交汇总
    lines.append(sep)
    lines.append(' 三、委托成交汇总')
    lines.append(sep)
    lines.append('')
    if _g_trade_records:
        lines.append(' 类型  代码        方向  数量    价格      金额      状态')
        lines.append(' ' + '─' * 50)
        for r in _g_trade_records:
            amount_str = '{:,}'.format(int(r['amount'])) if r['amount'] else '0'
            lines.append(' ' + r['type'] + '  ' + r['code'].ljust(10) + ' ' + r['direction'] + '   ' +
                        str(r['volume']).rjust(5) + '  ' + '{:.2f}'.format(r['price']).rjust(7) + '  ' +
                        amount_str.rjust(9) + '  ' + r['status'])
    else:
        lines.append(' （无委托记录）')
    lines.append('')

    # 四、持仓经济指标
    lines.append(sep)
    lines.append(' 四、持仓经济指标')
    lines.append(sep)
    lines.append('')
    if _g_my_codes:
        for code in sorted(_g_my_codes.keys()):
            name = _get_stock_name_safe(C, code)
            lines.append(' ' + code + '  ' + name)
            lines.append(' ' + '─' * 50)

            df = _g_all_data.get(code)
            current_price = 0.0
            if df is not None:
                current_price = float(df['close'].astype(float).iloc[-1])

            cost_price = 0.0
            state = _g_sell_engine._states.get(code) if _g_sell_engine else None
            if state:
                cost_price = state.cost_price

            profit_str = '--'
            if cost_price > 0 and current_price > 0:
                profit_pct = (current_price - cost_price) / cost_price * 100
                profit_str = '%+.1f%%' % profit_pct

            cost_str = '{:.2f}'.format(cost_price) if cost_price > 0 else '--'
            cur_str = '{:.2f}'.format(current_price) if current_price > 0 else '--'
            lines.append(' 成本' + cost_str + '  现价' + cur_str + '  盈亏' + profit_str)
            lines.append(' ' + '─' * 50)

            # Score dimensions
            if _g_scorer is not None and df is not None:
                try:
                    r = _g_scorer.score_single(stock_code=code, df=df)
                    brk = '{:.2f}'.format(r.get('score_breakout', 0))
                    trd = '{:.2f}'.format(r.get('score_trend', 0))
                    cns = '{:.2f}'.format(r.get('score_consolidation', 0))
                    vp = '{:.2f}'.format(r.get('score_volumeprice', 0))
                    macd = '{:.2f}'.format(r.get('score_macd', 0))
                    val = '{:.2f}'.format(r.get('score_valuation', 0))
                    sent = '{:.2f}'.format(r.get('score_sentiment', 0))
                    sec = '{:.2f}'.format(r.get('score_sector', 0))
                    total = '{:.2f}'.format(r.get('score_total', 0))
                    lines.append(' 评分: 突破' + brk + ' 趋势' + trd + ' 盘整' + cns + ' 量价' + vp)
                    lines.append('       MACD' + macd + ' 估值' + val + ' 情绪' + sent + ' 板块' + sec)
                    lines.append(' 总分: ' + total)
                    lines.append(' ' + '─' * 50)
                except Exception:
                    pass

            # Risk status
            risk_parts = ['底线层' + ('×' if not state or not state.cleared else '√')]
            risk_parts.append('预警层' + ('×' if not state or not state.warning_reduced else '√'))
            risk_parts.append('确认层' + ('×' if not state or not state.confirm_reduced else '√'))
            risk_parts.append('清仓层' + ('×' if not state or not state.cleared else '√'))
            lines.append(' 风控: ' + ' '.join(risk_parts))
            lines.append('')
    else:
        lines.append(' （无持仓）')
        lines.append('')

    # 五、账户汇总
    lines.append(sep)
    lines.append(' 五、账户汇总')
    lines.append(sep)
    lines.append('')

    total_asset = 0.0
    available_cash = 0.0
    holdings_value = 0.0
    try:
        if _g_trader:
            total_asset = _g_trader.get_total_asset()
            available_cash = _g_trader.get_available_cash()
            positions = _g_trader.get_holdings()
            for code, pos in positions.items():
                df = _g_all_data.get(code)
                if df is not None:
                    price = float(df['close'].astype(float).iloc[-1])
                    holdings_value += pos.get('volume', 0) * price
    except Exception:
        # Fallback: estimate from _g_my_codes
        for code in _g_my_codes:
            df = _g_all_data.get(code)
            if df is not None:
                price = float(df['close'].astype(float).iloc[-1])
                pos = _g_trader or None
                holdings_value += price * 100  # rough estimate
        total_asset = STRATEGY_CAPITAL + _g_cumulative_pnl
        available_cash = total_asset - holdings_value

    total_pnl = _g_cumulative_pnl
    if total_asset > 0:
        pnl_pct = total_pnl / total_asset * 100
        pos_ratio = holdings_value / total_asset * 100 if total_asset > 0 else 0
        cash_ratio = available_cash / total_asset * 100 if total_asset > 0 else 0
        lines.append(' 总资产    ' + '{:,}'.format(int(total_asset)) + '   (' + '%+.1f%%' % pnl_pct + ')')
        lines.append(' 持仓市值  ' + '{:,}'.format(int(holdings_value)) + '    (' + '%.1f%%' % pos_ratio + ')')
        lines.append(' 可用资金  ' + '{:,}'.format(int(available_cash)) + '    (' + '%.1f%%' % cash_ratio + ')')
    else:
        nav = STRATEGY_CAPITAL + total_pnl
        pnl_pct = total_pnl / STRATEGY_CAPITAL * 100 if STRATEGY_CAPITAL > 0 else 0
        lines.append(' 总资产    ' + '{:,}'.format(int(nav)) + '   (' + '%+.1f%%' % pnl_pct + ')')

    lines.append(' 持仓数量  ' + str(len(_g_my_codes)) + ' 只')
    lines.append(' 总盈亏    ' + '{:+,}'.format(int(total_pnl)))
    lines.append('')

    now_str = _market_now(C).strftime('%Y-%m-%d %H:%M')
    lines.append(' 日志生成: ' + now_str)
    lines.append(bot)

    content = '\n'.join(lines)

    log_path = 'D:/QMT_POOL/strategy_log_' + today + '.txt'
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w', encoding='gbk') as f:
            f.write(content + '\n')
        print('  [日志] 已写出: ' + log_path)
    except Exception as e:
        print('  [日志] 写入失败: ' + str(e))


# ============================================================
#  分时段卖出控制（P1 声明，P2 接通）
# ============================================================

def _get_allowed_sell_layers(now):
    """根据当前时点决定本轮允许哪些 sell decision triggered_layer 通过。

    返回 dict:
        {'layers': set[str],           # 允许的 layer 白名单
         'exclude_sublayers': set[str]} # 排除的 sublayer 黑名单
    layers 为空集表示本时段不允许任何卖出。
    """
    if now < '0925':
        return {'layers': set(), 'exclude_sublayers': set()}
    if now < '0930':
        return {'layers': set(), 'exclude_sublayers': set()}
    if now < '0935':
        return {'layers': {'底线层'}, 'exclude_sublayers': set()}
    if now < '0940':
        return {'layers': {'底线层', '清仓层'}, 'exclude_sublayers': {'trailing'}}
    if now < '1440':
        return {'layers': {'底线层', '清仓层', '预警层', '确认层', 'warning_add'},
                'exclude_sublayers': set()}
    if now < '1458':
        return {'layers': {'底线层', '清仓层', '预警层', '确认层', 'warning_add'},
                'exclude_sublayers': set()}
    return {'layers': set(), 'exclude_sublayers': set()}


def _is_in_cooling_off():
    """策略启动后 60 秒内屏蔽所有交易。
    P1 只声明不调用，P2 接通 handlebar。
    """
    if _g_strategy_start_ts is None:
        return False
    return (time.time() - _g_strategy_start_ts) < 60


def _get_premarket_ref_price(C, code):
    """取集合竞价撮合参考价 + 前一交易日收盘价。
    返回 (ref_price, prev_close)；任一取不到返回 (None, None)。

    注：09:25 撮合后 QMT 日 K close 字段是否反映撮合价需实盘验证。
    若不行回退用 lastPrice，单独 commit 处理。
    """
    if C is None:
        return None, None
    try:
        data = C.get_market_data_ex(['close'], [code], period='1d', count=2)
    except Exception:
        return None, None
    if not data or code not in data:
        return None, None
    df = data[code]
    if df is None or len(df) < 2:
        return None, None
    try:
        prev_close = float(df['close'].iloc[-2])
        ref_price = float(df['close'].iloc[-1])
    except Exception:
        return None, None
    if ref_price <= 0 or prev_close <= 0:
        return None, None
    return ref_price, prev_close


def _log_premarket_diagnostic(C, today, now):
    """P3 观察期: 把 09:25 日K close[-1]/close[-2] 与 tick lastPrice/preClose 写到
    D:\\QMT_POOL\\premarket_diag_YYYYMMDD.csv 用于验证 close[-1] 是否反映撮合价。
    每天只写一次（由 _g_premarket_check_done 守护，调用方负责）。
    异常不抛，只打印。
    """
    if C is None or not _g_my_codes:
        return
    try:
        codes = list(_g_my_codes.keys())
        md = {}
        try:
            md = C.get_market_data_ex(['close'], codes, period='1d', count=2) or {}
        except Exception as e:
            print("    [P3诊断] get_market_data_ex 异常: %s" % e)
        tick = {}
        try:
            tick = C.get_full_tick(codes) or {}
        except Exception as e:
            print("    [P3诊断] get_full_tick 异常: %s" % e)

        path = 'D:/QMT_POOL/premarket_diag_%s.csv' % today
        write_header = not os.path.exists(path)
        try:
            f = open(path, 'a')
            try:
                if write_header:
                    f.write('timestamp,today,now,code,md_close_minus_1,md_close_minus_2,tick_lastPrice,tick_preClose,tick_open,tick_high,tick_low\n')
                ts = _market_now(C).strftime('%Y-%m-%d %H:%M:%S')
                for code in codes:
                    md_c1 = ''
                    md_c2 = ''
                    df = md.get(code) if md else None
                    if df is not None and len(df) >= 2:
                        try:
                            md_c1 = '%.4f' % float(df['close'].iloc[-1])
                            md_c2 = '%.4f' % float(df['close'].iloc[-2])
                        except Exception:
                            pass
                    t = tick.get(code, {}) if tick else {}
                    last_p = t.get('lastPrice', '')
                    pre_c = t.get('preClose', '')
                    op = t.get('open', '')
                    hi = t.get('high', '')
                    lo = t.get('low', '')
                    f.write('%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n'
                            % (ts, today, now, code, md_c1, md_c2, last_p, pre_c, op, hi, lo))
            finally:
                f.close()
            print("    [P3诊断] 已写 %s (%d 只)" % (path, len(codes)))
        except Exception as e:
            print("    [P3诊断] 写文件异常: %s" % e)
    except Exception as e:
        print("    [P3诊断] 整体异常: %s" % e)


def _check_pre_market_hard_stop(C, today, now):
    """09:25-09:29:59 集合竞价锁定区扫描持仓，按 grade 决定是否预埋硬止损单。
    单日只跑一次，由 _g_premarket_check_done 守护。
    """
    global _g_premarket_check_done, _g_premarket_orders

    if _g_premarket_check_done:
        return

    # P3 观察期: 不论模式都先写诊断 CSV (每日一次，由 _g_premarket_check_done 守护)
    _log_premarket_diagnostic(C, today, now)

    if PREMARKET_HARD_STOP_MODE == 'OFF':
        _g_premarket_check_done = True
        print("  [%s] 集合竞价预埋: 模式 OFF, 跳过 (诊断已写)" % STRATEGY_NAME)
        return
    if _g_sell_engine is None or not _g_my_codes:
        _g_premarket_check_done = True
        return

    HARD_LOSS = -0.05
    HARD_DAILY = -0.07

    print("  [%s] 集合竞价预埋扫描 (mode=%s) ..." % (STRATEGY_NAME, PREMARKET_HARD_STOP_MODE))

    for code in list(_g_my_codes.keys()):
        try:
            ref_price, prev_close = _get_premarket_ref_price(C, code)
        except Exception as e:
            print("    [预埋扫描] %s 取参考价异常: %s" % (code, e))
            continue
        if not ref_price or not prev_close:
            continue

        state = _g_sell_engine._states.get(code)
        cost_price = state.cost_price if state else 0.0
        if cost_price <= 0:
            cost_price = _g_my_codes.get(code, 0) or 0.0
        if cost_price <= 0:
            continue

        daily_drop = (ref_price - prev_close) / prev_close
        cum_pnl = (ref_price - cost_price) / cost_price

        if cum_pnl <= HARD_LOSS or daily_drop <= HARD_DAILY:
            grade = 'G3'
        elif daily_drop <= -0.05 and cum_pnl <= HARD_LOSS + 0.02:
            grade = 'G2'
        elif daily_drop <= -0.03:
            grade = 'G1'
        else:
            grade = 'G0'

        pos = _g_trader.get_position(code) if _g_trader else None
        shares = (pos.get('volume', 0) if pos else 0)
        print("    [预埋扫描] %s grade=%s ref=%.2f prev=%.2f drop=%.2f%% pnl=%.2f%% shares=%d"
              % (code, grade, ref_price, prev_close, daily_drop * 100, cum_pnl * 100, shares))

        sell_vol = _normalize_sell_volume_for_board(code, shares, shares, True)
        if sell_vol <= 0:
            continue
        if grade in ('G0', 'G1'):
            continue
        if grade == 'G2' and PREMARKET_HARD_STOP_MODE != 'G2_AND_G3':
            continue

        if grade == 'G3':
            limit_price = round(prev_close * 0.91, 2)
        else:
            limit_price = round(ref_price * 0.99, 2)

        order_id = None
        try:
            if hasattr(_g_trader, 'sell_limit_price'):
                order_id = _g_trader.sell_limit_price(code, sell_vol, limit_price,
                                                      remark='预埋%s' % grade)
            else:
                order_id = _g_trader._passorder(
                    _g_trader.SELL_CODE, code, sell_vol,
                    '预埋%s' % grade, price_type=0, price=limit_price)
        except Exception as e:
            print("    [预埋下单异常] %s grade=%s: %s" % (code, grade, e))
            order_id = None

        if order_id is not None:
            _g_premarket_orders[code] = {
                'order_id': order_id, 'grade': grade,
                'price': limit_price, 'shares': sell_vol,
                'ref_price': ref_price,
            }
            print("    [预埋下单] %s grade=%s %d股@%.2f order=%s"
                  % (code, grade, sell_vol, limit_price, order_id))
            _append_log('集合竞价预埋: %s grade=%s %d股@%.2f' % (code, grade, sell_vol, limit_price))
        else:
            print("    [预埋失败] %s grade=%s" % (code, grade))

    _g_premarket_check_done = True
    print("  [%s] 集合竞价预埋扫描完成 (下单 %d 只)"
          % (STRATEGY_NAME, len(_g_premarket_orders)))


# ============================================================
#  卖出数量合法性
# ============================================================

def _is_star_market_stock(code):
    base = str(code).upper()
    if '.' in base:
        base = base.split('.')[0]
    if base.startswith('SH') or base.startswith('SZ'):
        base = base[2:]
    return base.startswith('688') or base.startswith('689')


def _min_sell_volume_for_board(code):
    if _is_star_market_stock(code):
        return 200
    return 100


def _normalize_sell_volume_for_board(code, desired_vol, available_vol, is_clear=False):
    available_vol = int(available_vol)
    desired_vol = int(desired_vol)
    if available_vol <= 0:
        return 0
    if is_clear:
        return available_vol
    if _is_star_market_stock(code):
        if available_vol < 200:
            return available_vol
        if desired_vol < 200:
            return min(200, available_vol)
        return min(desired_vol, available_vol)
    if desired_vol >= 100:
        lot = (min(desired_vol, available_vol) // 100) * 100
        return lot
    if available_vol < 100:
        return available_vol
    return 0


# ============================================================
#  卖出集成
# ============================================================

def _check_and_execute_sell(C, today, allowed_layers=None):
    global _g_sell_engine, _g_pending_sells, _g_last_sell_fingerprint, _g_sell_skip_printed, _g_failed_printed
    global _g_timegate_skip_printed

    if _g_sell_engine is None:
        return []

    # 构建持仓数据供引擎使用（替代 trader.get_position 内部调用）
    positions_data = {}
    for code in _g_my_codes:
        pos = _g_trader.get_position(code)
        if pos:
            positions_data[code] = pos

    rt_prices = _get_current_prices(list(_g_my_codes.keys()), C)
    raw_decisions = _g_sell_engine.evaluate(today, _g_my_codes, _g_all_data, positions_data, rt_prices)

    # ===== P2: 时段路由过滤 =====
    if allowed_layers is not None:
        layers_set = allowed_layers.get('layers', set())
        exclude_subs = allowed_layers.get('exclude_sublayers', set())
        filtered = []
        for code, dec, shares in raw_decisions:
            if dec.triggered_layer not in layers_set:
                skey = ('layer', code, dec.triggered_layer)
                if skey not in _g_timegate_skip_printed:
                    _g_timegate_skip_printed.add(skey)
                    print("  [时段拦截] %s reason=%s layer=%s 不在 %s 允许范围"
                          % (code, dec.reason, dec.triggered_layer, sorted(layers_set)))
                continue
            sub = getattr(dec, 'triggered_sublayer', None)
            if sub and sub in exclude_subs:
                skey = ('sublayer', code, sub)
                if skey not in _g_timegate_skip_printed:
                    _g_timegate_skip_printed.add(skey)
                    print("  [时段拦截|sublayer] %s reason=%s sublayer=%s 在 %s 排除列表"
                          % (code, dec.reason, sub, sorted(exclude_subs)))
                continue
            filtered.append((code, dec, shares))
        raw_decisions = filtered

    # 防刷屏：卖出决策变化时才打印诊断表
    if raw_decisions:
        fp = '|'.join('%s:%d:%.2f' % (c, int((d.sell_pct or 0) * 100), s) for c, d, s in raw_decisions)
        if fp != _g_last_sell_fingerprint:
            _g_last_sell_fingerprint = fp
            print_sell_diagnostics(_g_my_codes, _g_all_data, _g_sell_engine, _g_trader)
    else:
        _g_last_sell_fingerprint = ''

    sells = []
    now_ts = time.time()
    for code, dec, shares in raw_decisions:
        # 卖出失败冷却检查
        last_fail = _g_sell_fail_cooldown.get(code, 0)
        if now_ts - last_fail < 60:
            if code not in _g_sell_skip_printed:
                _g_sell_skip_printed.add(code)
                print("  [冷却] %s 卖出失败未满60秒，跳过" % code)
            sells.append({'code': code, 'reasons': [dec.reason], 'pct': dec.sell_pct, 'volume': 0})
            continue

        if code in _g_pending_sells:
            if code not in _g_sell_skip_printed:
                _g_sell_skip_printed.add(code)
                print("  [跳过] %s 已有待成交卖出订单" % code)
            sells.append({'code': code, 'reasons': [dec.reason], 'pct': dec.sell_pct, 'volume': 0})
            continue

        pos = _g_trader.get_position(code)
        available = pos['can_use'] if pos else shares
        is_clear = (dec.action == Action.CLEAR)
        sell_vol = _normalize_sell_volume_for_board(code, shares, available, is_clear)
        if sell_vol <= 0:
            if code not in _g_sell_skip_printed:
                _g_sell_skip_printed.add(code)
                print("  [卖出跳过] %s 数量不满足最低委托量 desired=%d available=%d" % (code, shares, available))
            continue

        price = _get_current_price(code, C)
        if not price or price <= 0:
            if code not in _g_price_skip_printed:
                _g_price_skip_printed.add(code)
                print("  [卖出跳过] %s 无法获取当前价" % code)
            continue

        order_id = _g_trader.sell(code, sell_vol, remark='卖出简易')
        if order_id is not None:
            state_obj = _g_sell_engine._states.get(code)
            _g_pending_sells[code] = {
                'order_id': order_id,
                'volume': sell_vol,
                'sell_price': price,
                'cost': state_obj.cost_price if state_obj else 0,
                'pct': dec.sell_pct,
                'checks': 0,
                'retries': 0,
                'is_clear': is_clear,
                'code': code,
                'today': today,
            }
            print("    [卖出委托] %s %d股 价格=%.2f  原因=%s" % (code, sell_vol, price, dec.reason))
            _append_log('卖出委托: %s %d股, 原因=%s' % (code, sell_vol, dec.reason))
            sells.append({'code': code, 'reasons': [dec.reason], 'pct': dec.sell_pct, 'volume': sell_vol})
        else:
            _g_failed_printed.add(code)
            _g_sell_fail_cooldown[code] = now_ts
            print("    [卖出委托失败] %s %d股  原因=%s (60秒冷却)" % (code, sell_vol, dec.reason))

    return sells


def _confirm_engine_clear(code, today, info):
    global _g_sell_engine
    if info.get('is_clear') and _g_sell_engine is not None:
        _g_sell_engine.confirm_clear(code, today)


def _check_pending_sells(C, today):
    global _g_pending_sells, _g_pending_limitdown_sells, _g_cumulative_pnl

    if C is None:
        return

    if not _g_pending_sells:
        return

    # 非交易时间跳过撤单重试
    dt = _get_qmt_time(C)
    if not _is_trading_time(dt):
        return

    try:
        orders = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'order')
    except Exception as e:
        print("  [待卖出] 查询订单失败: %s" % e)
        return

    for code, info in list(_g_pending_sells.items()):
        found_order = None
        for o in orders:
            inst = o.m_strInstrumentID
            ex = o.m_strExchangeID
            oc = "%s.%s" % (inst, ex)
            oid = getattr(o, 'm_nOrderID', None)
            if oc == code and oid is not None and oid == info['order_id']:
                found_order = o
                break

        if found_order is None:
            if info.get('order_id') is None:
                print("  [卖出清理] %s 订单号无效(%s)，清理" % (code, info.get('order_id')))
                _g_pending_sells.pop(code, None)
                _g_my_codes.pop(code, None)
                try:
                    write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)
                except Exception as e:
                    print("  [持仓清理] 写 holdings 文件失败: %s" % e)
                continue
            # 反查失败兜底：先查实际持仓再判成败，避免误撤活着的限价卖单
            pos = _g_trader.get_position(code)
            actual_vol = pos.get('volume', 0) if pos else 0
            ordered_vol = info.get('volume', 0)
            already_traded = info.get('already_traded', 0)
            prev_vol = ordered_vol + already_traded  # 委托前持仓估算
            if actual_vol <= 0:
                # 全部成交
                _finish_pending_sell(C, code, info, ordered_vol)
                print("  [卖出确认] %s 全部成交 (反查失败但持仓归零)" % code)
                _confirm_engine_clear(code, today, info)
            elif actual_vol < prev_vol:
                # 部分成交：按已减部分确认，剩余继续等，不撤单不重试
                traded = prev_vol - actual_vol
                if traded > 0:
                    sell_price = info.get('sell_price', 0)
                    cost_price = info.get('cost', 0)
                    realized = 0
                    if cost_price > 0 and sell_price > 0:
                        realized = (sell_price - cost_price) * traded
                        _g_cumulative_pnl += realized
                        write_nav_file(INTRADAY_NAV_FILE, _g_cumulative_pnl)
                    _append_trade_record(C, '卖出', code, sell_price, traded,
                                         profit_pct=info.get('pct', 0),
                                         profit_amount=realized)
                    print("    已实现盈亏: %+.0f  累计: %+.0f" % (realized, _g_cumulative_pnl))
                    print("  [卖出确认] %s 反查失败但部分成交 %d/%d 股 (持仓确认，剩余继续等)" % (
                        code, traded, ordered_vol))
                    info['volume'] = ordered_vol - traded
                    info['already_traded'] = already_traded + traded
                    _g_pending_sells[code] = info  # 保留剩余继续等，不撤单不重试
                else:
                    _g_trader.cancel_order(info['order_id'], code)
                    if code not in _g_retry_skip_printed:
                        _g_retry_skip_printed.add(code)
                        print("  [卖出重试] %s 订单未找到，撤单后重新委托" % code)
                    _retry_pending_sell(code, dict(info, retries=info.get('retries', 0) + 1), C)
            else:
                # actual_vol >= prev_vol，确实没成交，走原撤单重试
                _g_trader.cancel_order(info['order_id'], code)
                if code not in _g_retry_skip_printed:
                    _g_retry_skip_printed.add(code)
                    print("  [卖出重试] %s 订单未找到，撤单后重新委托" % code)
                _retry_pending_sell(code, dict(info, retries=info.get('retries', 0) + 1), C)
            continue

        vol_traded = getattr(found_order, 'm_nVolumeTraded', 0)

        if vol_traded >= info['volume']:
            _finish_pending_sell(C, code, info, vol_traded)
            print("  [卖出确认] %s 全部成交 %d股 @ %.2f" % (code, vol_traded, info['sell_price']))
            _confirm_engine_clear(code, today, info)
        elif vol_traded > 0:
            _g_trader.cancel_order(info['order_id'], code)
            remaining = info['volume'] - vol_traded
            print("  [部成撤单] %s 已成交%d, 剩余%d股继续卖" % (code, vol_traded, remaining))
            sell_price = info.get('sell_price', 0)
            cost_price = info.get('cost', 0)
            if cost_price > 0 and sell_price > 0:
                realized = (sell_price - cost_price) * vol_traded
                _g_cumulative_pnl += realized
                write_nav_file(INTRADAY_NAV_FILE, _g_cumulative_pnl)
                print("    已实现盈亏: %+.0f  累计: %+.0f" % (realized, _g_cumulative_pnl))
            _append_trade_record(C, '卖出', code, sell_price, vol_traded,
                                 profit_pct=info.get('pct', 0),
                                 profit_amount=(sell_price - cost_price) * vol_traded if cost_price > 0 and sell_price > 0 else 0)
            _g_trade_records.append({'type':'卖出','code':code,'direction':'卖','volume':vol_traded,'price':sell_price,'amount':sell_price*vol_traded,'status':'成交'})
            _retry_pending_sell(code, dict(info, volume=remaining), C)
        else:
            _g_trader.cancel_order(info['order_id'], code)
            info['checks'] = info.get('checks', 0) + 1
            info['retries'] = info.get('retries', 0) + 1
            # 跌停检测：跌停中则移入等待队列
            if _is_limit_down(code, C):
                _g_pending_limitdown_sells[code] = dict(
                    info,
                    timestamp=_market_now(C).strftime('%Y%m%d'),
                )
                _g_pending_sells.pop(code, None)
                print("  [跌停暂缓] %s 跌停中，移入等待队列" % code)
            else:
                print("  [卖出撤单] %s 未成交(已等%d次)，撤单重试..." % (code, info['checks']))
                _retry_pending_sell(code, info, C)


def _check_limitdown_sells(C, today):
    """遍历跌停等待队列：跌停打开则卖出，超过5天则强制卖出。"""
    global _g_pending_limitdown_sells, _g_pending_sells

    if not _g_pending_limitdown_sells:
        return

    for code, info in list(_g_pending_limitdown_sells.items()):
        if _is_limit_down(code, C):
            if 'timestamp' in info:
                try:
                    entry_date = datetime.strptime(str(info['timestamp']), '%Y%m%d')
                    curr_date = datetime.strptime(str(today), '%Y%m%d')
                    days_waiting = (curr_date - entry_date).days
                    if days_waiting >= 5:
                        price = _get_current_price(code, C)
                        if price and price > 0:
                            remaining_vol = info.get('volume', 0)
                            pos = _g_trader.get_position(code)
                            available = pos['can_use'] if pos else 0
                            sell_vol = _normalize_sell_volume_for_board(code, remaining_vol, available, True)
                            if sell_vol > 0:
                                order_id = _g_trader.sell(code, sell_vol, remark='跌停强卖')
                                if order_id is not None:
                                    _g_pending_sells[code] = dict(
                                        info,
                                        order_id=order_id,
                                        sell_price=price,
                                        retries=0,
                                        checks=0,
                                    )
                                    _g_pending_limitdown_sells.pop(code, None)
                                    print("  [跌停强卖] %s 跌停超过%d天，强制卖出 %d股 @ %.2f" % (
                                        code, days_waiting, sell_vol, price))
                                else:
                                    print("  [跌停强卖] %s 强制卖出委托失败" % code)
                            else:
                                print("  [跌停强卖] %s 可卖数量不足最低委托量，清理记录" % code)
                                _g_pending_limitdown_sells.pop(code, None)
                        else:
                            print("  [跌停强卖] %s 无法获取当前价格" % code)
                except Exception as e:
                    print("  [跌停暂缓] %s 日期计算异常: %s" % (code, e))
        else:
            price = _get_current_price(code, C)
            if price and price > 0:
                remaining_vol = info.get('volume', 0)
                pos = _g_trader.get_position(code)
                available = pos['can_use'] if pos else 0
                sell_vol = _normalize_sell_volume_for_board(code, remaining_vol, available, True)
                if sell_vol > 0:
                    order_id = _g_trader.sell(code, sell_vol, remark='跌停放行')
                    if order_id is not None:
                        _g_pending_sells[code] = dict(
                            info,
                            order_id=order_id,
                            sell_price=price,
                            retries=0,
                            checks=0,
                        )
                        _g_pending_limitdown_sells.pop(code, None)
                        print("  [跌停放行] %s 跌停打开，继续卖出 %d股 @ %.2f" % (code, sell_vol, price))
                    else:
                        print("  [跌停放行] %s 恢复卖出委托失败" % code)
                else:
                    print("  [跌停放行] %s 可卖数量不足最低委托量，清理记录" % code)
                    _g_pending_limitdown_sells.pop(code, None)
            else:
                print("  [跌停放行] %s 无法获取当前价格" % code)


def _finish_pending_sell(C, code, info, vol_traded):
    global _g_cumulative_pnl

    sell_price = info.get('sell_price', 0)
    cost_price = info.get('cost', 0)
    realized = 0
    if cost_price > 0 and vol_traded > 0 and sell_price > 0:
        realized = (sell_price - cost_price) * vol_traded
        _g_cumulative_pnl += realized
        write_nav_file(INTRADAY_NAV_FILE, _g_cumulative_pnl)
    print("    已实现盈亏: %+.0f  累计: %+.0f" % (realized, _g_cumulative_pnl))

    _append_trade_record(C, '卖出', code, sell_price, vol_traded,
                         profit_pct=info.get('pct', 0), profit_amount=realized)
    _append_log('卖出成交: %s %d股 @ %.2f' % (code, vol_traded, sell_price))
    _g_trade_records.append({'type':'卖出','code':code,'direction':'卖','volume':vol_traded,'price':sell_price,'amount':sell_price*vol_traded,'status':'成交'})
    _g_pending_sells.pop(code, None)
    # 成交确认即移除：以策略侧成交判定为准，不等 QMT position 缓存刷新
    # （QMT 缓存刷新有延迟，当天 m_nVolume 还显示旧值会导致清仓票赖着占名额）
    pos = _g_trader.get_position(code) if _g_trader else None
    qmt_vol = pos.get('volume', 0) if pos else 0
    if qmt_vol > 0:
        # QMT 缓存未刷新但仍判定成交：以策略侧为准 pop，打 warning 留痕便于事后核
        print("  [持仓清理] %s 成交确认但 QMT 缓存仍显示 %d 股，按策略侧成交移除" % (code, qmt_vol))
    _g_my_codes.pop(code, None)
    # 立即写 holdings 文件，释放名额（原 bug：此处未写文件）
    try:
        write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)
    except Exception as e:
        print("  [持仓清理] 写 holdings 文件失败: %s" % e)
    # 同步卖出引擎状态
    if _g_sell_engine is not None:
        try:
            _g_sell_engine.save_state()
        except Exception:
            pass


def _retry_pending_sell(code, info, C):
    if info.get('retries', 0) >= MAX_SELL_RETRIES:
        print("    -> %s 已重试%d次仍失败，放弃卖出" % (code, MAX_SELL_RETRIES))
        _g_pending_sells.pop(code, None)
        return
    new_price = _get_current_price(code, C)
    if not new_price or new_price <= 0:
        new_retries = info.get('retries', 0) + 1
        print("    -> 无法获取%s当前价，第%d次失败" % (code, new_retries))
        # 保留状态并递增 retries，防止无限循环
        _g_pending_sells[code] = dict(info, retries=new_retries)
        return

    pos = _g_trader.get_position(code)
    available = pos['can_use'] if pos else 0
    new_vol = _normalize_sell_volume_for_board(code, info['volume'], available, info.get('is_clear', False))
    if new_vol <= 0:
        print("    -> %s 已无可卖持仓，清理记录" % code)
        _g_pending_sells.pop(code, None)
        _g_my_codes.pop(code, None)
        try:
            write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)
        except Exception as e:
            print("  [持仓清理] 写 holdings 文件失败: %s" % e)
        return

    use_market = info.get('retries', 0) >= 1  # 首次重试就用市价确保成交
    order_id = _g_trader.sell(code, new_vol, remark='卖出', use_market=use_market)
    if order_id is not None:
        _g_pending_sells[code] = dict(
            info,
            order_id=order_id,
            volume=new_vol,
            sell_price=new_price,
            retries=info.get('retries', 0) + 1,
            checks=info.get('checks', 0),
        )
        print("    -> 重试卖出 %s %d股 @ %.2f  订单号=%s" % (code, new_vol, new_price, order_id))
    else:
        new_retries = info.get('retries', 0) + 1
        print("    -> 委托失败 %s %d股，第%d次失败" % (code, new_vol, new_retries))
        # 保留状态并递增 retries，防止无限循环
        _g_pending_sells[code] = dict(info, retries=new_retries)


def _check_sell(C, today):
    _check_and_execute_sell(C, today)


# ============================================================
#  买入 / 订单管理
# ============================================================

def _try_buy_replacement(C, remark):
    global _g_pending_buys, _g_candidate_queue, _g_per_stock_amount, _g_my_codes, _g_retry_queue
    from core.risk_manager import NO_REENTRY_DAYS

    today = _get_qmt_time(C).strftime('%Y%m%d')
    total_held = len(_g_my_codes) + len(_g_pending_buys)
    if total_held >= MAX_HOLD:
        print("  [补买] 持仓已满(%d/%d)，放弃补买" % (total_held, MAX_HOLD))
        return False
    skip = set(_g_pending_buys.keys())
    skip |= set(_g_my_codes.keys())

    repl = None
    while _g_candidate_queue:
        cand = _g_candidate_queue.pop(0)
        code = cand['code']
        if code in skip:
            continue
        if _g_sell_engine and not _g_sell_engine.is_reentry_allowed(code, today, _g_all_data.get(code)):
            print("  [补买禁入] %s 仍在20日禁入期，跳过" % code)
            continue
        if _is_limit_up(code, C):
            print("  [补买] %s 涨停，跳过" % code)
            continue
        repl = cand
        break

    if repl is None:
        print("  [补买] 无可补候选")
        return False

    repl_code = repl['code']
    repl_price = _get_current_price(repl_code, C)
    if not repl_price or repl_price <= 0:
        print("  [补买] %s 无法获取价格，放弃" % repl_code)
        return False

    repl_vol = int(_g_per_stock_amount / repl_price / 100) * 100
    if repl_vol < 100:
        print("  [补买] %s 不足100股，放弃" % repl_code)
        return False

    repl_id = _g_trader.buy(repl_code, repl_vol, remark=remark)
    if repl_id is not None:
        _g_pending_buys[repl_code] = {
            'order_id': repl_id,
            'price': repl_price,
            'volume': repl_vol,
            'checks': 0,
            'retries': 0,
        }
        print("  [补买] %s %d股 @ %.2f  订单号=%s" % (repl_code, repl_vol, repl_price, repl_id))
        return True

    _g_retry_queue.append({
        'code': repl_code,
        'amount': _g_per_stock_amount,
        'retries': 0,
    })
    print("  [补买] %s 委托失败，加入重试队列" % repl_code)
    return False


def _try_retry_queue(C):
    global _g_retry_queue, _g_pending_buys, _g_candidate_queue, _g_per_stock_amount, _g_my_codes
    from core.risk_manager import NO_REENTRY_DAYS

    if not _g_retry_queue:
        return

    today = _get_qmt_time(C).strftime('%Y%m%d')
    still_queue = []
    for item in _g_retry_queue:
        code = item['code']
        if _g_sell_engine and not _g_sell_engine.is_reentry_allowed(code, today, _g_all_data.get(code)):
            print("  [重试禁入] %s 仍在20日禁入期，转补买" % code)
            _try_buy_replacement(C, '重试禁入补买')
            continue

        if item['retries'] >= 3:
            print("  [重试放弃] %s 重试%d次失败，转补买" % (code, item['retries']))
            _try_buy_replacement(C, '补买')
            continue

        price = _get_current_price(code, C)
        if not price or price <= 0:
            still_queue.append(item)
            continue

        if _is_limit_up(code, C):
            print("  [重试跳过] %s 涨停，转补买" % code)
            _try_buy_replacement(C, '补买')
            continue

        volume = int(item['amount'] / price / 100) * 100
        if volume < 100:
            print("  [重试放弃] %s 金额不足100股，转补买" % code)
            _try_buy_replacement(C, '补买')
            continue

        order_id = _g_trader.buy(code, volume, remark='重试')
        if order_id is not None:
            _g_pending_buys[code] = {
                'order_id': order_id,
                'price': price,
                'volume': volume,
                'checks': 0,
                'retries': item['retries'],
            }
            print("  [重试成功] %s %d股 @ %.2f  订单号=%s" % (code, volume, price, order_id))
        else:
            item['retries'] += 1
            still_queue.append(item)
            print("  [重试待续] %s 第%d次失败，下次继续" % (code, item['retries']))

    _g_retry_queue = still_queue


def _check_pending_orders(C):
    global _g_my_codes, _g_pending_buys, _g_candidate_queue, _g_per_stock_amount, _g_retry_queue

    if not _g_pending_buys:
        return

    try:
        orders = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'order')
    except Exception as e:
        print("  [待成交] 查询订单失败: %s" % e)
        return

    original_pending_codes = set(_g_pending_buys.keys())
    still_pending = {}
    for code, info in list(_g_pending_buys.items()):
        found_order = None
        for o in orders:
            inst = o.m_strInstrumentID
            ex = o.m_strExchangeID
            oc = "%s.%s" % (inst, ex)
            oid = getattr(o, 'm_nOrderID', None)
            if oc == code and oid is not None and oid == info['order_id']:
                found_order = o
                break

        if found_order is None:
            pos = _g_trader.get_position(code)
            if pos and pos['volume'] > 0:
                _g_my_codes[code] = info['price']
                write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)
                print("  [成交确认] %s  %d股 @ %.2f (持仓确认)" % (code, info['volume'], info['price']))
                _append_trade_record(C, '买入', code, info['price'], pos['volume'])
                _append_log('买入成交: %s %d股 @ %.2f' % (code, pos['volume'], info['price']))
                _g_trade_records.append({'type':'买入','code':code,'direction':'买','volume':pos['volume'],'price':info['price'],'amount':pos['volume']*info['price'],'status':'成交'})
            else:
                print("  [未查到] %s 订单%s 无法查询，尝试替补" % (code, info['order_id']))
                _try_buy_replacement(C, '盘中')
            continue

        vol_traded = getattr(found_order, 'm_nVolumeTraded', 0)

        if vol_traded > 0:
            _g_my_codes[code] = info['price']
            write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)
            print("  [成交确认] %s  %d/%d股 @ %.2f" % (code, vol_traded, info['volume'], info['price']))
            _append_trade_record(C, '买入', code, info['price'], vol_traded)
            _append_log('买入成交: %s %d股 @ %.2f' % (code, vol_traded, info['price']))
            _g_trade_records.append({'type':'买入','code':code,'direction':'买','volume':vol_traded,'price':info['price'],'amount':vol_traded*info['price'],'status':'成交'})
            if vol_traded < info['volume']:
                _g_trader.cancel_order(info['order_id'], code)
                print("  [部成撤单] %s 未成交部分已撤销" % code)
        elif info['retries'] >= 3:
            _g_trader.cancel_order(info['order_id'], code)
            print("  [重试用完] %s 3次撤单重试未成交，转补买..." % code)
            _try_buy_replacement(C, '盘中')
        else:
            _g_trader.cancel_order(info['order_id'], code)
            retry_count = info['retries'] + 1
            print("  [撤单重试] %s 第%d次 (checks=%d)" % (code, retry_count, info['checks']))

            if _is_limit_up(code, C):
                print("    -> %s 涨停，直接替补" % code)
                _try_buy_replacement(C, '盘中')
                continue

            new_price = _get_current_price(code, C)
            if new_price and new_price > 0:
                new_vol = int(info['volume'] / new_price * info['price'] / 100) * 100
                if new_vol >= 100:
                    new_id = _g_trader.buy(code, new_vol, remark='盘中')
                    if new_id is not None:
                        still_pending[code] = {
                            'order_id': new_id,
                            'price': new_price,
                            'volume': new_vol,
                            'checks': 0,
                            'retries': retry_count,
                        }
                        print("    -> 重试 %s %d股 @ %.2f  新订单号=%s" % (code, new_vol, new_price, new_id))
                    else:
                        print("    -> 重试委托失败，加入重试队列(累计%d次)" % retry_count)
                        _g_retry_queue.append({
                            'code': code,
                            'amount': _g_per_stock_amount,
                            'retries': retry_count,
                        })
                else:
                    print("    -> 调整后不足100股，尝试替补")
                    _try_buy_replacement(C, '盘中')
            else:
                print("    -> 无法获取价格，尝试替补")
                _try_buy_replacement(C, '盘中')

    new_pending = dict(still_pending)
    for k, v in _g_pending_buys.items():
        if k not in original_pending_codes:
            new_pending[k] = v
    _g_pending_buys = new_pending


# ============================================================
#  交易执行主流程
# ============================================================

def _execute_trade(C, today, dt):
    global _g_my_codes, _g_pending_buys, _g_pending_sells, _g_pending_limitdown_sells

    _refresh_trade_data(C)
    # 买入前再校验实际持仓，防止盘中已清仓的票残留占名额
    _sync_holdings_from_account(C, today)

    if DEBUG_MODE:
        window = "调试全天"
    elif TEST_MODE:
        window = "测试全天"
    else:
        window = BUY_WINDOW_LABEL
    prefix = "[调试模式]" if DEBUG_MODE else ""
    print("\n" + "=" * 60)
    print("  %s[%s] %s  盘中交易窗口 %s" % (prefix, STRATEGY_NAME, today, window))
    print("=" * 60)

    # 持仓同步
    实际持仓 = get_account_holdings(ACCOUNT_ID)
    对方持仓 = read_holdings_file(ENDOFDAY_HOLD_FILE)
    对方持仓集 = set(对方持仓.keys()) if isinstance(对方持仓, dict) else set()

    if 实际持仓 is not None and len(实际持仓) > 0:
        for code in list(_g_my_codes.keys()):
            if code not in 实际持仓:
                del _g_my_codes[code]
                print("  [同步] 移除 %s（不在账户中）" % code)
    else:
        print("  [持仓] 查询返回空，可能是API未就绪，跳过删除当前持仓记录")

    if 实际持仓:
        for code in 实际持仓:
            if code not in 对方持仓集 and code not in _g_my_codes:
                _g_my_codes[code] = 0
                print("  [同步] 加入 %s（账户中发现）" % code)

    write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)

    其他持仓 = read_holdings_file(ENDOFDAY_HOLD_FILE)
    账户持仓 = 实际持仓
    我的持仓 = _g_my_codes

    print("  我的持仓: %d 只 -> %s" % (len(我的持仓), sorted(我的持仓)))
    print("  对方持仓: %d 只" % len(其他持仓))
    print("  账户总持仓: %d 只" % len(账户持仓))

    _check_limitdown_sells(C, today)
    _check_and_execute_sell(C, today)

    current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl

    holdings_value = 0.0
    for code in list(_g_my_codes.keys()):
        df = _g_all_data.get(code)
        if df is not None:
            try:
                price = float(df['close'].iloc[-1])
                pos = _g_trader.get_position(code)
                if pos and pos.get('volume', 0) > 0:
                    holdings_value += pos['volume'] * price
            except Exception:
                pass

    floating_pnl = calc_floating_pnl(ACCOUNT_ID)
    effective_nav = current_nav + floating_pnl

    current_ratio = holdings_value / current_nav if current_nav > 0 else 0
    budget = current_nav * MAX_TOTAL_RATIO - holdings_value

    print("  策略净值: %.0f (本%d+已实现%+.0f+浮动%+.0f)" % (
        effective_nav, STRATEGY_CAPITAL, _g_cumulative_pnl, floating_pnl))
    print("  仓位: %.1f%%  持仓市值: %.0f  可用预算: %.0f" % (
        current_ratio * 100, holdings_value, budget))

    if current_ratio >= MAX_TOTAL_RATIO or budget <= 0:
        if len(_g_my_codes) < MAX_HOLD:
            print("  仓位已达上限或预算不足，跳过买入")
            return True
        print("  仓位已满，尝试换仓...")

    candidates = _load_pool()
    if not candidates:
        print("  [外部池] 无候选股票")
        return False

    signal_candidates = []
    for cand in candidates:
        code = cand['code']
        df = _g_all_data.get(code)
        if df is None or len(df) < MIN_BARS:
            continue
        buy, signal, buy_type = check_buy(df)
        if not buy:
            continue
        if _is_st_stock(code, C):
            print("  [ST过滤] %s 跳过" % code)
            continue
        signal_candidates.append({'code': code, 'signal': signal, 'buy_type': buy_type})

    if not signal_candidates:
        print("  [买入信号] 外部池无股票通过技术信号/ST过滤")
        return True
    candidates = signal_candidates

    scored = _run_scoring(C, candidates, dt)
    if not scored:
        print("  [打分] 无候选股通过")
        return True

    # 用同步后实际有持仓的票数算名额，避免已清仓票残留占名额
    actual_held = _sync_holdings_from_account(C, today)
    already_held = actual_held | set(_g_my_codes.keys()) | 对方持仓集 | set(_g_pending_buys.keys())
    buyable = []
    for s in scored:
        code = s['code']
        if code in already_held:
            continue
        if _g_sell_engine and not _g_sell_engine.is_reentry_allowed(code, today, _g_all_data.get(code)):
            print("  [禁止再入] %s 仍在20日禁止期内，跳过" % code)
            continue
        buyable.append(s)

    if not buyable:
        print("  [买入] 所有候选股票已被持有，跳过")
        return True

    可买数量 = max(0, MAX_HOLD - len(actual_held))
    _g_candidate_queue = buyable[可买数量:]
    buyable = buyable[:可买数量]

    # 置换方案C: 双门控置换
    if not buyable and len(_g_my_codes) >= MAX_HOLD and scored:
        held_codes = list(_g_my_codes.keys())
        held_scores = {}
        for code in held_codes:
            df = _g_all_data.get(code)
            if df is not None:
                try:
                    r = _g_scorer.score_single(stock_code=code, df=df)
                    held_scores[code] = r['score_total']
                except Exception as ex:
                    print("    [置换打分] %s 异常: %s" % (code, ex))
        for code, held_score in sorted(held_scores.items(), key=lambda x: x[1]):
            # 5天淘汰检查
            _should_swap = False
            state = _g_sell_engine._states.get(code) if _g_sell_engine else None
            if state and state.entry_date:
                try:
                    entry_dt = datetime.strptime(state.entry_date, '%Y%m%d')
                    held_days = (datetime.strptime(today, '%Y%m%d') - entry_dt).days
                    if held_days >= 5:
                        cost = state.cost_price
                        current_price = _get_current_price(code, C)
                        if cost > 0 and current_price and current_price > 0:
                            return_pct = (current_price - cost) / cost
                            if return_pct < 0.03:
                                _should_swap = True  # 5天不到3%，标记可换
                except Exception:
                    pass

            # 评分门控：非5天淘汰且评分>=70则跳过
            if not _should_swap and held_score >= 70:
                continue

            # 评分差门槛：5天淘汰时降低门槛
            gap_required = 10 if _should_swap else 15

            for s in scored:
                if s['code'] in already_held or s['code'] == code:
                    continue
                if s['score'] >= held_score + gap_required:
                    pos = _g_trader.get_position(code)
                    can_use = pos.get('can_use', 0) if pos else 0
                    if can_use >= 100:
                        vol = (can_use // 100) * 100
                        price = _get_current_price(code, C)
                        oid = _g_trader.sell(code, vol, remark='换仓卖出')
                        if oid is not None:
                            state_obj = _g_sell_engine._states.get(code) if _g_sell_engine else None
                            _g_pending_sells[code] = {
                                'order_id': oid,
                                'volume': vol,
                                'sell_price': price or 0,
                                'cost': state_obj.cost_price if state_obj else 0,
                                'pct': 1.0,
                                'checks': 0,
                                'retries': 0,
                                'is_clear': True,
                                'code': code,
                                'today': today,
                            }
                            print("  [换仓] 先卖出 %s (评分%.2f)，成交确认后再补买候选" % (code, held_score))
                            return True
                        else:
                            print("  [换仓失败] %s 卖出委托失败" % code)
                    break
            if buyable:
                break

    if not buyable:
        print("  [买入] 仓位已满（%d/%d），无可买目标" % (len(我的持仓), MAX_HOLD))
        return True

    print("\n  [买入计划] 目标 %d 只, 候补 %d 只:" % (len(buyable), len(_g_candidate_queue)))
    for s in buyable:
        print("    %s  总分=%.2f  信号=%s" % (s['code'], s['score'], s['signal']))

    per_stock_amount_raw = current_nav * TARGET_RATIO
    if buyable and budget > 0:
        per_stock_amount_raw = min(per_stock_amount_raw, budget / len(buyable))
    per_stock_amount = int(per_stock_amount_raw / 100) * 100
    if per_stock_amount < 100:
        print("  单只金额不足100股，跳过买入")
        return True
    _g_per_stock_amount = per_stock_amount

    real_cash = _g_trader.get_available_cash()
    total_buy_amount = per_stock_amount * len(buyable)
    max_buy_from_cash = real_cash * 0.80
    if total_buy_amount > max_buy_from_cash and len(buyable) > 0:
        adjusted = int(max_buy_from_cash / len(buyable) / 100) * 100
        if adjusted < 100:
            print("  可用资金不足，跳过买入")
            return True
        per_stock_amount = adjusted
        _g_per_stock_amount = per_stock_amount

    for s in buyable:
        code = s['code']
        if _is_limit_up(code, C):
            print("    - 跳过 %s  涨停" % code)
            continue
        price = _get_current_price(code, C)
        if price and price > 0:
            volume = int(per_stock_amount / price / 100) * 100
            if volume >= 100:
                print("    委托买入 %s  %d股  估算金额=%.0f" % (code, volume, volume * price))
                order_id = _g_trader.buy(code, volume, remark='盘中')
                if order_id is not None:
                    _g_pending_buys[code] = {
                        'order_id': order_id,
                        'price': price,
                        'volume': volume,
                        'checks': 0,
                        'retries': 0,
                    }
                    print("    [委托] %s %d股  订单号=%s" % (code, volume, order_id))
                    _append_log('买入委托: %s %d股 @ %.2f' % (code, volume, price))
                else:
                    _g_retry_queue.append({
                        'code': code,
                        'amount': per_stock_amount,
                        'retries': 0,
                    })
                    print("    [委托失败] %s %d股  已加入重试队列" % (code, volume))
        else:
            print("    - 跳过 %s  无法获取价格" % code)

    if _g_pending_buys:
        print("\n  [待成交] %d 只委托待确认:" % len(_g_pending_buys))
        for code, info in _g_pending_buys.items():
            print("    %s %d股 @ %.2f  订单号=%s" % (code, info['volume'], info['price'], info['order_id']))
    if _g_retry_queue:
        print("  [重试队列] %d 只待重试:" % len(_g_retry_queue))
        for item in _g_retry_queue:
            print("    %s 已重试%d次" % (item['code'], item['retries']))

    return True


# ============================================================
#  订单状态查询
# ============================================================

def check_order_status(C, code=None):
    try:
        orders = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'order')
        if not orders:
            print("  [委托] 当日无委托记录")
            return

        status_map = {
            48: '未报', 49: '待撤', 50: '已报', 51: '待报',
            52: '已撤', 53: '部撤', 54: '部成', 55: '未成',
            56: '全部成交', 57: '已成',
        }

        count = 0
        for o in orders:
            inst = o.m_strInstrumentID
            ex = o.m_strExchangeID
            oc = "%s.%s" % (inst, ex)
            if code and oc != code:
                continue
            st = status_map.get(o.m_nOrderStatus, '未知(%d)' % o.m_nOrderStatus)
            vol_orig = o.m_nVolumeTotalOriginal
            vol_traded = o.m_nVolumeTraded
            print("    %s %s %s  委托%d股 成交%d股  价格%.2f %s" % (
                oc, o.m_strOptName, st, vol_orig, vol_traded,
                o.m_dLimitPrice, o.m_strInsertTime))
            count += 1

        if count == 0:
            print("  [委托] %s 无当日委托" % (code or '全部'))
        return orders
    except Exception as e:
        print("  [委托] 查询失败: %s" % e)
        return None


# ============================================================
#  成交记录 & 评分历史
# ============================================================

def _append_trade_record(C, trade_type, code, price, volume, profit_pct=None, profit_amount=0):
    try:
        name = C.get_stock_name(code) or ''
    except Exception:
        name = ''

    try:
        dt_str = C.get_current_time().strftime('%Y-%m-%d %H:%M')
    except Exception:
        dt_str = _get_qmt_time(C).strftime('%Y-%m-%d %H:%M')

    if trade_type == '买入':
        line = "%s  买入  %s  %s  价格:%.2f  数量:%d" % (dt_str, code, name, price, volume)
    else:
        pct_s = ""
        try:
            if profit_pct is not None:
                pct_s = "%+.2f%%" % float(profit_pct)
        except Exception:
            pct_s = str(profit_pct) if profit_pct is not None else ""
        amt_s = "%+.0f" % profit_amount if profit_amount != 0 else ""
        line = "%s  卖出  %s  %s  价格:%.2f  数量:%d  盈亏:%s  金额:%s" % (
            dt_str, code, name, price, volume, pct_s, amt_s)

    try:
        dirname = os.path.dirname(TRADE_LOG_FILE)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(TRADE_LOG_FILE, 'a', encoding='gbk') as f:
            f.write(line + '\n')
    except Exception as e:
        print("  [成交记录] 写入失败: %s" % e)


def _get_prev_scores(today):
    if not os.path.exists(SCORE_HISTORY_FILE):
        return {}
    try:
        with open(SCORE_HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        dates = sorted([k for k in data if k != 'latest_date'], reverse=True)
        for d in dates:
            if d < today:
                return data[d]
        return {}
    except Exception:
        return {}


def _save_today_scores(today, scores):
    data = {}
    if os.path.exists(SCORE_HISTORY_FILE):
        try:
            with open(SCORE_HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            pass
    dates = sorted([k for k in data if k != 'latest_date'], reverse=True)
    for d in dates[4:]:
        data.pop(d, None)
    data[today] = scores
    try:
        dirname = os.path.dirname(SCORE_HISTORY_FILE)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(SCORE_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("  [评分历史] 写入失败: %s" % e)


# ============================================================
#  全天调试版：全流程执行 + 决策矩阵
# ============================================================

def _execute_full_cycle(C, today, dt):
    """全流程：加载数据→评分池候选+持仓→决策执行"""
    global _g_data_loaded, _g_all_data, _g_my_codes, _g_scorer, _g_sell_engine

    if not _g_data_loaded:
        _load_data(C, dt)
        _g_data_loaded = True

    # 1. 加载池、评分池候选
    candidates = _load_pool()
    if not candidates:
        print("  [全天] 外部池无候选")
        return

    # 2. 过滤池候选（信号+ST+数据检查）
    signal_candidates = []
    for cand in candidates:
        code = cand['code']
        df = _g_all_data.get(code)
        if df is None or len(df) < MIN_BARS:
            continue
        buy, signal, buy_type = check_buy(df)
        if not buy:
            continue
        if not _passes_buy_bias_filter(code, df, label='全天买入过滤'):
            continue
        if _is_st_stock(code, C):
            continue
        signal_candidates.append({'code': code, 'signal': signal, 'buy_type': buy_type})

    if not signal_candidates:
        print("  [全天] 信号过滤后无候选")
        return

    # 3. 评分池候选
    scored = _run_scoring(C, signal_candidates, dt)
    if not scored:
        print("  [全天] 评分后无候选")
        return

    # 4. 评分持仓股（用于对比）
    held_scores = {}
    for code in list(_g_my_codes.keys()):
        df = _g_all_data.get(code)
        if df is not None:
            try:
                r = _g_scorer.score_single(stock_code=code, df=df)
                held_scores[code] = r['score_total']
            except Exception:
                pass

    # 5. 决策矩阵
    _all_day_decision_matrix(C, today, dt, scored, held_scores)


def _all_day_decision_matrix(C, today, dt, scored_candidates, held_scores):
    """全天版决策矩阵：在每个操作点执行"""
    global _g_my_codes, _g_all_data, _g_sell_engine, _g_trader
    global _g_pending_buys, _g_pending_sells, _g_candidate_queue, _g_per_stock_amount

    # 第一步：构建持仓数据，调用卖出引擎评估所有持仓
    positions_data = {}
    for code in _g_my_codes:
        pos = _g_trader.get_position(code)
        if pos:
            positions_data[code] = pos

    rt_prices = _get_current_prices(list(_g_my_codes.keys()), C)
    raw_decisions = _g_sell_engine.evaluate(today, _g_my_codes, _g_all_data, positions_data, rt_prices)

    for code, dec, shares in raw_decisions:
        df = _g_all_data.get(code)
        if df is None:
            continue

        if dec.action == Action.CLEAR:
            print("  [全天决策] %s CLEAR触发, 强制卖出" % code)
            _check_and_execute_sell(C, today)
            continue

        if dec.action == Action.REDUCE:
            if code in held_scores and held_scores[code] < 70:
                cand_score = _find_best_candidate(scored_candidates, set(_g_my_codes.keys()))
                if cand_score and cand_score['score'] >= held_scores[code] + 15:
                    _execute_swap(code, cand_score, dec, C)
                    continue
            _check_and_execute_sell(C, today)
            continue

    # 第二步：检查无卖出信号的持仓，做5天淘汰检查
    decided_codes = {code for code, _, _ in raw_decisions}
    for code in list(_g_my_codes.keys()):
        if code in decided_codes:
            continue
        state = _g_sell_engine._states.get(code)
        if state and state.entry_date:
            try:
                entry_dt = datetime.strptime(state.entry_date, '%Y%m%d')
                held_days = (datetime.strptime(today, '%Y%m%d') - entry_dt).days
                if held_days >= 5:
                    current_price = _get_current_price(code, C)
                    cost = state.cost_price
                    if cost > 0 and current_price is not None:
                        return_pct = (current_price - cost) / cost
                        if return_pct < 0.03:
                            cand = _find_best_candidate(scored_candidates, set(_g_my_codes.keys()))
                            if cand and code in held_scores and cand['score'] >= held_scores[code] + 15:
                                _execute_swap(code, cand, None, C)
            except Exception:
                pass

    # 第三步：有空位就买入
    empty_slots = max(0, MAX_HOLD - len(_g_my_codes))
    if empty_slots > 0:
        already_held_or_pending = set(_g_my_codes.keys()) | set(_g_pending_buys.keys()) | set(_g_pending_sells.keys())
        buyable = [s for s in scored_candidates if s['code'] not in already_held_or_pending]
        buyable = buyable[:empty_slots]
        for s in buyable:
            _place_buy_order(C, s['code'], today, dt)


def _find_best_candidate(scored_candidates, exclude_codes):
    """从候选中找评分最高的（排除已持有/已挂单）"""
    for s in scored_candidates:
        if s['code'] not in exclude_codes:
            return s
    return None


def _execute_swap(old_code, new_candidate, sell_decision, C):
    """换仓：卖出旧股，等成交后买入新股"""
    global _g_trader, _g_pending_sells, _g_pending_buys, _g_sell_engine

    pos = _g_trader.get_position(old_code)
    can_use = pos.get('can_use', 0) if pos else 0
    if can_use < 100:
        print("  [换仓] %s 可卖数量不足100股" % old_code)
        return

    vol = (can_use // 100) * 100
    price = _get_current_price(old_code, C)
    if not price or price <= 0:
        print("  [换仓] %s 无法获取当前价" % old_code)
        return

    oid = _g_trader.sell(old_code, vol, remark='换仓卖出')
    if oid:
        state_obj = _g_sell_engine._states.get(old_code) if _g_sell_engine else None
        _g_pending_sells[old_code] = {
            'order_id': oid,
            'volume': vol,
            'sell_price': price,
            'cost': state_obj.cost_price if state_obj else 0,
            'pct': 1.0,
            'checks': 0,
            'retries': 0,
            'is_clear': True,
            'code': old_code,
            'today': _market_now(C).strftime('%Y%m%d'),
        }
        _g_candidate_queue.insert(0, new_candidate)
        print("  [换仓] 卖出 %s %d股 @ %.2f, 待成交后买入 %s" % (old_code, vol, price, new_candidate['code']))


def _place_buy_order(C, code, today, dt):
    """直接买入（全天版决策矩阵使用）"""
    global _g_trader, _g_pending_buys, _g_my_codes, _g_per_stock_amount, _g_cumulative_pnl, _g_all_data

    price = _get_current_price(code, C)
    if not price or price <= 0:
        print("    [买入] %s 无法获取价格" % code)
        return

    if _is_limit_up(code, C):
        print("    [买入] %s 涨停，跳过" % code)
        return

    current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
    holdings_value = 0.0
    for hcode in list(_g_my_codes.keys()):
        df = _g_all_data.get(hcode)
        if df is not None:
            try:
                hprice = float(df['close'].iloc[-1])
                pos = _g_trader.get_position(hcode)
                if pos and pos.get('volume', 0) > 0:
                    holdings_value += pos['volume'] * hprice
            except Exception:
                pass
    budget = current_nav * MAX_TOTAL_RATIO - holdings_value
    if budget <= 0:
        print("    [买入] %s 预算不足 (budget=%.0f)，跳过" % (code, budget))
        return
    amount = min(_g_per_stock_amount if _g_per_stock_amount > 0 else current_nav * TARGET_RATIO, budget)
    volume = int(amount / price / 100) * 100
    if volume < 100:
        print("    [买入] %s 不足100股" % code)
        return

    order_id = _g_trader.buy(code, volume, remark='全天买入')
    if order_id is not None:
        _g_pending_buys[code] = {
            'order_id': order_id,
            'price': price,
            'volume': volume,
            'checks': 0,
            'retries': 0,
        }
        print("    [买入] %s %d股 @ %.2f  订单号=%s" % (code, volume, price, order_id))
        _append_log('全天买入委托: %s %d股 @ %.2f' % (code, volume, price))


# ============================================================
#  StrategyRunner — QMT 生命周期入口
# ============================================================

class StrategyRunner(object):
    """QMT handlebar 入口：init → handlebar → exit"""

    def init(self, C):
        global _g_init_done, _g_trader, _g_scorer, _g_cumulative_pnl
        global _g_pending_buys, _g_retry_queue, _g_candidate_queue, _g_per_stock_amount
        global _g_pending_sells, _g_pending_limitdown_sells, _g_sell_engine
        global _g_strategy_start_ts

        if _g_init_done:
            return

        # ===== SAFEMODE 初始化 =====
        if SAFEMODE_ENABLED:
            os.makedirs(SAFEMODE_LOG_DIR, exist_ok=True)
            with open(os.path.join(SAFEMODE_LOG_DIR, "safemode_started.log"), "a") as f:
                # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
                f.write("[%s] SAFEMODE ACTIVE - 真仓锁定\n" % datetime.now())

        _g_trader = Trader(C, ACCOUNT_ID, 'STOCK', STRATEGY_NAME)
        _g_scorer = SwitchScorer(mode='6plus2')

        _g_cumulative_pnl = read_nav_file(INTRADAY_NAV_FILE)
        current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl

        _g_pending_buys = {}
        _g_retry_queue = []
        _g_candidate_queue = []
        _g_per_stock_amount = 0
        _g_pending_sells = {}
        _g_pending_limitdown_sells = {}
        _g_sell_engine = SellStrategyEngine(
            strategy_name=STRATEGY_NAME,
            account_id=ACCOUNT_ID,
            state_file=INTRADAY_SELL_STATE_FILE,
            is_intraday=False,
            hard_stop_loss=HARD_STOP_LOSS,
        )
        _g_sell_engine.load_state()

        _g_strategy_start_ts = time.time()
        try:
            _mkt = _market_now(C)
            print("  [时间校验] 行情时间=%s 设备时间=%s" % (_mkt.strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        except Exception as e:
            print("  [时间校验] 异常: %s" % e)
        _g_init_done = True
        print("[%s] 初始化完成  账号=%s" % (STRATEGY_NAME, ACCOUNT_ID))
        print("[%s] 策略本金=%d  累计盈亏=%+.0f  当前净值=%.0f" % (
            STRATEGY_NAME, STRATEGY_CAPITAL, _g_cumulative_pnl, current_nav))
        print("[%s] 持仓上限=%d只  %s" % (
            STRATEGY_NAME, MAX_HOLD,
            "买入窗口=调试模式-全天候" if DEBUG_MODE else "买入窗口=%s（数据含当天日线）" % BUY_WINDOW_LABEL))
        print("[%s] K线周期请设为「1分钟」" % STRATEGY_NAME)

    def handlebar(self, C):
        try:
            self._handlebar_impl(C)
        except KeyboardInterrupt:
            pass  # 用户手动停止，静默退出，不打印 traceback

    def _handlebar_impl(self, C):
        global _g_last_date, _g_today_done, _g_data_loaded, _g_my_codes, _g_cumulative_pnl, _g_wait_printed
        global _g_pending_buys, _g_retry_queue, _g_candidate_queue, _g_per_stock_amount
        global _g_pending_sells, _g_pending_limitdown_sells, _g_sell_engine
        global _g_op_executed, _g_startup_done, _g_all_data, _g_index_data, _g_last_sell_fingerprint
        global _g_timegate_skip_printed, _g_cooling_printed
        global _g_premarket_check_done, _g_premarket_orders

        dt = _get_qmt_time(C)
        today = dt.strftime('%Y%m%d')
        now = dt.strftime('%H%M')

        if today != _g_last_date:
            _g_last_date = today
            _g_today_done = False
            _g_data_loaded = False
            _g_wait_printed = False
            _g_sell_skip_printed.clear()
            _g_price_skip_printed.clear()
            _g_retry_skip_printed.clear()
            _g_failed_printed.clear()
            _g_last_sell_fingerprint = ''
            _g_timegate_skip_printed.clear()
            _g_cooling_printed = False
            _g_premarket_check_done = False
            _g_premarket_orders = {}
            _g_my_codes = read_holdings_file(INTRADAY_HOLD_FILE)
            _g_cumulative_pnl = read_nav_file(INTRADAY_NAV_FILE)
            _g_pending_buys = {}
            _g_retry_queue = []
            _g_candidate_queue = []
            _g_per_stock_amount = 0
            _g_pending_sells = {}
            _g_pending_limitdown_sells = {}
            _g_startup_done = False
            _g_all_data = {}
            _g_index_data = None
            _reset_log_buffers()
            if _g_sell_engine:
                _g_sell_engine.load_state()
            # 开盘首帧强制同步实际账户持仓（修 603618 类残留）
            _sync_holdings_from_account(C, today)
            if DEBUG_MODE:
                _g_op_executed = {}

        # Layer 1: 全天卖出监测
        if SAFEMODE_ENABLED:
            # SAFEMODE: 只做数据加载 + 评分 + 日志输出，不下单
            if not _g_data_loaded:
                print("\n[SAFEMODE] %s  加载交易日数据（只读模式）..." % today)
                _load_data(C, dt)
                _g_data_loaded = True

            candidates = _load_pool()
            if candidates and _g_all_data:
                signal_candidates = []
                for cand in candidates:
                    code = cand['code']
                    df = _g_all_data.get(code)
                    if df is None or len(df) < MIN_BARS:
                        continue
                    buy, signal, buy_type = check_buy(df)
                    if not buy:
                        continue
                    if _is_st_stock(code, C):
                        continue
                    signal_candidates.append({'code': code, 'signal': signal, 'buy_type': buy_type})
                if signal_candidates:
                    scored = _run_scoring(C, signal_candidates, dt)
                    for s in scored:
                        _safemode_log_signal(
                            s['code'], s['score'], s.get('buy_points', 0),
                            0, details=s.get('details')
                        )
            if _g_today_done:
                return
            _write_daily_log(today, C)
            _print_holdings_report(C, today)
            _g_today_done = True
            print("[SAFEMODE] %s 信号计算完成（只读），跳过所有交易执行" % today)
            return

        # ===== P2: 启动 cooling-off 守卫 =====
        if _is_in_cooling_off():
            if not _g_cooling_printed:
                print("  [%s] 启动 cooling-off 中（60s 内屏蔽所有交易）..." % STRATEGY_NAME)
                _g_cooling_printed = True
            return

        # ===== P3: 09:25-09:29:59 集合竞价预埋硬止损 =====
        if '0925' <= now < '0930':
            _check_pre_market_hard_stop(C, today, now)
            return

        # Layer 1: 全天卖出监测（仅限交易时段，TEST_MODE不再绕过时间检查；P2 加时段路由）
        if _is_trading_time(dt) and now < '1458':
            _check_pending_sells(C, today)
            _check_limitdown_sells(C, today)
            if _g_my_codes:
                allowed = _get_allowed_sell_layers(now)
                if allowed['layers']:
                    _check_and_execute_sell(C, today, allowed_layers=allowed)
                # 注：limitdown_sells 不受时段路由限制（已挂出的撤单/重发不阻断）
        elif now >= '1458':
            if not _g_today_done:
                if _g_pending_buys:
                    for code, info in list(_g_pending_buys.items()):
                        _g_trader.cancel_order(info['order_id'], code)
                        print("  [%s] 收盘撤单 %s 买入%s" % (STRATEGY_NAME, code, info['order_id']))
                    _g_pending_buys = {}
                if _g_retry_queue:
                    print("  [%s] 清空重试队列 %d 只" % (STRATEGY_NAME, len(_g_retry_queue)))
                    _g_retry_queue = []
                if _g_pending_sells:
                    for code, info in list(_g_pending_sells.items()):
                        _g_trader.cancel_order(info['order_id'], code)
                        print("  [%s] 收盘撤单 %s 卖出%s" % (STRATEGY_NAME, code, info['order_id']))
                _g_pending_sells = {}
                _check_sell(C, today)
                _print_holdings_report(C, today)
                _g_today_done = True
            _write_daily_log(today, C)

        if _g_today_done:
            return

        # ===== 全天调试版：时间窗口守卫 =====
        if DEBUG_MODE:
            morning = ALLDAY_MORNING_START <= now <= ALLDAY_MORNING_END
            afternoon = ALLDAY_AFTERNOON_START <= now <= ALLDAY_AFTERNOON_END
            if not morning and not afternoon:
                return  # 非交易时间，跳过

        # 生产版：等待盘中买入窗口
        if not DEBUG_MODE and not TEST_MODE and now < BUY_WINDOW_START:
            if not _g_wait_printed:
                print("  [%s] 当前时间 %s, 等待盘中买入窗口 %s..." % (STRATEGY_NAME, now, BUY_WINDOW_LABEL))
                _g_wait_printed = True
            return

        if not DEBUG_MODE and not TEST_MODE and now > BUY_WINDOW_END:
            if _g_pending_buys:
                for code, info in list(_g_pending_buys.items()):
                    _g_trader.cancel_order(info['order_id'], code)
                    print("  [%s] 盘中买入窗口结束，撤单 %s 买入%s" % (STRATEGY_NAME, code, info['order_id']))
                _g_pending_buys = {}
            if _g_retry_queue:
                print("  [%s] 盘中买入窗口结束，清空买入重试队列 %d 只" % (STRATEGY_NAME, len(_g_retry_queue)))
                _g_retry_queue = []
            _g_today_done = True
            print("  [%s] 盘中买入窗口已结束，停止今日新买入" % STRATEGY_NAME)
            return

        # ===== 全天调试版：启动时首次全流程执行 =====
        if DEBUG_MODE and not _g_startup_done:
            _g_startup_done = True
            _execute_full_cycle(C, today, dt)
            return

        # ===== 全天调试版：操作点守卫 =====
        if DEBUG_MODE:
            is_operation_point = now in OPERATION_POINTS
            if is_operation_point and not _g_op_executed.get(now, False):
                _execute_full_cycle(C, today, dt)
                _g_op_executed[now] = True
                return
            # 非操作点：只跑卖出监测（已在 layer 1 执行），不执行买入/换仓
            if not is_operation_point:
                return

        if _g_pending_buys or _g_retry_queue:
            _check_pending_orders(C)
            _try_retry_queue(C)
            if not _g_pending_buys and not _g_retry_queue and not _g_pending_sells:
                _g_today_done = True
                print("  [%s] 所有买入委托已确认，交易结束" % STRATEGY_NAME)
            return

        # 测试模式 / 盘中生产版：允许交易
        if TEST_MODE or _is_buy_window(now):
            if not _g_data_loaded:
                print("\n[%s] %s  加载交易日数据..." % (STRATEGY_NAME, today))
                _load_data(C, dt)
                _g_data_loaded = True

            ok = _execute_trade(C, today, dt)
            if ok is False and now < '1500':
                _g_data_loaded = False
                print("  [%s] 选股池无可选项，盘中买入窗口内自动重试..." % STRATEGY_NAME)
                return
            if not _g_pending_buys and not _g_retry_queue and not _g_pending_sells:
                _write_daily_log(today, C)
                _g_today_done = True
            return

    def exit(self, C):
        global _g_cumulative_pnl

        # 确保日志写入（防止DEBUG_MODE下_g_today_done过早设置导致的日志漏写）
        if _g_last_date and not _g_log_written_today:
            _write_daily_log(_g_last_date, C)

        if SAFEMODE_ENABLED:
            print("\n[SAFEMODE] 策略退出（只读模式，跳过文件写入）")
            print("  最终持仓: %s" % sorted(_g_my_codes))
            return

        _g_cumulative_pnl = read_nav_file(INTRADAY_NAV_FILE)
        current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
        print("\n[%s] 策略退出" % STRATEGY_NAME)
        print("  最终持仓: %s" % sorted(_g_my_codes))
        print("  累计已实现盈亏: %+.0f  策略净值: %.0f" % (_g_cumulative_pnl, current_nav))
        write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)
        write_nav_file(INTRADAY_NAV_FILE, _g_cumulative_pnl)
        if _g_sell_engine:
            _g_sell_engine.save_state()
