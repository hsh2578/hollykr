"""전략 23: Trend Play [등급 A] [HYBRID]
6개 이평 리본(5/10/20/50/100/200일) 완전 정배열 — 모든 시간축이 상승에 동의."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class TrendPlay(BaseStrategy):
    name = "trend_play"
    category = "trend"
    exec_timing = "HYBRID"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 210:
            return None

        row = df.iloc[-1]
        close = df['Close']

        # 6개 이평 계산
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma50 = close.rolling(50).mean()
        ma100 = close.rolling(100).mean()
        ma200 = close.rolling(200).mean()

        ma5_now = ma5.iloc[-1]
        ma10_now = ma10.iloc[-1]
        ma20_now = ma20.iloc[-1]
        ma50_now = ma50.iloc[-1]
        ma100_now = ma100.iloc[-1]
        ma200_now = ma200.iloc[-1]

        # 완전 정배열: MA5 > MA10 > MA20 > MA50 > MA100 > MA200
        if not (ma5_now > ma10_now > ma20_now > ma50_now > ma100_now > ma200_now):
            return None

        # 모든 이평 상승 중 (5일 전 대비)
        if ma5.iloc[-1] <= ma5.iloc[-6]:
            return None
        if ma10.iloc[-1] <= ma10.iloc[-6]:
            return None
        if ma20.iloc[-1] <= ma20.iloc[-6]:
            return None
        if ma50.iloc[-1] <= ma50.iloc[-6]:
            return None
        if ma100.iloc[-1] <= ma100.iloc[-6]:
            return None
        if ma200.iloc[-1] <= ma200.iloc[-6]:
            return None

        # MA50 상승 중 (10일 전 대비)
        if ma50.iloc[-1] <= ma50.iloc[-11]:
            return None

        # 종가가 MA5 근처 (2% 이내)
        dist_ma5 = abs(row['Close'] - ma5_now) / ma5_now
        if dist_ma5 > 0.02:
            return None

        ep = entry_price or row['Close']
        stop = max(ma20_now, ep * 0.95)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.07, stop_loss_pct=(stop / ep - 1),
            hold_min=5, hold_max=20, confidence=0.70,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
