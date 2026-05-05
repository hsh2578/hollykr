"""전략 33: MA Convergence (이평선 수렴 = VCP 한국화) [등급 A] [HYBRID]
주봉 정배열 + 일봉 다중 이평선 수렴 → 폭발 직전 squeeze 패턴.
출처: stock-screener-kr ma_convergence.py 한국화 + Phase 5 인프라 통합."""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class MAConvergence(BaseStrategy):
    name = "ma_convergence"
    category = "trend_following"  # legendary preset 5x/2x, RR 2.5
    exec_timing = "HYBRID"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 250:  # 주봉 60주 + 일봉 120일 커버
            return None

        # 일봉 종가 시리즈
        close = df['Close']
        row = df.iloc[-1]

        # 일봉 거래량 10만주+ 유동성 컷
        if row['Volume'] < 100_000:
            return None

        # 주봉 변환 (마지막 거래일 기준)
        weekly = df['Close'].resample('W').last().dropna()
        if len(weekly) < 100:
            return None

        # 조건 A: 주봉 10>20>60 정배열
        ma10w = weekly.rolling(10).mean()
        ma20w = weekly.rolling(20).mean()
        ma60w = weekly.rolling(60).mean()
        if pd.isna(ma60w.iloc[-1]):
            return None
        if not (ma10w.iloc[-1] > ma20w.iloc[-1] > ma60w.iloc[-1]):
            return None

        # 조건 B: 100주봉 신고가가 30주 이내
        weekly_100_high = weekly.rolling(100).max()
        if pd.isna(weekly_100_high.iloc[-1]):
            return None
        # 최근 30주 내 100주봉 최고치 발생 여부
        recent_30w = weekly.iloc[-30:]
        if recent_30w.max() < weekly_100_high.iloc[-1] * 0.99:
            return None

        # 조건 C: 일봉 20/60/120 이격도 모두 5% 이내 (수렴)
        ma20d = close.rolling(20).mean().iloc[-1]
        ma60d = close.rolling(60).mean().iloc[-1]
        ma120d = close.rolling(120).mean().iloc[-1]
        if pd.isna(ma120d):
            return None

        gap_20_60 = abs(ma20d - ma60d) / ma60d * 100
        gap_20_120 = abs(ma20d - ma120d) / ma120d * 100
        gap_60_120 = abs(ma60d - ma120d) / ma120d * 100

        if gap_20_60 > 5 or gap_20_120 > 5 or gap_60_120 > 5:
            return None

        # 조건 D: 종가 vs 20일 이격도 5% 이내
        gap_price_20 = abs(row['Close'] - ma20d) / ma20d * 100
        if gap_price_20 > 5:
            return None

        ep = entry_price or row['Close']
        # Minervini VCP 정석: 손절 = "마지막 가장 좁은 수축의 저점 직하"
        # 우리 시스템 적용: 최근 20일 (마지막 수축 구간) 저점 -0.5% vs ATR×2 cap
        last_contraction_low = df['Low'].iloc[-20:].min()
        contraction_stop_pct = (last_contraction_low * 0.995 / ep) - 1
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        stop_loss_pct = max(contraction_stop_pct, atr_stop_pct, -0.08)
        target_pct = atr_target_pct

        reason = (f"VCP 한국화 · 주봉 10>20>60 정배열 · 100주봉 신고가 30주 내 · "
                  f"일봉 이격도 모두 ≤5% (squeeze) · "
                  f"손절: 마지막 수축 저점 {last_contraction_low:,.0f}원 직하")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=5, hold_max=30, confidence=0.75,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
