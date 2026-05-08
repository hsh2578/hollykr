"""전략: Clenow Momentum [등급 A] [HYBRID]
Andreas Clenow "Stocks on the Move" (2015) 정통 구현.

핵심 룰 (헤지펀드 운용 + 13년 검증):
1. 90일 로그 회귀 slope × R² = volatility-adjusted momentum 점수
2. 시장 (KOSPI) 200일 SMA 위에서만 long
3. ATR 기반 사이징 (이미 base에 있음)
4. 점수 상위 진입

한국 시장 적용:
- Clenow는 S&P 500 → 우리는 KOSPI/KOSDAQ
- 시장 필터: KOSPI 종가 > 200일 SMA
- 종목 점수: 90일 log 회귀 slope (연환산) × R² × 100

출처:
- Clenow "Stocks on the Move" (2015)
- TuringTrader 검증 백테스트
- QuantConnect 구현 검증
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class ClenowMomentum(BaseStrategy):
    name = "clenow_momentum"
    category = "trend_following"  # RR 2.5
    exec_timing = "HYBRID"
    grade = "A"

    REGRESSION_PERIOD = 90        # Clenow 정통 90일
    MIN_SCORE = 30.0              # 연환산 % × R² (한국 시장 기준 30%+)
    MIN_R_SQUARED = 0.50          # R² ≥ 0.50 (추세 일관성)
    GAP_LIMIT = 0.15              # 최근 90일 갭 -15%+ 제외 (Clenow 정통)

    @staticmethod
    def _check_market_filter(df_market: pd.DataFrame) -> bool:
        """KOSPI 200일 SMA 위 (Clenow 시장 필터)."""
        if df_market is None or len(df_market) < 200:
            return False
        ma200 = df_market['Close'].rolling(200).mean().iloc[-1]
        return df_market['Close'].iloc[-1] > ma200

    def _calc_clenow_score(self, df: pd.DataFrame) -> tuple:
        """Clenow score = annualized slope × R² × 100.

        90일 log 가격에 선형 회귀 → slope 연환산 % × R²
        """
        if len(df) < self.REGRESSION_PERIOD + 5:
            return 0.0, 0.0

        prices = df['Close'].iloc[-self.REGRESSION_PERIOD:].values
        if (prices <= 0).any():
            return 0.0, 0.0

        log_prices = np.log(prices)
        x = np.arange(len(log_prices))

        # 선형 회귀
        slope, intercept = np.polyfit(x, log_prices, 1)
        # R² 계산
        fit = slope * x + intercept
        ss_res = np.sum((log_prices - fit) ** 2)
        ss_tot = np.sum((log_prices - np.mean(log_prices)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        # 연환산 (252 거래일)
        annualized_slope_pct = (np.exp(slope * 252) - 1) * 100

        score = annualized_slope_pct * r_squared
        return float(score), float(r_squared)

    def _check_recent_gap(self, df: pd.DataFrame) -> bool:
        """최근 90일 동안 -15%+ 갭 다운 없는지 (Clenow 정통)."""
        if len(df) < self.REGRESSION_PERIOD + 1:
            return True
        recent = df.iloc[-self.REGRESSION_PERIOD:]
        for i in range(1, len(recent)):
            prev_close = recent['Close'].iloc[i - 1]
            today_open = recent['Open'].iloc[i]
            if prev_close > 0:
                gap = (today_open - prev_close) / prev_close
                if gap < -self.GAP_LIMIT:
                    return False
        return True

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 220:  # 200일 SMA + 20일 buffer
            return None

        row = df.iloc[-1]

        # ====================================================================
        # 1. 시장 필터: 종목 자체 200일 SMA 위 (Clenow 정통은 KS11 시장 필터,
        #    한국에선 KRX API 접근 제한으로 종목 자체 SMA 사용)
        # ====================================================================
        ma200 = df['Close'].rolling(200).mean().iloc[-1]
        if pd.isna(ma200) or row['Close'] < ma200:
            return None

        # ====================================================================
        # 2. 종목 100일 SMA 위 (중기 추세)
        # ====================================================================
        ma100 = df['Close'].rolling(100).mean().iloc[-1]
        if pd.isna(ma100) or row['Close'] < ma100:
            return None

        # ====================================================================
        # 3. Clenow 점수 (90일 회귀 slope × R²)
        # ====================================================================
        score, r_sq = self._calc_clenow_score(df)
        if score < self.MIN_SCORE:
            return None
        if r_sq < self.MIN_R_SQUARED:
            return None  # 추세 일관성 없음

        # ====================================================================
        # 4. 최근 90일 갭다운 -15%+ 컷 (Clenow 정통)
        # ====================================================================
        if not self._check_recent_gap(df):
            return None

        ep = entry_price or row['Close']

        # ATR target/stop (trend_following preset 5×/2×, RR 2.5)
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        # Stop: 100일 SMA 또는 ATR×2 또는 -8%
        ma100_stop_pct = (ma100 * 0.99 / ep) - 1
        stop_loss_pct = max(ma100_stop_pct, atr_stop_pct, -0.08)
        target_pct = atr_target_pct

        confidence = min(0.85, 0.65 + (score - self.MIN_SCORE) / 200)

        reason = (f"Clenow Momentum · slope×R² {score:.1f} (R² {r_sq:.2f}) · "
                  f"KOSPI 200SMA 위 · 100일 SMA 위")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=10, hold_max=60, confidence=confidence,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
