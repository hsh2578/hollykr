"""전략 19: Bullish Pullback [등급 A-] [HYBRID]
강한 종목의 20-30% 풀백 + 3일 연속 양봉 반등 확인."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class BullishPullback(BaseStrategy):
    name = "bullish_pullback"
    category = "pullback"
    exec_timing = "HYBRID"
    grade = "A-"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 120:
            return None

        row = df.iloc[-1]

        # 상승 추세였음: 60일 최고가 > 120일 이평
        high_60d = df['High'].rolling(60).max().iloc[-1]
        ma120 = df['Close'].rolling(120).mean().iloc[-1]
        if high_60d <= ma120:
            return None

        # 현재 종가가 60일 고가 대비 20~30% 하락 (풀백)
        pullback = (high_60d - row['Close']) / high_60d
        if pullback < 0.20 or pullback > 0.30:
            return None

        # 3일 연속 양봉 (반등 확인)
        for i in range(-3, 0):
            if df['Close'].iloc[i] <= df['Open'].iloc[i]:
                return None

        # 거래량 증가 추세 (최근 3일 평균 > 10일 평균)
        vol_3d = df['Volume'].tail(3).mean()
        vol_10d = df['Volume'].rolling(10).mean().iloc[-1]
        if vol_3d < vol_10d:
            return None

        ep = entry_price or row['Close']
        recent_low = df['Low'].tail(10).min()
        stop = max(recent_low, ep * 0.92)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.08, stop_loss_pct=(stop / ep - 1),
            hold_min=3, hold_max=10, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
