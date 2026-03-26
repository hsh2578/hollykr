"""전략 20: Strong Stock Pulling Back [등급 B] [HYBRID]
시장 대비 상대 강세 종목의 풀백 + 반등 시작."""

from typing import Optional, Dict
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class StrongStockPullingBack(BaseStrategy):
    name = "strong_stock_pulling_back"
    category = "pullback"
    exec_timing = "HYBRID"
    grade = "B"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 63:
            return None

        row = df.iloc[-1]

        # 3개월 수익률 계산 (상대 강세 근사)
        # 시장 벤치마크 없이 절대 수익률로 근사: 3m return > 0 (시장 평균 이상)
        ret_3m = row['Close'] / df['Close'].iloc[-63] - 1
        if ret_3m < 0.05:  # 최소 5% 이상 수익 (시장 대비 강세 근사)
            return None

        # 60일 고가 대비 20~25% 풀백
        high_60d = df['High'].rolling(60).max().iloc[-1]
        pullback = (high_60d - row['Close']) / high_60d
        if pullback < 0.20 or pullback > 0.25:
            return None

        # 당일 양봉 (반등 시작)
        if row['Close'] <= row['Open']:
            return None

        # 거래량 > 5일 평균
        vol_5d = df['Volume'].rolling(5).mean().iloc[-1]
        if row['Volume'] < vol_5d:
            return None

        ep = entry_price or row['Close']
        stop = ep * 0.95

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.05, stop_loss_pct=(stop / ep - 1),
            hold_min=2, hold_max=5, confidence=0.55,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
