# coding=utf-8
"""仓位计算 — 凯利公式"""


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
