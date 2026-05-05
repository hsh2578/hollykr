"""전략 34: 52주 신고가 근접 (돌파 직전 진입) [등급 A] [HYBRID]
52주 고가 5% 이내 미돌파 + 저항선 형성 후 20일+ 경과.
이유: 돌파 후 진입(neo_breakout)보다 RR 우월. 손절폭은 작고 목표 폭은 큼.
출처: stock-screener-kr new_high_52w_approach 한국화."""

from typing import Optional, Dict
import pandas as pd

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class NewHigh52wApproach(BaseStrategy):
    name = "new_high_52w_approach"
    category = "breakout"  # RR 2.5 (5x/2x ATR preset)
    exec_timing = "HYBRID"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        # 52주 = 250 거래일 + 저항 형성 20일 + Stage 2 200일 = 충분히
        if len(df) < 270:
            return None

        row = df.iloc[-1]

        # Stage 2 거시 필터 (Phase 2)
        if not self._check_stage_2(df):
            return None

        close = df['Close']
        high = df['High']

        # 52주 (250일) 고가 — 단, 최근 20일은 제외 (저항선 확립 기간)
        lookback = 250
        confirm_window = 20
        if len(df) < lookback + confirm_window:
            return None

        # 저항선 (20일 이전 250일 동안의 고가)
        resistance = high.iloc[-(lookback + confirm_window):-confirm_window].max()
        if pd.isna(resistance) or resistance <= 0:
            return None

        # 조건 1: 종가가 52주 고가의 5% 이내 (미돌파 근접)
        proximity = (row['Close'] - resistance) / resistance
        if proximity > 0 or proximity < -0.05:
            return None  # 이미 돌파했거나 너무 멈

        # 조건 2: 최근 20일 내 신고가 미발생 (저항선 확립 확인)
        recent_high = high.iloc[-confirm_window:].max()
        if recent_high >= resistance:
            return None  # 이미 갱신함

        # 조건 3: 거래량 정상 (50일 평균의 1.0~5.0배 — 폭발 직전이라 climax 컷)
        if not self._check_volume_with_climax(df, min_mult=1.0, max_mult=5.0, period=50):
            return None

        # 조건 4: 당일 상승률 5%~25% (강한 모멘텀 + 상한가 미달)
        # — 52주 고가 근접 + 강한 상승 = 진짜 돌파 임박 시그널
        if len(df) < 2:
            return None
        daily_ret = (row['Close'] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]
        if daily_ret < 0.05 or daily_ret > 0.25:
            return None

        # 진입가 = 종가
        ep = entry_price or row['Close']

        # 정석 (asktraders/Earn2Trade): "직전 higher low 직하 OR 저항선 하단"
        # 우리 적용: 직전 20일 swing low vs 저항선의 -3% vs ATR×2 cap, 가장 가까운 쪽
        swing_low = df['Low'].iloc[-confirm_window:].min()
        swing_low_pct = (swing_low * 0.995 / ep) - 1  # swing low -0.5%
        resistance_lower_pct = (resistance * 0.97 / ep) - 1  # 저항선 -3%
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        stop_loss_pct = max(swing_low_pct, resistance_lower_pct, atr_stop_pct, -0.07)

        # target: ATR×5 (저항선 돌파 후 모멘텀 노림)
        target_pct = atr_target_pct

        proximity_pct = abs(proximity) * 100
        reason = (f"52주 고가 {resistance:,.0f}원 {proximity_pct:.1f}% 이내 미돌파 · "
                  f"당일 +{daily_ret*100:.1f}% 강한 상승 · "
                  f"저항선 확립 ({confirm_window}일 신고가 미갱신) · 돌파 임박")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=5, hold_max=15, confidence=0.70,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
