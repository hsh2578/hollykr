"""전략: 52주 신고가 당일 돌파 [등급 A] [HYBRID]

사용자 설계 (주식웹사이트 new_high_52w.py 참고 + 보강):
- 52주 신고가 (250일 최고 종가) 당일 첫 돌파
- 거래량 동반 (20일 평균 × 1.5+)
- 당일 상승률 +5% ~ +20% (강한 돌파만, chase 회피)
- 시가총액 / ML 필터 X (사용자 명시 제거)

매도 (둘 중 발동):
1. 종가 < 5일 SMA → 매도 (빠른 추세 컷)
2. 종가 < 진입 시 52주 신고가 (저항선) → 매도 (돌파 무효)
3. 60일 시간 청산

stop = max(5일선, 52주 신고가 저항선) — 보수적
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class NewHigh52wBreakout(BaseStrategy):
    name = "new_high_52w_breakout"
    category = "breakout"  # RR 2.5 (5x/2x ATR preset)
    exec_timing = "HYBRID"
    grade = "A"

    HIGH_PERIOD = 250            # 52주 = 250 거래일
    VOLUME_RATIO_MIN = 1.5       # 거래량 ≥ 20일 평균 × 1.5
    VOLUME_LOOKBACK = 20
    MIN_DAILY_RETURN = 0.05      # 당일 +5% 이상
    MAX_DAILY_RETURN = 0.20      # 당일 +20% 이하 (chase 회피)
    SMA_FAST = 5                 # 5일 SMA (매도 stop)

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:

        # 최소 데이터: 250일 + 어제 비교 = 251일
        if len(df) < self.HIGH_PERIOD + 1:
            return None

        # 당일 / 어제
        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        today_close = float(today['Close'])
        yesterday_close = float(yesterday['Close'])
        today_volume = float(today['Volume'])
        today_open = float(today['Open']) if 'Open' in df.columns else today_close

        if today_close <= 0 or yesterday_close <= 0:
            return None

        # ====================================================================
        # 1. 52주 신고가 계산 (당일 제외 250일 최고 종가)
        # ====================================================================
        prior_window = df['Close'].iloc[-(self.HIGH_PERIOD + 1):-1]  # 어제까지 250일
        if len(prior_window) < self.HIGH_PERIOD:
            return None
        high_52w = float(prior_window.max())

        if high_52w <= 0:
            return None

        # ====================================================================
        # 2. 당일 첫 돌파 확인
        #    당일 종가 > 52주 신고가 AND 어제 종가 ≤ 52주 신고가
        # ====================================================================
        if not (today_close > high_52w and yesterday_close <= high_52w):
            return None

        # ====================================================================
        # 3. 당일 상승률 +5% ~ +20% (강한 돌파만)
        # ====================================================================
        daily_return = (today_close - yesterday_close) / yesterday_close
        if not (self.MIN_DAILY_RETURN <= daily_return <= self.MAX_DAILY_RETURN):
            return None

        # ====================================================================
        # 4. 거래량 동반 (20일 평균 × 1.5+)
        # ====================================================================
        vol_window = df['Volume'].iloc[-(self.VOLUME_LOOKBACK + 1):-1]  # 어제까지 20일
        if len(vol_window) < self.VOLUME_LOOKBACK:
            return None
        avg_vol_20 = float(vol_window.mean())
        if avg_vol_20 <= 0:
            return None
        volume_ratio = today_volume / avg_vol_20
        if volume_ratio < self.VOLUME_RATIO_MIN:
            return None

        # ====================================================================
        # 5. 진입가 + 매도 룰 계산
        # ====================================================================
        ep = entry_price or today_close

        # Stop = max(5일선, 52주 신고가 저항선)
        sma5 = float(df['Close'].iloc[-self.SMA_FAST:].mean())
        # 진입 후 stop (둘 중 높은 가격이 발동 — 보수적)
        stop_price = max(sma5, high_52w)
        stop_loss_pct = (stop_price - ep) / ep

        # 손절폭 너무 작으면 (RR 게이트 통과 못함) 또는 음수 (이미 stop 위)이면 폐기
        if stop_loss_pct >= -0.005:
            # stop이 진입가 위 또는 손절폭 0.5% 미만 = 비현실적
            return None
        if stop_loss_pct < -0.10:
            # 손절폭 10% 초과 = 비현실적
            return None

        # 목표 = ATR 기반 (breakout preset 5×ATR)
        atr_target_pct, _ = self._atr_target_stop(df, ep)
        target_pct = atr_target_pct  # 5×ATR (보통 +10~15%)

        # 신뢰도: 거래량 비율 + 상승률 강도
        # volume_ratio 1.5 → 0.65, 3.0 → 0.85
        # daily_return 0.10 → +0.05, 0.20 → +0.10
        confidence = min(0.90,
                         0.55
                         + min((volume_ratio - 1.5) / 5.0, 0.20)
                         + min((daily_return - 0.05) / 0.30, 0.10))

        reason = (f"52주 신고가 {high_52w:,.0f}원 당일 돌파 (어제 종가 ≤) · "
                  f"+{daily_return*100:.1f}% 상승 · "
                  f"거래량 {volume_ratio:.1f}× 20일평균 · "
                  f"매도: 5SMA({sma5:,.0f}) or 52w고가({high_52w:,.0f}) 하향")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=5, hold_max=60, confidence=confidence,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series,
                   df_history: pd.DataFrame = None) -> Optional[str]:
        """매도 체크 (실전 운영용 — backtest는 별도 룰 사용 가능).

        Args:
            position: dict with 'entry_high_52w', 'entry_price' 등
            current_row: 오늘 OHLCV
            df_history: 5일 SMA 계산용 (마지막 5일)

        Returns:
            매도 사유 ('sma5_break', 'breakout_invalid', 'time_exit') 또는 None
        """
        if df_history is None or len(df_history) < self.SMA_FAST:
            return None

        today_close = float(current_row['Close'])
        sma5 = float(df_history['Close'].iloc[-self.SMA_FAST:].mean())

        # 1. 5일선 하향
        if today_close < sma5:
            return 'sma5_break'

        # 2. 52주 신고가 (진입 시) 하향
        entry_high_52w = position.get('entry_high_52w', 0)
        if entry_high_52w > 0 and today_close < entry_high_52w:
            return 'breakout_invalid'

        return None
