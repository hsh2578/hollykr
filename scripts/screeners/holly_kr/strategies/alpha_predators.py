"""전략 18: Alpha Predators [등급 B+] [HYBRID]
조용한 매집 — 거래량 증가 + 레인지 축소 + 외국인/기관 순매수."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class AlphaPredators(BaseStrategy):
    name = "alpha_predators"
    category = "accumulation"
    exec_timing = "HYBRID"
    grade = "B+"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]

        # 5일 평균 거래량 > 20일 평균 거래량 × 1.3 (거래량 증가)
        vol_5d = df['Volume'].rolling(5).mean().iloc[-1]
        vol_20d = df['Volume'].rolling(20).mean().iloc[-1]
        if vol_20d == 0 or vol_5d < vol_20d * 1.3:
            return None

        # 5일 레인지 < 10일 레인지 × 0.6 (레인지 축소 = 조용한 매집)
        range_5d = df['High'].tail(5).max() - df['Low'].tail(5).min()
        range_10d = df['High'].tail(10).max() - df['Low'].tail(10).min()
        if range_10d == 0 or range_5d >= range_10d * 0.6:
            return None

        # 양봉 (최소한의 상승 확인)
        if row['Close'] <= row['Open']:
            return None

        # MA20 상승 중 (하락 추세 매집 회피)
        ma20 = df['Close'].rolling(20).mean()
        if ma20.iloc[-1] <= ma20.iloc[-6]:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.97

        sig = self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.05, stop_loss_pct=(stop / ep - 1),
            hold_min=2, hold_max=5, confidence=0.60,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )
        if sig is None:
            return None
        # 외국인/기관 3일 순매수는 scanner에서 수급 등급으로 반영
        sig.risk_warnings = ['외국인/기관 3일 순매수 확인 권장']
        return sig

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
