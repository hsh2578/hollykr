"""전략: Donchian Channel Breakout [등급 A] [HYBRID]
Donchian (1960s) + Ed Seykota Market Wizards 검증 trend following.

핵심 룰:
- 종가 ≥ 20일 신고가 = long entry (Donchian 정통)
- Donchian이 발견, Seykota가 컴퓨터 시스템화 (1970s)
- 단순 + 강력. Market Wizards에서 가장 기억에 남는 트레이더 (Schwager)

한국 시장 적용:
- 20일 신고가 (Donchian 정통)
- 거래량 확장 (Seykota 추가)
- 200일 SMA 위 (장기 추세 확인)

출처:
- Schwager "Market Wizards" Ed Seykota interview
- Donchian channel rule (1960s)
- TurtleTrader.com Seykota documentation
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class DonchianBreakout(BaseStrategy):
    name = "donchian_breakout"
    category = "breakout"  # RR 2.5
    exec_timing = "HYBRID"
    grade = "A"

    DONCHIAN_PERIOD = 20    # Donchian 정통 20일 (Seykota도 사용)
    MIN_VOLUME_MULT = 1.5   # 50일 평균 1.5× (거래량 확장)
    MAX_VOLUME_MULT = 5.0   # climax 컷

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 220:  # 200일 SMA 필요
            return None

        row = df.iloc[-1]

        # ====================================================================
        # 1. Donchian 신고가 돌파 (정통 20일 채널)
        # ====================================================================
        # 직전 20일 (당일 제외) 최고가
        prior_high_20 = df['High'].iloc[-(self.DONCHIAN_PERIOD + 1):-1].max()
        if pd.isna(prior_high_20) or row['Close'] <= prior_high_20:
            return None

        # ====================================================================
        # 2. 200일 SMA 위 (장기 추세)
        # ====================================================================
        ma200 = df['Close'].rolling(200).mean().iloc[-1]
        if pd.isna(ma200) or row['Close'] < ma200:
            return None

        # ====================================================================
        # 3. 50일 SMA 위 (중기 추세)
        # ====================================================================
        ma50 = df['Close'].rolling(50).mean().iloc[-1]
        if pd.isna(ma50) or row['Close'] < ma50:
            return None

        # ====================================================================
        # 4. 거래량 확장 (Seykota: breakout은 volume confirmation)
        # ====================================================================
        vol_50 = df['Volume'].rolling(50).mean().iloc[-1]
        if pd.isna(vol_50) or vol_50 <= 0:
            return None
        vol_ratio = row['Volume'] / vol_50
        if vol_ratio < self.MIN_VOLUME_MULT or vol_ratio > self.MAX_VOLUME_MULT:
            return None

        # ====================================================================
        # 5. 양봉 confirmation
        # ====================================================================
        if row['Close'] <= row['Open']:
            return None

        # ====================================================================
        # 6. 갭다운 -3%+ 컷 (최근 5일)
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

        # ATR target/stop (breakout preset 5×/2×, RR 2.5)
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        # Stop: Donchian lower band (10일 신저가) 또는 ATR×2 또는 -7%
        recent_low_10 = df['Low'].iloc[-10:].min()
        donchian_stop_pct = (recent_low_10 * 0.997 / ep) - 1
        stop_loss_pct = max(donchian_stop_pct, atr_stop_pct, -0.07)
        target_pct = atr_target_pct

        confidence = 0.78

        reason = (f"Donchian 20일 신고가 돌파 · 200·50일 SMA 위 · "
                  f"vol {vol_ratio:.1f}× · 양봉")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=5, hold_max=30, confidence=confidence,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
