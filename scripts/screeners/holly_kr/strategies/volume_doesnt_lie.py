"""전략 6: Volume Doesn't Lie [등급 A] [EOD]
4%+ 갭업 + 거래량 2배 폭발 = 방향 지속."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import close_position_ratio


class VolumeDoesntLie(BaseStrategy):
    name = "volume_doesnt_lie"
    category = "gap_momentum"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 220:
            return None

        # 200일선 위 (Stage 4 차단)
        ma200 = df['Close'].rolling(200).mean().iloc[-1]
        if pd.isna(ma200) or df['Close'].iloc[-1] <= ma200:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        # 갭업 5%+ (4%에서 강화 — 질 우선)
        gap = (row['Open'] - prev['Close']) / prev['Close']
        if gap < 0.05:
            return None

        # 거래량: 50일 평균 2.5~6.0× (climax 컷, 질 강화)
        if not self._check_volume_with_climax(df, min_mult=2.5, max_mult=6.0, period=50):
            return None
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1]

        # 종가 >= 시가 (갭 유지)
        if row['Close'] < row['Open']:
            return None

        # 종가 레인지 상위 60% (position >= 0.6, 0.5에서 강화)
        if close_position_ratio(row) < 0.6:
            return None

        ep = entry_price or row['Close']
        # 카테고리 preset (gap_momentum: 4.0, 1.6 → RR 2.5)
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        # 손절: 갭 시가 vs ATR stop, 더 가까운 쪽
        gap_stop_pct = (row['Open'] / ep) - 1
        stop_loss_pct = max(gap_stop_pct, atr_stop_pct, -0.05)
        target_pct = atr_target_pct

        vol_ratio = row['Volume'] / vol_avg if vol_avg > 0 else 0
        reason = f"갭업 +{gap*100:.1f}% · 거래량 {vol_ratio:.1f}배 · 갭 유지(종가≥시가)"

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=1, hold_max=5, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
