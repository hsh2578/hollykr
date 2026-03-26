"""전략 26: The Guiding Hand [등급 B] [HYBRID]
갭업 후 횡보 → 이평이 가격을 안내하듯 밀어올려서 추가 상승."""

from typing import Optional, Dict
import pandas as pd
import numpy as np
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class GuidingHand(BaseStrategy):
    name = "guiding_hand"
    category = "breakout"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 30:
            return None

        row = df.iloc[-1]

        # 최근 5일 내 2%+ 갭업이 있었는지 확인
        gap_found = False
        for i in range(-5, 0):
            if abs(i) >= len(df):
                continue
            day_open = df.iloc[i]['Open']
            prev_close = df.iloc[i - 1]['Close']
            if prev_close > 0 and (day_open / prev_close - 1) >= 0.02:
                gap_found = True
                break

        if not gap_found:
            return None

        # 최근 3일 타이트 레인지: 각 일 레인지 < 20일 평균 레인지 × 0.6
        daily_range = df['High'] - df['Low']
        avg_range = daily_range.rolling(20).mean().iloc[-4]  # 횡보 시작 전 기준
        for i in range(-3, 0):
            day_range = df.iloc[i]['High'] - df.iloc[i]['Low']
            if day_range >= avg_range * 0.6:
                return None

        # 당일 종가 > 최근 3일 고가
        high_3d = df['High'].iloc[-4:-1].max()
        if row['Close'] <= high_3d:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.97

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.04, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.58,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
