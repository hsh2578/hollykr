"""전략 14: Float On [등급 B] [HYBRID]
저유통주 + RS 강세 + 저항 돌파 — 공급 부족 상태에서 수요 유입."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class FloatOn(BaseStrategy):
    name = "float_on"
    category = "breakout"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 63:
            return None

        row = df.iloc[-1]

        # RS Rating 근사: 3개월 수익률 백분위 >= 70 (간이 방식)
        ret_3m = row['Close'] / df['Close'].iloc[-63] - 1 if len(df) >= 63 else 0
        if ret_3m < 0.15:  # 상위 ~30% 수준의 3개월 수익률 문턱
            return None

        # 종가 > 20일 최고가 (저항 돌파)
        high_20d = df['High'].rolling(20).max().iloc[-2]  # 전일까지의 20일 고가
        if row['Close'] <= high_20d:
            return None

        # 거래량 > 20일 평균 × 2.0
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] < vol_avg * 2.0:
            return None

        # 양봉
        if row['Close'] <= row['Open']:
            return None

        # 당일 수익률 > 1% (당일 강세 확인)
        daily_ret = (row['Close'] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]
        if daily_ret <= 0.01:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.97

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.04, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.55,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
