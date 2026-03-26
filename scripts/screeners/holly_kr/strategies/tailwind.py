"""전략 22: Tailwind [등급 A-] [HYBRID]
이평 완전 정배열 + 20일 이평 터치 반등 — 순풍을 타고 계속 올라간다."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class Tailwind(BaseStrategy):
    name = "tailwind"
    category = "trend_following"
    exec_timing = "HYBRID"
    grade = "A-"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 65:
            return None

        row = df.iloc[-1]

        ma5 = df['Close'].rolling(5).mean()
        ma20 = df['Close'].rolling(20).mean()
        ma60 = df['Close'].rolling(60).mean()

        ma5_now = ma5.iloc[-1]
        ma20_now = ma20.iloc[-1]
        ma60_now = ma60.iloc[-1]

        # 이평 정배열: MA5 > MA20 > MA60
        if not (ma5_now > ma20_now > ma60_now):
            return None

        # 모든 이평 상승 중 (현재 > 5일 전)
        if ma5.iloc[-1] <= ma5.iloc[-6]:
            return None
        if ma20.iloc[-1] <= ma20.iloc[-6]:
            return None
        if ma60.iloc[-1] <= ma60.iloc[-6]:
            return None

        # 종가가 MA20 위에서 근접 (0~2% 위) — MA20 아래면 제외
        if row['Close'] < ma20_now:
            return None
        ma20_dist = (row['Close'] - ma20_now) / ma20_now
        if ma20_dist > 0.02:
            return None

        # 당일 양봉 (MA20 지지 반등)
        if row['Close'] <= row['Open']:
            return None

        # 거래량 > 20일 평균
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] < vol_avg:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.96  # MA20 바로 위에서 진입하므로 4% 고정 손절

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.05, stop_loss_pct=(stop / ep - 1),
            hold_min=2, hold_max=5, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
