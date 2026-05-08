"""전략: AQR Time-Series Momentum [등급 A] [HYBRID]
Moskowitz, Ooi, Pedersen (2012) 학술 검증 + AQR Capital 실무 운용.

핵심 룰:
- 12개월 수익률 sign (excluding most recent month — 정통)
- 양수면 long, 음수면 cash (long-only 한국 적응)
- 변동성 inverse 사이징 (이미 base.py에 있음)

학술 검증:
- 58 asset class 25년 백테스트 (Moskowitz 2012)
- Sharpe 1.0+ persistent
- TSMOM = "Time Series Momentum" (Quantpedia)

한국 일별 적응:
- 12개월 + 6개월 + 3개월 모두 양수 (multi-horizon confirmation)
- 일별 적용 (월별 리밸런싱 X, 일별 진입)
- Stage 2 안전망 (200일 SMA 위)
- 50일 SMA 위 + 양봉 + 거래량 (entry timing)

출처:
- Moskowitz, Ooi, Pedersen "Time Series Momentum" (2012, JFE)
- AQR Capital TSMOM datasets
- Quantpedia Time Series Momentum Effect
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class AQRTSMomentum(BaseStrategy):
    name = "aqr_tsmom"
    category = "trend_following"  # RR 2.5
    exec_timing = "HYBRID"
    grade = "A"

    LOOKBACK_12M = 252       # 12개월 거래일
    LOOKBACK_6M = 126        # 6개월
    LOOKBACK_3M = 63         # 3개월
    SKIP_RECENT = 22         # 최근 1개월 제외 (Moskowitz 정통)
    MAX_VOLATILITY = 0.45    # 연환산 변동성 45% 초과 컷 (한국 변동성 반영)

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        # 12개월 + skip 1개월 = 274일 + 충분한 buffer
        if len(df) < self.LOOKBACK_12M + self.SKIP_RECENT + 50:
            return None

        row = df.iloc[-1]
        close = df['Close']

        # ====================================================================
        # 1. 12개월 수익률 sign (Moskowitz 정통, skip 1개월)
        # ====================================================================
        p_now = close.iloc[-(self.SKIP_RECENT + 1)]
        p_12m_ago = close.iloc[-(self.LOOKBACK_12M + self.SKIP_RECENT + 1)]
        if p_12m_ago <= 0:
            return None
        ret_12m = (p_now / p_12m_ago) - 1
        if ret_12m <= 0:
            return None

        # ====================================================================
        # 2. 6개월 confirmation (multi-horizon)
        # ====================================================================
        p_6m_ago = close.iloc[-(self.LOOKBACK_6M + self.SKIP_RECENT + 1)]
        if p_6m_ago <= 0:
            return None
        ret_6m = (p_now / p_6m_ago) - 1
        if ret_6m <= 0:
            return None

        # ====================================================================
        # 3. 3개월 confirmation
        # ====================================================================
        p_3m_ago = close.iloc[-(self.LOOKBACK_3M + self.SKIP_RECENT + 1)]
        if p_3m_ago <= 0:
            return None
        ret_3m = (p_now / p_3m_ago) - 1
        if ret_3m <= 0:
            return None

        # ====================================================================
        # 4. 변동성 컷 (AQR: 변동성 inverse 사이징, 너무 변동성 큰 자산 컷)
        # ====================================================================
        daily_returns = close.pct_change()
        vol_60 = daily_returns.iloc[-60:].std() * np.sqrt(252)
        if pd.isna(vol_60) or vol_60 > self.MAX_VOLATILITY:
            return None

        # ====================================================================
        # 5. Stage 2 안전망 (200일 + 50일 SMA)
        # ====================================================================
        ma200 = close.rolling(200).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        if pd.isna(ma200) or pd.isna(ma50):
            return None
        if row['Close'] < ma200:
            return None
        if ma50 < ma200:
            return None

        # ====================================================================
        # 6. Entry 타이밍: 양봉 + 거래량 평균 이상
        # ====================================================================
        if row['Close'] <= row['Open']:
            return None
        vol_50 = df['Volume'].rolling(50).mean().iloc[-1]
        if pd.isna(vol_50) or row['Volume'] < vol_50:
            return None

        ep = entry_price or row['Close']

        # ATR target/stop (trend_following preset 5×/2×, RR 2.5)
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        ma50_stop_pct = (ma50 * 0.99 / ep) - 1
        stop_loss_pct = max(ma50_stop_pct, atr_stop_pct, -0.08)
        target_pct = atr_target_pct

        confidence = 0.78

        reason = (f"AQR TSMOM · 12M {ret_12m*100:.0f}% · 6M {ret_6m*100:.0f}% · "
                  f"3M {ret_3m*100:.0f}% · vol {vol_60*100:.0f}% · Stage 2")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=10, hold_max=60, confidence=confidence,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
