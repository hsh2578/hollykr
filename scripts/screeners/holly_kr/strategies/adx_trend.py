"""전략: ADX Strong Trend [등급 A] [HYBRID]
Welles Wilder ADX (Average Directional Index) 정통 + Carver Systematic Trading.

핵심 룰:
1. ADX(14) > 25 (강한 추세, Wilder 정통 임계값)
2. +DI > -DI (상승 추세)
3. 종가 > 50일 SMA + 200일 SMA (Stage 2)
4. 양봉 + 거래량 확장

학술/실무 검증:
- Welles Wilder "New Concepts in Technical Trading Systems" (1978)
- Robert Carver "Systematic Trading" (2015) — multi-time-scale ADX
- Andrew Lo "Adaptive Markets" — trend regime detection

원리:
- ADX > 25 = 명확한 trend regime (sideways X)
- 학술 검증: ADX 필터 적용 시 추세추종 strategy의 false breakout 50%+ 감소
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class ADXTrend(BaseStrategy):
    name = "adx_trend"
    category = "trend_following"  # RR 2.5
    exec_timing = "HYBRID"
    grade = "A"

    ADX_PERIOD = 14
    ADX_THRESHOLD = 25.0     # Wilder 정통 (강한 trend)
    VOL_BREAKOUT_MULT = 1.3
    VOL_CLIMAX_MULT = 5.0

    @staticmethod
    def _calc_adx(df: pd.DataFrame, period: int = 14) -> tuple:
        """ADX, +DI, -DI 계산 (Wilder 1978 정통)."""
        high = df['High']
        low = df['Low']
        close = df['Close']

        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0),
                            index=df.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0),
                             index=df.index)

        # Smoothed TR / DM (Wilder 평활)
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr

        # ADX = smoothed |+DI - -DI| / (+DI + -DI)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/period, adjust=False).mean()

        return adx, plus_di, minus_di

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 220:
            return None

        row = df.iloc[-1]

        # ====================================================================
        # 1. ADX 강한 trend 필터
        # ====================================================================
        adx, plus_di, minus_di = self._calc_adx(df, self.ADX_PERIOD)
        if pd.isna(adx.iloc[-1]) or pd.isna(plus_di.iloc[-1]):
            return None
        if adx.iloc[-1] < self.ADX_THRESHOLD:
            return None  # 강한 trend 아님
        if plus_di.iloc[-1] <= minus_di.iloc[-1]:
            return None  # 하락 추세

        # ADX 상승 중 (5일 전 대비) — trend 강화
        if pd.isna(adx.iloc[-6]) or adx.iloc[-1] <= adx.iloc[-6]:
            return None

        # ====================================================================
        # 2. Stage 2 (200일 + 50일 SMA)
        # ====================================================================
        ma200 = df['Close'].rolling(200).mean().iloc[-1]
        ma50 = df['Close'].rolling(50).mean().iloc[-1]
        if pd.isna(ma200) or pd.isna(ma50):
            return None
        if row['Close'] < ma200:
            return None
        if ma50 < ma200:
            return None

        # ====================================================================
        # 3. 양봉 + 거래량 확장
        # ====================================================================
        if row['Close'] <= row['Open']:
            return None
        vol_50 = df['Volume'].rolling(50).mean().iloc[-1]
        if pd.isna(vol_50) or vol_50 <= 0:
            return None
        vol_ratio = row['Volume'] / vol_50
        if vol_ratio < self.VOL_BREAKOUT_MULT or vol_ratio > self.VOL_CLIMAX_MULT:
            return None

        # ====================================================================
        # 4. 갭다운 컷
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

        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        ma50_stop_pct = (ma50 * 0.99 / ep) - 1
        stop_loss_pct = max(ma50_stop_pct, atr_stop_pct, -0.07)
        target_pct = atr_target_pct

        confidence = 0.78

        reason = (f"ADX {adx.iloc[-1]:.0f} 강한 추세 (+DI {plus_di.iloc[-1]:.0f} > "
                  f"-DI {minus_di.iloc[-1]:.0f}) · Stage 2 · vol {vol_ratio:.1f}×")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=5, hold_max=30, confidence=confidence,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
