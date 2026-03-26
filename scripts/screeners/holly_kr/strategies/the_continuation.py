"""전략 24: The Continuation [등급 B+] [HYBRID]
2일 연속 양봉 + 레인지 확장 = 모멘텀 지속."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class TheContinuation(BaseStrategy):
    name = "the_continuation"
    category = "momentum"
    exec_timing = "HYBRID"
    grade = "B+"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]

        # 전전일 양봉
        if prev2['Close'] <= prev2['Open']:
            return None

        # 전일 양봉
        if prev['Close'] <= prev['Open']:
            return None

        # 당일 레인지 > 20일 평균 레인지
        daily_range = df['High'] - df['Low']
        avg_range = daily_range.rolling(20).mean().iloc[-1]
        today_range = row['High'] - row['Low']
        if today_range <= avg_range:
            return None

        # 당일 양봉
        if row['Close'] <= row['Open']:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.97

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.04, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.60,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
