"""전략 4: Snap Back Long [등급 A] [EOD]
5일 연속 하락 + RSI 과매도 → 첫 양봉에 반등 탑승."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import calc_rsi


class SnapBackLong(BaseStrategy):
    name = "snap_back_long"
    category = "mean_reversion"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 60:
            return None

        row = df.iloc[-1]

        # 최근 5일 중 3일 이상 음봉 (종가 < 전일 종가)
        bearish = (df['Close'] < df['Close'].shift(1)).tail(5).sum()
        if bearish < 3:
            return None

        # 5일 누적 수익률 < -5%
        ret_5d = row['Close'] / df['Close'].iloc[-6] - 1
        if ret_5d >= -0.08:
            return None

        # RSI(14) < 35
        rsi = calc_rsi(df['Close'], 14)
        if rsi.iloc[-1] >= 30:
            return None

        # 당일 양봉 (종가 > 전일 종가) + 거래량 > 5일 평균
        if row['Close'] <= df['Close'].iloc[-2]:
            return None
        if row['Volume'] <= df['Volume'].rolling(5).mean().iloc[-1]:
            return None

        # 60일 이평이 상승 중 (장기 추세 살아있음)
        ma60 = df['Close'].rolling(60).mean()
        if ma60.iloc[-1] <= ma60.iloc[-6]:
            return None

        ep = entry_price or row['Close']
        low_5d = df['Low'].tail(5).min()
        stop = max(low_5d, ep * 0.96)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.05, stop_loss_pct=(stop / ep - 1),
            hold_min=3, hold_max=7, confidence=0.70,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
