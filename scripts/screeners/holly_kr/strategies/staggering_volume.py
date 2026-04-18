"""전략 16: Staggering Volume [등급 B] [HYBRID]
거래량 3배 폭발 + 신고가 — 뭔가 큰 일이 벌어지고 있다. 테마주 필터 필수."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import close_position_ratio


class StaggeringVolume(BaseStrategy):
    name = "staggering_volume"
    category = "gap_momentum"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]

        # 거래량 > 20일 평균 × 3.0 (극단적 거래량 폭발)
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1]
        if row['Volume'] < vol_avg * 3.0:
            return None

        # 종가 > 20일 최고가 (신고가)
        high_20d = df['High'].rolling(20).max().iloc[-2]  # 전일까지의 20일 고가
        if row['Close'] <= high_20d:
            return None

        # 종가 레인지 상위 30% (close position >= 0.7)
        if close_position_ratio(row) < 0.7:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.95

        # 테마주 경고 추가
        warnings = ['테마주/작전주 필터 확인 필요 — 극단적 거래량 전략']

        vol_ratio = row['Volume'] / vol_avg if vol_avg > 0 else 0
        reason = f"거래량 {vol_ratio:.1f}배 폭발 · 20일 신고가 돌파"

        sig = self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.07, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=2, confidence=0.55,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )
        sig.risk_warnings = warnings
        return sig

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
