"""전략: Bollinger Squeeze Breakout [등급 A] [HYBRID]
John Bollinger 정통 + Linda Raschke 검증.

핵심 룰:
1. Bollinger Band Width (BBW) 6개월 내 최저 quartile (squeeze)
2. 종가 > BB upper (squeeze 후 돌파)
3. 200일 SMA 위 (장기 추세)
4. 거래량 50일 평균 1.5배+ (확장)

학술/실무 검증:
- John Bollinger "Bollinger on Bollinger Bands" (2001)
- Linda Raschke "Street Smarts" (1996) — Squeeze 패턴
- StockCharts.com Bollinger Squeeze Breakout

원리:
- 낮은 변동성 = 큰 변동성 직전 (변동성 군집화)
- BB squeeze는 매수 압력 누적의 신호
- 돌파 + 거래량 = 진짜 추세 시작
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class BollingerSqueeze(BaseStrategy):
    name = "bollinger_squeeze"
    category = "breakout"  # RR 2.5
    exec_timing = "HYBRID"
    grade = "A"

    BB_PERIOD = 20
    BB_STD = 2.0
    SQUEEZE_LOOKBACK = 126   # 6개월 BBW 비교
    SQUEEZE_QUANTILE = 0.25  # 하위 25% (squeeze)
    VOL_BREAKOUT_MULT = 1.5
    VOL_CLIMAX_MULT = 5.0

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 220:  # 200일 SMA + 20일 BB + 충분한 lookback
            return None

        row = df.iloc[-1]
        close = df['Close']

        # ====================================================================
        # 1. Bollinger Band 계산
        # ====================================================================
        bb_mid = close.rolling(self.BB_PERIOD).mean()
        bb_std = close.rolling(self.BB_PERIOD).std()
        bb_upper = bb_mid + self.BB_STD * bb_std
        bb_lower = bb_mid - self.BB_STD * bb_std
        bb_width = (bb_upper - bb_lower) / bb_mid  # 정규화

        if pd.isna(bb_width.iloc[-1]):
            return None

        # ====================================================================
        # 2. Squeeze 검출 — BBW 6개월 최저 quantile (하위 25%)
        # ====================================================================
        bbw_recent = bb_width.iloc[-self.SQUEEZE_LOOKBACK:]
        if pd.isna(bbw_recent).any():
            return None
        squeeze_threshold = bbw_recent.quantile(self.SQUEEZE_QUANTILE)
        # 직전 5일 중 squeeze 영역 (BBW < threshold) 있어야 (압축 직후)
        recent_5_in_squeeze = (bb_width.iloc[-6:-1] <= squeeze_threshold).sum()
        if recent_5_in_squeeze < 2:
            return None  # 직전 squeeze 없음

        # ====================================================================
        # 3. Breakout — 종가 > BB upper
        # ====================================================================
        if row['Close'] <= bb_upper.iloc[-1]:
            return None

        # ====================================================================
        # 4. Macro filter — 200일 SMA 위
        # ====================================================================
        ma200 = close.rolling(200).mean().iloc[-1]
        if pd.isna(ma200) or row['Close'] < ma200:
            return None

        # ====================================================================
        # 5. 거래량 확장 (1.5-5×, climax 컷)
        # ====================================================================
        vol_50 = df['Volume'].rolling(50).mean().iloc[-1]
        if pd.isna(vol_50) or vol_50 <= 0:
            return None
        vol_ratio = row['Volume'] / vol_50
        if vol_ratio < self.VOL_BREAKOUT_MULT or vol_ratio > self.VOL_CLIMAX_MULT:
            return None

        # ====================================================================
        # 6. 양봉 confirmation
        # ====================================================================
        if row['Close'] <= row['Open']:
            return None

        ep = entry_price or row['Close']

        # ATR target/stop (breakout preset 5×/2×, RR 2.5)
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        # Stop: BB middle (mean reversion 가능성) 또는 ATR×2
        bb_mid_stop_pct = (bb_mid.iloc[-1] * 0.99 / ep) - 1
        stop_loss_pct = max(bb_mid_stop_pct, atr_stop_pct, -0.07)
        target_pct = atr_target_pct

        confidence = 0.78

        bbw_pct = bb_width.iloc[-1] / squeeze_threshold * 100
        reason = (f"Bollinger Squeeze Breakout · BBW {bb_width.iloc[-1]*100:.1f}% "
                  f"(squeeze {recent_5_in_squeeze}/5일) · "
                  f"vol {vol_ratio:.1f}× · 200SMA 위")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=3, hold_max=20, confidence=confidence,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
