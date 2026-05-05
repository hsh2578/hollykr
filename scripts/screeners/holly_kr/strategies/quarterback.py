"""전략 21: Quarterback [등급 A-] [HYBRID]
큰 상승 후 20%+ 풀백 + RSI 이중 필터 — 정교한 풀백 매수."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import calc_rsi


class Quarterback(BaseStrategy):
    name = "quarterback"
    category = "pullback"
    exec_timing = "HYBRID"
    grade = "A-"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]

        # 20일 최고가 대비 현재가 풀백 > 20%
        high_20d = df['High'].rolling(20).max().iloc[-1]
        pullback = (high_20d - row['Close']) / high_20d
        if pullback < 0.20:
            return None

        # RSI(14) 30~50 (과매도 탈출 중이지만 과매수 아님)
        rsi14 = calc_rsi(df['Close'], 14)
        rsi14_val = rsi14.iloc[-1]
        if pd.isna(rsi14_val) or rsi14_val < 30 or rsi14_val > 50:
            return None

        # RSI(5) > RSI(14) (단기 모멘텀이 장기 추월 = 가속 전환)
        rsi5 = calc_rsi(df['Close'], 5)
        rsi5_val = rsi5.iloc[-1]
        if pd.isna(rsi5_val) or rsi5_val <= rsi14_val:
            return None

        # 당일 양봉
        if row['Close'] <= row['Open']:
            return None

        ep = entry_price or row['Close']
        target_pct, stop_loss_pct = self._atr_target_stop(df, ep)  # pullback → 3x/1.5x (RR 2.0)

        reason = (f"20일 고점 대비 -{pullback*100:.1f}% 풀백 · "
                  f"RSI14 {rsi14_val:.0f} · RSI5({rsi5_val:.0f})>RSI14 모멘텀 전환 · 양봉")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=3, hold_max=7, confidence=0.65,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
