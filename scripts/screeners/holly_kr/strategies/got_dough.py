"""전략 25: Got Dough Wants to Go [등급 B] [HYBRID]
대형주(시총 1조+) + 모멘텀 — 돈 있는 놈이 가려고 한다."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class GotDough(BaseStrategy):
    name = "got_dough"
    category = "momentum"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0,
             market_cap: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]
        close = df['Close']

        # 대형주: 시총 1조 이상 (market_cap 단위 = 억원, 10000억 = 1조)
        if market_cap < 10000:
            return None

        # MA20 상승 중
        ma20 = close.rolling(20).mean()
        if ma20.iloc[-1] <= ma20.iloc[-6]:
            return None

        # 당일 양봉
        if row['Close'] <= row['Open']:
            return None

        # 거래량 > 20일 평균
        avg_vol = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] <= avg_vol:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.98

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.03, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=5, confidence=0.55,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
