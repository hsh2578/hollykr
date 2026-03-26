"""전략 6: Volume Doesn't Lie [등급 A] [EOD]
4%+ 갭업 + 거래량 2배 폭발 = 방향 지속."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import close_position_ratio


class VolumeDoesntLie(BaseStrategy):
    name = "volume_doesnt_lie"
    category = "gap_momentum"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 20:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        # 갭업 4%+
        gap = (row['Open'] - prev['Close']) / prev['Close']
        if gap < 0.04:
            return None

        # 거래량 20일 평균의 2배
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] < vol_avg * 2.0:
            return None

        # 종가 >= 시가 (갭 유지)
        if row['Close'] < row['Open']:
            return None

        # 종가 레인지 상위 50% (position >= 0.5)
        if close_position_ratio(row) < 0.5:
            return None

        ep = entry_price or row['Close']
        # 손절: 당일 시가(갭업 시가) 하회 시 또는 entry x 0.95
        stop = max(row['Open'], ep * 0.95)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.06, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=5, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
