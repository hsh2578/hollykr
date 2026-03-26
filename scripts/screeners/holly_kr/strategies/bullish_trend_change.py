"""전략 13: Bullish Trend Change [등급 B+] [HYBRID]
하락 추세에서 상승 추세로 전환 — 20일 이평 상향 돌파 + 거래량 2배."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import close_position_ratio


class BullishTrendChange(BaseStrategy):
    name = "bullish_trend_change"
    category = "breakout"
    exec_timing = "HYBRID"
    grade = "B+"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        ma20 = df['Close'].rolling(20).mean()

        # 전일 종가 < 20일 이평 (하락 추세)
        if prev['Close'] >= ma20.iloc[-2]:
            return None

        # 당일 종가 > 20일 이평 (상향 돌파)
        if row['Close'] <= ma20.iloc[-1]:
            return None

        # MA20 슬로프 상승 (ma20 > ma20 5일전) — 모멘텀 동반 크로스
        if ma20.iloc[-1] <= ma20.iloc[-6]:
            return None

        # 거래량 > 20일 평균 × 2.0
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] < vol_avg * 2.0:
            return None

        # 종가 레인지 상위 30% (close position >= 0.7)
        if close_position_ratio(row) < 0.7:
            return None

        ep = entry_price or row['Close']
        stop = max(ma20.iloc[-1], ep * 0.975)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.06, stop_loss_pct=(stop / ep - 1),
            hold_min=2, hold_max=5, confidence=0.60,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
