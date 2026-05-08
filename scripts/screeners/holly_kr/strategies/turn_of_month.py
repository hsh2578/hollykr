"""전략: Turn of Month Effect [등급 A] [HYBRID]
Calendar Anomaly — 월말/월초 매수 효과 (학술 검증).

핵심 룰:
1. 월말 5거래일 ~ 월초 3거래일 진입 (Lakonishok-Smidt 1988)
2. Stage 2 macro filter (강세 종목만)
3. 양봉 + 거래량 확인

학술 검증:
- Lakonishok & Smidt "Are Seasonal Anomalies Real?" (1988, RFS)
- Ariel "A Monthly Effect in Stock Returns" (1987, JFE)
- Quantpedia: Turn-of-month effect 100년+ 검증

원리:
- 월말: 펀드 매니저 window dressing + 401k 자금 유입 (미국)
- 한국: 펀드 리밸런싱 + 외국인 매수 패턴
- 통계: 월말 5일 / 월초 3일이 나머지 17-18일보다 평균 ~0.3% 초과 수익
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class TurnOfMonth(BaseStrategy):
    name = "turn_of_month"
    category = "trend_following"  # RR 2.5 (월간 효과지만 추세 동반)
    exec_timing = "HYBRID"
    grade = "A"

    @staticmethod
    def _is_turn_of_month(date) -> bool:
        """월말 5거래일 또는 월초 3거래일."""
        if not hasattr(date, 'day'):
            return False
        day = date.day
        # 월초 3일
        if day <= 3:
            return True
        # 월말 5일 (대략 24일 이후 — 정확히는 마지막 5거래일)
        # 단순 — 25일 이후
        if day >= 25:
            return True
        return False

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 220:
            return None

        row = df.iloc[-1]
        last_date = df.index[-1]

        # ====================================================================
        # 1. Calendar 필터 — 월말 5일 또는 월초 3일
        # ====================================================================
        if not self._is_turn_of_month(last_date):
            return None

        # ====================================================================
        # 2. Stage 2 macro (안전 — 강세 종목에만)
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
        if pd.isna(vol_50) or row['Volume'] < vol_50 * 1.2:
            return None

        # ====================================================================
        # 4. 갭다운 컷 (최근 5일 -3%+ 갭다운)
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

        # ATR target/stop (trend_following preset 5×/2×, RR 2.5)
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        ma50_stop_pct = (ma50 * 0.99 / ep) - 1
        stop_loss_pct = max(ma50_stop_pct, atr_stop_pct, -0.06)
        target_pct = atr_target_pct

        confidence = 0.72

        day_of_month = last_date.day if hasattr(last_date, 'day') else 0
        position_label = "월초" if day_of_month <= 3 else "월말"
        reason = (f"Turn-of-Month effect ({position_label} {day_of_month}일) · "
                  f"Stage 2 강세 종목 · 양봉 + 거래량")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=3, hold_max=10, confidence=confidence,
            signal_date=str(last_date.date()) if hasattr(last_date, 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
