"""전략 27: Nice Chart [등급 A-] [HYBRID]
전일 고가 돌파 + 이평 정배열 + RSI 적당 + 거래량 증가 — 차트가 예쁘다."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import calc_rsi


class NiceChart(BaseStrategy):
    name = "nice_chart"
    category = "multi_factor"
    exec_timing = "HYBRID"
    grade = "A-"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 30:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]
        close = df['Close']

        # 조건 1: 종가 > 전일 고가
        if row['Close'] <= prev['High']:
            return None

        # 조건 2: MA5 > MA20 (단기 정배열)
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        if ma5 <= ma20:
            return None

        # 조건 3: 45 < RSI(14) < 65 (과열/과매도 아닌 적당한 구간)
        rsi = calc_rsi(close, 14)
        rsi_now = rsi.iloc[-1]
        if rsi_now <= 45 or rsi_now >= 65:
            return None

        # 조건 4: 거래량 > 20일 평균 × 1.5
        avg_vol = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] <= avg_vol * 1.5:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.96

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.06, stop_loss_pct=(stop / ep - 1),
            hold_min=2, hold_max=5, confidence=0.68,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
