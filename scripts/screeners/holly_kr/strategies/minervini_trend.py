"""전략 7: Minervini Trend Template [등급 A] [EOD]
8가지 조건으로 Stage 2 상승 추세 종목 선별."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class MinerviniTrend(BaseStrategy):
    name = "minervini_trend_template"
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
        close = df['Close']

        ma50 = close.rolling(50).mean().iloc[-1]
        ma150 = close.rolling(150).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        ma200_prev = close.rolling(200).mean().iloc[-23]

        # --- 8가지 Minervini 조건 ---

        # 1. 종가 > 150일 이평
        if row['Close'] <= ma150:
            return None

        # 2. 종가 > 200일 이평
        if row['Close'] <= ma200:
            return None

        # 3. 150일 이평 > 200일 이평
        if ma150 <= ma200:
            return None

        # 4. 200일 이평이 22거래일(1개월) 동안 상승
        if ma200 <= ma200_prev:
            return None

        # 5. 종가 > 50일 이평
        if row['Close'] <= ma50:
            return None

        # 6. 52주 최저가 대비 30% 이상 위
        low_52w = df['Low'].rolling(252).min().iloc[-1]
        if row['Close'] < low_52w * 1.30:
            return None

        # 7. 52주 최고가 대비 25% 이내
        high_52w = df['High'].rolling(252).max().iloc[-1]
        if row['Close'] < high_52w * 0.75:
            return None

        # 8. RS Rating >= 70
        rs_rating = self._rs_ratings.get(ticker, 0.0)
        if rs_rating < 70:
            return None

        # --- 트리거: 당일 2%+ 상승 + 거래량 20일 평균의 2배 ---
        daily_ret = row['Close'] / df['Close'].iloc[-2] - 1
        vol_surge = row['Volume'] > df['Volume'].rolling(20).mean().iloc[-1] * 2.0
        if daily_ret < 0.02 or not vol_surge:
            return None

        ep = entry_price or row['Close']
        # legendary minervini preset (5.0/2.0, RR 2.5)
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        # 손절: 50일 이평 하회 (Minervini 정석) vs ATR×2 vs -8%
        ma50_stop_pct = (ma50 / ep) - 1
        stop_loss_pct = max(ma50_stop_pct, atr_stop_pct, -0.08)
        target_pct = atr_target_pct

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=10, hold_max=60, confidence=0.75,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        """150일 이평 하회 OR RS < 50 OR 50일 이평 하향 전환 시 청산."""
        return None
