"""전략 1: Pushing The Spring [등급 A] [EOD]
좁은 횡보 후 거래량 돌파 — 스프링이 튕기듯 상승."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import close_position_ratio


class PushingTheSpring(BaseStrategy):
    name = "pushing_the_spring"
    category = "breakout"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 20:
            return None

        row = df.iloc[-1]

        # 레인지 스퀴즈: 5일 레인지 < 10일 레인지의 60%
        r5 = (df['High'].tail(5).max() - df['Low'].tail(5).min()) / df['Close'].tail(5).mean()
        r10 = (df['High'].tail(10).max() - df['Low'].tail(10).min()) / df['Close'].tail(10).mean()
        if r5 >= r10 * 0.6:
            return None

        # 캔들 몸통 축소: 최근 3일 몸통 < 20일 평균의 50%
        body = (df['Close'] - df['Open']).abs()
        if body.tail(3).mean() >= body.tail(20).mean() * 0.5:
            return None

        # 돌파: 종가 > 5일 고가 (전일까지의 5일 고가)
        resistance = df['High'].shift(1).rolling(5).max().iloc[-1]
        if row['Close'] <= resistance:
            return None

        # 거래량 확인: 20일 평균의 2배
        if row['Volume'] <= df['Volume'].rolling(20).mean().iloc[-1] * 2.0:
            return None

        # 종가 강도: 레인지 상위 30% (position >= 0.7)
        if close_position_ratio(row) < 0.7:
            return None

        ep = entry_price or row['Close']
        stop = max(df['Low'].tail(5).min(), ep * 0.97)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.03, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=5, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        """5일 이평 하회 시 청산."""
        if 'ma5' in position and current_row['Close'] < position['ma5']:
            return 'condition'
        return None
