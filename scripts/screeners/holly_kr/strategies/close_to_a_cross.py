"""전략 17: Close to a Cross [등급 A-] [HYBRID]
5일 이평이 50일 이평을 골든크로스 — 기관들이 주시하는 신호."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class CloseToACross(BaseStrategy):
    name = "close_to_a_cross"
    category = "breakout"
    exec_timing = "HYBRID"
    grade = "A-"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 55:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        ma5 = df['Close'].rolling(5).mean()
        ma50 = df['Close'].rolling(50).mean()

        # 골든크로스: 전일 MA5 < MA50, 당일 MA5 > MA50
        if ma5.iloc[-2] >= ma50.iloc[-2]:
            return None
        if ma5.iloc[-1] <= ma50.iloc[-1]:
            return None

        # 당일 수익률 >= 2%
        daily_ret = (row['Close'] - prev['Close']) / prev['Close']
        if daily_ret < 0.02:
            return None

        # 거래량 > 20일 평균 × 1.5
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] < vol_avg * 2.0:
            return None

        ep = entry_price or row['Close']
        target_pct, stop_loss_pct = self._atr_target_stop(df, ep, target_multiple=3.0, stop_multiple=2.0)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=3, hold_max=5, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
