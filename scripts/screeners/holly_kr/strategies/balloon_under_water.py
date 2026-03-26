"""전략 30: Balloon Under Water [등급 B] [HYBRID]
극단적 과매도(Z-Score <= -3.0) + 수급 전환 시 반등 — 물속 풍선은 떠오른다."""

from typing import Optional, Dict
import pandas as pd
import numpy as np
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class BalloonUnderWater(BaseStrategy):
    name = "balloon_under_water"
    category = "mean_reversion"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]
        close = df['Close']

        # Z-Score: (종가 - MA20) / std20
        ma20 = close.rolling(20).mean().iloc[-1]
        std20 = close.rolling(20).std().iloc[-1]
        if std20 == 0 or np.isnan(std20):
            return None

        z_score = (row['Close'] - ma20) / std20

        # Z-Score <= -3.0 (극단적 과매도)
        if z_score > -3.0:
            return None

        # 당일 양봉
        if row['Close'] <= row['Open']:
            return None

        # 거래량 > 5일 평균
        avg_vol_5 = df['Volume'].rolling(5).mean().iloc[-1]
        if row['Volume'] <= avg_vol_5:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.95

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.07, stop_loss_pct=(stop / ep - 1),
            hold_min=3, hold_max=7, confidence=0.62,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
