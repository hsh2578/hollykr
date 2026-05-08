"""전략: Elder Triple Screen [등급 A] [HYBRID]
Alexander Elder "Trading for a Living" (1993) 정통 3-Screen 방법.

핵심 룰 (3 screen filter):
1. Screen 1 — 주봉 추세: 주봉 13주 EMA 우상향 (장기 강세)
2. Screen 2 — 일봉 oversold: RSI(14) < 35 (단기 pullback)
3. Screen 3 — Entry trigger: 일봉 양봉 + 직전 swing low 위

학술/실무 검증:
- Alexander Elder "Trading for a Living" (1993) — 3-Screen 정통
- 핵심: "Trade with the long-term tide, against the short-term wave"
- Schwager Market Wizards에서 인용

한국 시장 적응:
- 주봉 EMA → 일봉으로 13×5=65일 EMA 활용
- 일봉 RSI 14 < 35
- 양봉 + 거래량 확인
- 200일 SMA 위 (안전 추가)
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import calc_rsi


class ElderTripleScreen(BaseStrategy):
    name = "elder_triple_screen"
    category = "pullback"  # RR 2.0
    exec_timing = "HYBRID"
    grade = "A"

    LONG_EMA = 65        # 13주 EMA 등가 (일봉 65일)
    RSI_PERIOD = 14
    RSI_OVERSOLD = 35    # Elder 정통 (35는 보수적, 30보다 시그널 ↑)
    SWING_LOW_LOOKBACK = 10

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 220:  # 200일 SMA 안전 추가
            return None

        row = df.iloc[-1]
        close = df['Close']

        # ====================================================================
        # 1. Screen 1 — 장기 추세 (Elder: 주봉 13주 EMA 우상향)
        # 한국 적응: 일봉 65일 EMA (13주 × 5거래일)
        # ====================================================================
        ema_long = close.ewm(span=self.LONG_EMA, adjust=False).mean()
        if pd.isna(ema_long.iloc[-1]) or pd.isna(ema_long.iloc[-6]):
            return None
        # EMA 우상향 (5일 전 대비)
        if ema_long.iloc[-1] <= ema_long.iloc[-6]:
            return None
        # 종가 > 65일 EMA (강세)
        if row['Close'] < ema_long.iloc[-1]:
            return None

        # 안전 추가: 200일 SMA 위
        ma200 = close.rolling(200).mean().iloc[-1]
        if pd.isna(ma200) or row['Close'] < ma200:
            return None

        # ====================================================================
        # 2. Screen 2 — 일봉 oversold (단기 pullback in uptrend)
        # ====================================================================
        rsi = calc_rsi(close, self.RSI_PERIOD)
        if pd.isna(rsi.iloc[-1]):
            return None
        if rsi.iloc[-1] >= self.RSI_OVERSOLD:
            return None  # oversold 아님 = 진입 X

        # ====================================================================
        # 3. Screen 3 — Entry trigger
        # ====================================================================
        # 양봉 (전일 종가 위로 반등)
        if row['Close'] <= df['Close'].iloc[-2]:
            return None
        # 양봉 candle (시가 < 종가)
        if row['Close'] <= row['Open']:
            return None
        # 거래량 5일 평균 이상
        vol_5 = df['Volume'].rolling(5).mean().iloc[-1]
        if pd.isna(vol_5) or row['Volume'] < vol_5:
            return None

        # ====================================================================
        # 4. 갭다운 -3%+ 컷 (최근 5일)
        # ====================================================================
        for i in range(1, 6):
            if i + 1 > len(df):
                break
            today = df.iloc[-i]
            yest = df.iloc[-i - 1]
            if yest['Close'] > 0:
                gap = (today['Open'] - yest['Close']) / yest['Close']
                if gap < -0.03:
                    return None

        ep = entry_price or row['Close']

        # ATR target/stop (pullback preset 3×/1.5×, RR 2.0)
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        # Stop: 10일 swing low (Elder 정통) 또는 ATR×1.5 또는 -5%
        swing_low = df['Low'].iloc[-self.SWING_LOW_LOOKBACK:].min()
        swing_low_stop_pct = (swing_low * 0.997 / ep) - 1
        stop_loss_pct = max(swing_low_stop_pct, atr_stop_pct, -0.05)
        target_pct = atr_target_pct

        confidence = 0.75

        reason = (f"Elder 3-Screen · 65일 EMA 우상향 · "
                  f"RSI14 {rsi.iloc[-1]:.0f} oversold · 양봉 reversal · 200SMA 위")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=2, hold_max=10, confidence=confidence,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
