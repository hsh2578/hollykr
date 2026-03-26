"""전략 15: Wake Up Call [등급 B] [HYBRID]
저유통 종목이 20일 신고가 갱신 + 이평 정배열 — 잠자던 종목이 깨어난다."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class WakeUpCall(BaseStrategy):
    name = "wake_up_call"
    category = "breakout"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]

        # 종가 = 20일 최고가 (신고가 갱신)
        high_20d = df['High'].rolling(20).max().iloc[-1]
        if row['Close'] < high_20d * 0.99:  # 1% 허용 범위 내
            return None

        # 이평 정배열: MA5 > MA20
        ma5 = df['Close'].rolling(5).mean().iloc[-1]
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        if ma5 <= ma20:
            return None

        # 거래량 > 20일 평균 × 1.5
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] < vol_avg * 1.5:
            return None

        # 양봉
        if row['Close'] <= row['Open']:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.95

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.06, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.55,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
