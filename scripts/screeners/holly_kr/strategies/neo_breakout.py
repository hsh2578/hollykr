"""전략 31: NEO Breakout Long [등급 B-] [HYBRID]
뉴스 촉매 + 거래량 3배 폭발 → 추세 방향 초기 진입. 테마주 필터 필수."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class NeoBreakout(BaseStrategy):
    name = "neo_breakout"
    category = "momentum"
    exec_timing = "HYBRID"
    grade = "B-"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]
        close = df['Close']

        # 거래량 > 20일 평균 × 4.0 (거래량 폭발)
        avg_vol = df['Volume'].rolling(20).mean().iloc[-1]
        if avg_vol <= 0 or row['Volume'] <= avg_vol * 4.0:
            return None

        # 종가 > 전일 고가
        if row['Close'] <= prev['High']:
            return None

        # 종가 > MA20
        ma20 = close.rolling(20).mean().iloc[-1]
        if row['Close'] <= ma20:
            return None

        # 일일 수익률 > 4%
        daily_ret = row['Close'] / prev['Close'] - 1
        if daily_ret <= 0.04:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.95

        # 테마주 경고
        warnings = []
        if daily_ret > 0.10:
            warnings.append("급등 종목 — 테마주/작전주 여부 확인 필요")

        sig = self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.07, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=3, confidence=0.52,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )
        sig.risk_warnings = warnings
        return sig

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
