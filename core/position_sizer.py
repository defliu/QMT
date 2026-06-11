# coding=utf-8
"""仓位计算 — 凯利公式 + 追踪止损"""


# ============================================================
#  原始骨架函数保留
# ============================================================

def kelly_criterion(win_rate, avg_win, avg_loss):
    """凯利公式: f* = (p*b - q)/b，保守版减半，上限20%"""
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    if win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win / avg_loss
    q = 1 - win_rate
    f = (win_rate * b - q) / b
    if f <= 0:
        return 0.0
    conservative = f / 2
    return min(conservative, 0.20)


def get_position_by_kelly(available_cash, stock_price, strategy_stats):
    """根据凯利公式算股数"""
    if stock_price <= 0 or available_cash <= 0:
        return 0
    win_rate = strategy_stats.get('win_rate', 0.5)
    avg_win = strategy_stats.get('avg_win', 0.05)
    avg_loss = strategy_stats.get('avg_loss', 0.03)
    kelly_pct = kelly_criterion(win_rate, avg_win, avg_loss)
    amount = available_cash * kelly_pct
    shares = int(amount / stock_price / 100) * 100
    return max(shares, 0)


# ============================================================
#  追踪止损
# ============================================================

TRAILING_STOP_DRAWDOWN_1 = 0.12
TRAILING_STOP_DRAWDOWN_2 = 0.10
TRAILING_STOP_DRAWDOWN_3 = 0.08


def check_trailing_stop(current_price, highest_price, cost_price):
    """
    移动止盈检查。
    返回 (should_sell: bool, reason: str)

    阶梯回撤:
      盈利 < 20%: 回撤 12% 止盈
      20% <= 盈利 < 40%: 回撤 10% 止盈
      盈利 >= 40%: 回撤 8% 止盈
    """
    if highest_price <= 0 or current_price <= 0:
        return False, ""

    drawdown = (highest_price - current_price) / highest_price
    profit_pct = (current_price - cost_price) / cost_price if cost_price > 0 else 0

    if profit_pct < 0:
        return False, ""

    if profit_pct < 0.20:
        max_dd = TRAILING_STOP_DRAWDOWN_1
    elif profit_pct < 0.40:
        max_dd = TRAILING_STOP_DRAWDOWN_2
    else:
        max_dd = TRAILING_STOP_DRAWDOWN_3

    if drawdown >= max_dd:
        locked = profit_pct - drawdown
        return True, (
            "追踪止盈(高%.2f->现%.2f,回撤%.1f%%,锁定%.1f%%)" % (
                highest_price, current_price, drawdown * 100, locked * 100
            )
        )
    return False, ""
