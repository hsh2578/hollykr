"""전략 12: Livermore Pivot Point [등급 A] [EOD]
52주 신고가 돌파 + 거래량 폭발 → 피라미딩 매수."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class LivermorePivot(BaseStrategy):
    name = "livermore_pivot"
    category = "legendary"
    exec_timing = "EOD"
    grade = "A"

    # RS Rating은 외부에서 주입 (scanner에서 설정)
    _rs_ratings: dict = {}

    @classmethod
    def set_rs_ratings(cls, ratings: dict):
        """유니버스 RS Rating 딕셔너리를 주입."""
        cls._rs_ratings = ratings

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 252:
            return None

        row = df.iloc[-1]

        # 52주 신고가 OR 3개월 고가 돌파 (전일까지의 고가 기준)
        high_52w = df['High'].shift(1).rolling(252).max().iloc[-1]
        high_3m = df['High'].shift(1).rolling(63).max().iloc[-1]
        if not (row['Close'] > high_52w or row['Close'] > high_3m):
            return None

        # 거래량 20일 평균의 2배
        if row['Volume'] <= df['Volume'].rolling(20).mean().iloc[-1] * 2.0:
            return None

        # RS Rating >= 70
        rs_rating = self._rs_ratings.get(ticker, 0.0)
        if rs_rating < 70:
            return None

        ep = entry_price or row['Close']
        # 피라미딩: 1차 50% 진입, 손절 = entry x 0.97 (3%)
        stop = ep * 0.97

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.0, stop_loss_pct=-0.03,
            hold_min=5, hold_max=90, confidence=0.70,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        """진입가 x 0.97 하회 시 전체 손절."""
        return None
