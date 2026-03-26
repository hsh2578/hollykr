"""전략 29: Pulling The Arrow Back [등급 B+] [HYBRID]
전일 장 전반 하락 → 후반 강반등 마감 → 다음날 양봉 확인 시 화살이 날아간다."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class PullingTheArrow(BaseStrategy):
    name = "pulling_the_arrow"
    category = "reversal"
    exec_timing = "HYBRID"
    grade = "B+"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 5:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        # 전일: 시가 > 종가 방향이었지만 (약세 시작)
        # 실제로는 종가가 당일 중간값보다 위 (강한 마감)
        prev_midpoint = (prev['High'] + prev['Low']) / 2
        if prev['Open'] <= prev['Close']:
            # 전일이 양봉이면 "하락 후 반등" 패턴 아님
            # 시가 > 종가여야 약세 시작 느낌이지만,
            # 문제 조건: open > close (bearish start) BUT close > midpoint
            return None
        if prev['Close'] <= prev_midpoint:
            return None

        # 당일 양봉: 종가 > 시가
        if row['Close'] <= row['Open']:
            return None

        # 당일 종가 > 전일 고가
        if row['Close'] <= prev['High']:
            return None

        # 당일 거래량 > 전일 거래량 (거래량 확인)
        if row['Volume'] <= prev['Volume']:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.97

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.04, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.60,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
