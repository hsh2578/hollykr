"""전략 28: The Vault [등급 B] [HYBRID]
10일 레인지 바닥에 갇혀 있던 종목이 전일 고가를 돌파하며 탈출."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import calc_rsi


class TheVault(BaseStrategy):
    name = "the_vault"
    category = "breakout"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 20:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]
        close = df['Close']

        # 전일 종가가 10일 레인지 하위 30%에 위치
        high_10d = df['High'].iloc[-11:-1].max()
        low_10d = df['Low'].iloc[-11:-1].min()
        range_10d = high_10d - low_10d
        if range_10d <= 0:
            return None

        prev_position = (prev['Close'] - low_10d) / range_10d
        if prev_position > 0.30:
            return None

        # 당일 종가 > 전일 고가
        if row['Close'] <= prev['High']:
            return None

        # RSI 반등: 당일 RSI > 전일 RSI
        rsi = calc_rsi(close, 14)
        if rsi.iloc[-1] <= rsi.iloc[-2]:
            return None

        # MA5 기울기 전환: 당일 MA5 > 전일 MA5
        ma5 = close.rolling(5).mean()
        if ma5.iloc[-1] <= ma5.iloc[-2]:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.97

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.04, stop_loss_pct=(stop / ep - 1),
            hold_min=2, hold_max=5, confidence=0.58,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
