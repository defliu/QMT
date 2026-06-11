# coding=utf-8
"""回测参数与结果数据类。"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BacktestParams:
    """回测参数"""
    stock_codes: list[str] = None        # 股票代码列表 ['000001.SZ', '600519.SH', ...]
    start_date: str = '2024-01-01'        # 开始日期
    end_date: str = '2024-12-31'          # 结束日期
    period: str = '1d'                    # K线周期
    initial_capital: float = 100000.0     # 初始资金
    slippage: float = 0.001               # 滑点比例 0.1%
    commission_rate: float = 0.00025      # 佣金 万2.5
    tax_rate: float = 0.0001              # 印花税 万1
    benchmark: str = '000300.SH'          # 基准指数

    def __post_init__(self):
        if self.stock_codes is None:
            self.stock_codes = []


@dataclass
class BacktestResult:
    """回测结果"""
    success: bool = False
    error: Optional[str] = None

    # 收益指标
    total_return: float = 0.0              # 总收益率 (小数, 0.15 = 15%)
    annualized_return: float = 0.0         # 年化收益率
    benchmark_return: float = 0.0          # 基准收益率

    # 风险指标
    max_drawdown: float = 0.0              # 最大回撤 (小数)
    sharpe_ratio: float = 0.0              # 夏普比率
    volatility: float = 0.0                # 年化波动率

    # 交易统计
    total_trades: int = 0                  # 总交易次数
    win_trades: int = 0                    # 盈利交易次数
    lose_trades: int = 0                   # 亏损交易次数
    win_rate: float = 0.0                  # 胜率
    profit_factor: float = 0.0             # 盈亏比
    avg_hold_days: float = 0.0             # 平均持仓天数

    # 每月收益明细
    monthly_returns: dict[str, float] = field(default_factory=dict)

    # 原始数据
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    drawdown_curve: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转可序列化字典。"""
        d = {
            'success': self.success,
            'error': self.error,
            'total_return': self.total_return,
            'annualized_return': self.annualized_return,
            'benchmark_return': self.benchmark_return,
            'max_drawdown': self.max_drawdown,
            'sharpe_ratio': self.sharpe_ratio,
            'volatility': self.volatility,
            'total_trades': self.total_trades,
            'win_trades': self.win_trades,
            'lose_trades': self.lose_trades,
            'win_rate': self.win_rate,
            'profit_factor': self.profit_factor,
            'avg_hold_days': self.avg_hold_days,
        }
        if self.monthly_returns:
            d['monthly_returns'] = self.monthly_returns
        return d

    @property
    def status(self) -> str:
        """PASS/FAIL 状态。"""
        if not self.success:
            return 'FAIL'
        if self.sharpe_ratio >= 1.0 and abs(self.max_drawdown) < 0.08:
            return 'PASS'
        return 'FAIL'
