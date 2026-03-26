"""전략 3: Yesterday Hammer [등급 A] [EOD]
전일 해머 캔들 → 당일 강세 확인 → 매수."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import is_hammer, close_position_ratio


class YesterdayHammer(BaseStrategy):
    name = "yesterday_hammer"
    category = "support_bounce"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 3:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        # 전일 해머: 하단꼬리 >= 몸통x2, 상단꼬리 <= 몸통x0.3
        if not is_hammer(prev):
            return None

        # 전일 종가가 레인지 상위 30% (position >= 0.7)
        prev_range = prev['High'] - prev['Low']
        if prev_range > 0:
            prev_pos = (prev['Close'] - prev['Low']) / prev_range
            if prev_pos < 0.7:
                return None

        # 당일 강세: 시가 > 전일 종가 AND 종가 > 전일 고가
        if not (row['Open'] > prev['Close'] and row['Close'] > prev['High']):
            return None

        # 거래량 확인: 당일 >= 전일
        if row['Volume'] < prev['Volume']:
            return None

        ep = entry_price or row['Close']
        stop = max(prev['Low'], ep * 0.97)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.04, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
