"""
통일 시그널 데이터 모델
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Signal:
    strategy_name: str
    ticker: str
    ticker_name: str
    direction: str = "LONG"
    entry_price: float = 0.0
    target_price: float = 0.0
    stop_loss_price: float = 0.0
    target_pct: float = 0.0
    stop_loss_pct: float = 0.0
    rr_ratio: float = 0.0
    hold_days_min: int = 1
    hold_days_max: int = 5
    confidence: float = 0.5
    exec_timing: str = "EOD"
    category: str = ""
    grade: str = "B"
    signal_date: str = ""
    sector: str = ""
    supply_demand_grade: str = "B"
    entry_mode: str = "open"  # 'open' (다음날 시가) | 'close' (당일 종가)
    risk_warnings: List[str] = field(default_factory=list)

    def calc_rr_ratio(self):
        """Risk:Reward 비율 계산"""
        if self.stop_loss_pct != 0:
            self.rr_ratio = abs(self.target_pct / self.stop_loss_pct)
