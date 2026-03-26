"""전략 2: Engulfing [등급 A] [EOD]
전일 음봉을 당일 양봉이 완전히 삼키면 추세 전환."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class Engulfing(BaseStrategy):
    name = "engulfing"
    category = "breakout"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 3:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        # 전일 음봉
        if prev['Close'] >= prev['Open']:
            return None

        # 장악형: 당일 저가 < 전일 저가, 당일 종가 > 전일 고가, 양봉
        if not (row['Low'] < prev['Low'] and row['Close'] > prev['High'] and row['Close'] > row['Open']):
            return None

        # 레인지 확장: 당일 > 전일 x 1.2
        today_range = row['High'] - row['Low']
        prev_range = prev['High'] - prev['Low']
        if prev_range > 0 and today_range < prev_range * 1.2:
            return None

        # 거래량: 전일의 1.5배
        if row['Volume'] < prev['Volume'] * 1.5:
            return None

        ep = entry_price or row['Close']
        stop = max(row['Low'], ep * 0.97)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.04, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
