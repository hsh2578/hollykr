"""전략 32: NEO Pullback Long [등급 B] [HYBRID]
NEO 급등 후 2~3일 횡보(숨 고르기) → 횡보 상단 돌파 시 2차 상승."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class NeoPullback(BaseStrategy):
    name = "neo_pullback"
    category = "momentum"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 30:
            return None

        row = df.iloc[-1]
        close = df['Close']

        # 최근 5일 내 5%+ 단일일 상승이 있었는지
        surge_found = False
        surge_idx = -1
        for i in range(-5, 0):
            if abs(i) >= len(df) or abs(i - 1) >= len(df):
                continue
            day_ret = df['Close'].iloc[i] / df['Close'].iloc[i - 1] - 1
            if day_ret >= 0.05:
                surge_found = True
                surge_idx = i
                break

        if not surge_found:
            return None

        # 급등 이후 2~3일 타이트 레인지 (< 20일 평균 레인지 × 0.5)
        daily_range = df['High'] - df['Low']
        avg_range = daily_range.rolling(20).mean().iloc[surge_idx - 1]  # 급등 전 기준

        # 급등일과 오늘 사이의 일수
        days_after = abs(surge_idx) - 1  # surge_idx는 음수
        if days_after < 2:
            return None

        # 급등 후 ~ 전일까지 타이트 레인지 확인
        for i in range(surge_idx + 1, 0):
            day_range = df.iloc[i]['High'] - df.iloc[i]['Low']
            if day_range >= avg_range * 0.5:
                return None

        # 당일 종가 > 횡보 구간 고가 (급등일+1 ~ 전일)
        consolidation_high = df['High'].iloc[surge_idx + 1:].iloc[:-1].max()
        if row['Close'] <= consolidation_high:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.96

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.05, stop_loss_pct=(stop / ep - 1),
            hold_min=2, hold_max=5, confidence=0.58,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
