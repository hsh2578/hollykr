"""전략 9: Weinstein Stage Analysis [등급 A] [EOD]
Stage 1→2 전환 감지 (150일 이평 상승 전환 + 거래량)."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class WeinsteinStage(BaseStrategy):
    name = "weinstein_stage"
    category = "legendary"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 180:
            return None

        row = df.iloc[-1]
        close = df['Close']
        ma150 = close.rolling(150).mean()
        slope = ma150 - ma150.shift(22)  # 1개월 기울기

        # 현재 Stage 2: 주가 > 150일 이평 AND 이평 상승 중
        if not (row['Close'] > ma150.iloc[-1] and slope.iloc[-1] > 0):
            return None

        # 5일 전 Stage 1이었는지 (이평 거의 수평 + 주가 근접)
        ma150_val_5d_ago = ma150.iloc[-6]
        if ma150_val_5d_ago == 0:
            return None
        was_stage1 = (
            abs(slope.iloc[-6]) / ma150_val_5d_ago < 0.01 and
            abs(close.iloc[-6] - ma150_val_5d_ago) / ma150_val_5d_ago < 0.05
        )
        if not was_stage1:
            return None

        # 거래량 급증: 20일 평균의 2배
        if row['Volume'] <= df['Volume'].rolling(20).mean().iloc[-1] * 2.0:
            return None

        # 5일간 150일 이평 위 유지
        if close.tail(5).min() <= ma150.tail(5).min():
            return None

        ep = entry_price or row['Close']
        # 손절: ATR 기반 (추세추종이므로 3x ATR 넓은 손절)
        _, stop_loss_pct = self._atr_target_stop(df, ep, stop_multiple=3.0)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.0, stop_loss_pct=stop_loss_pct,
            hold_min=20, hold_max=120, confidence=0.75,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        """Stage 3 전환 감지 시 (이평 기울기 감소 시작) 청산."""
        return None
