"""전략 5: Horseshoe Up [등급 A] [EOD]
갭업 → 갭 메꿈 시도 실패 → 시가 위 복귀 = U자 반등."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import close_position_ratio


class HorseshoeUp(BaseStrategy):
    name = "horseshoe_up"
    category = "support_bounce"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 3:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        # 갭업 1.5%+
        gap = (row['Open'] - prev['Close']) / prev['Close']
        if gap < 0.015:
            return None

        # 장중 시가 아래 1%+ 하락 (갭 메꿈 시도)
        if row['Low'] >= row['Open'] * 0.99:
            return None

        # 종가 > 시가 (복귀)
        if row['Close'] <= row['Open']:
            return None

        # 종가 레인지 상위 40% (position >= 0.6)
        if close_position_ratio(row) < 0.6:
            return None

        ep = entry_price or row['Close']
        stop = max(row['Low'], ep * 0.98)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.03, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.60,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
