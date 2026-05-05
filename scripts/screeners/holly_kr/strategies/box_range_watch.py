"""전략 37: Box Range Watch (관심 등록형, 돌파 직전) [등급 B+] [HYBRID]
60일 횡보 + 저항선 2회+ 터치 + 거래량 후반 감소 (세력 매집).
종가가 저항선 근접 시 — "곧 돌파할 후보".
출처: stock-screener-kr box_range 한국화."""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class BoxRangeWatch(BaseStrategy):
    name = "box_range_watch"
    category = "breakout"  # RR 2.5
    exec_timing = "HYBRID"
    grade = "B+"

    BOX_PERIOD = 60
    HALF_PERIOD = 30
    MAX_RANGE_PCT = 25.0
    RESISTANCE_TOLERANCE = 0.02  # 박스 상단 ±2%
    NEAR_RESISTANCE_PCT = 0.03   # 종가 vs 박스 상단 ≤3% (돌파 직전)

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < self.BOX_PERIOD + 10:
            return None

        row = df.iloc[-1]
        recent = df.tail(self.BOX_PERIOD)
        close = recent['Close']
        high = recent['High']
        low = recent['Low']
        volume = recent['Volume']

        # 박스 범위
        box_high = float(close.max())
        box_low = float(close.min())
        if box_low <= 0:
            return None
        range_pct = (box_high - box_low) / box_low * 100

        # 조건 1: 변동폭 25% 이내
        if range_pct > self.MAX_RANGE_PCT:
            return None

        # 조건 2: 추세 거의 없음 (전반/후반 중심값 차이 15% 이내)
        first_half = close.iloc[:self.HALF_PERIOD]
        second_half = close.iloc[self.HALF_PERIOD:]
        first_mid = (first_half.max() + first_half.min()) / 2
        second_mid = (second_half.max() + second_half.min()) / 2
        if min(first_mid, second_mid) <= 0:
            return None
        mid_diff_pct = abs(first_mid - second_mid) / min(first_mid, second_mid) * 100
        if mid_diff_pct > 15:
            return None

        # 조건 3: 박스 상단 ±2%에 2회+ 터치
        upper_band = box_high * (1 - self.RESISTANCE_TOLERANCE)
        touches = (high >= upper_band).sum()
        if touches < 2:
            return None

        # 조건 4: 거래량 후반 30일 < 전반 30일 × 0.95 (관심 이탈 = 매집)
        vol_first = volume.iloc[:self.HALF_PERIOD].mean()
        vol_second = volume.iloc[self.HALF_PERIOD:].mean()
        if vol_first <= 0 or vol_second >= vol_first * 0.95:
            return None

        # 조건 5: 종가가 저항선 ±3% 이내 (돌파 직전)
        proximity = (row['Close'] - box_high) / box_high
        if proximity > 0 or proximity < -self.NEAR_RESISTANCE_PCT:
            return None

        # 진입가 + ATR-based stop/target (breakout 5x/2x preset)
        ep = entry_price or row['Close']
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        # Darvas 정석: "박스 하단 직하". 박스 하단 ×0.997 (-0.3% 마진) vs ATR×2 cap
        box_stop_pct = (box_low * 0.997 / ep) - 1
        stop_loss_pct = max(box_stop_pct, atr_stop_pct, -0.08)
        target_pct = atr_target_pct

        proximity_pct = abs(proximity) * 100
        reason = (f"박스권 60일 횡보 (범위 {range_pct:.1f}%) · "
                  f"저항선 {touches}회 터치 · 후반 거래량 dry-up · "
                  f"종가 박스상단 {proximity_pct:.1f}% 이내 (돌파 직전)")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=2, hold_max=10, confidence=0.60,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
