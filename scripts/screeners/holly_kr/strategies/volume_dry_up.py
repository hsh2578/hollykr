"""전략 36: Volume Dry-Up (급등 후 매물 소화) [등급 A] [HYBRID]
거래량 ×4+ 양봉 후 3-8일간 거래량 ×40% 이하 dry-up. 세력 매물 소화 → 재상승 직전.
한국 작전주 매집 패턴 — 한국 시장 특화.
출처: stock-screener-kr volume_dry_up 한국화."""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class VolumeDryUp(BaseStrategy):
    name = "volume_dry_up"
    category = "accumulation"  # RR 2.5 (5x/2x ATR preset)
    exec_timing = "HYBRID"
    grade = "A"

    # 1단계 폭발봉 조건
    EXPLOSION_VOL_MULT = 4.0    # 거래량 20일 평균 × 4배
    EXPLOSION_PRICE_MIN = 0.08  # 종가 +8% 이상
    UPPER_WICK_MAX = 0.30       # 윗꼬리 30% 미만
    GAP_DOWN_MIN = -0.03        # 갭다운 -3% 이상 제외

    # 2단계 dry-up 조건
    MIN_DAYS_AFTER = 3
    MAX_DAYS_AFTER = 8
    PRICE_HOLD_MIN = 0.98       # 폭발봉 시가 × 0.98 이상
    PRICE_DROP_MAX = 0.90       # 폭발봉 고가 × 0.90 이상
    VOL_DRY_THRESHOLD = 0.40    # 폭발봉 거래량 × 40% 이하

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 30:
            return None

        row = df.iloc[-1]
        close = df['Close']
        volume = df['Volume']

        # 폭발봉 후보 탐색 (3-8일 전)
        for offset in range(self.MIN_DAYS_AFTER, self.MAX_DAYS_AFTER + 1):
            exp_idx = -offset - 1
            if abs(exp_idx) > len(df):
                continue

            exp_row = df.iloc[exp_idx]
            prev_row = df.iloc[exp_idx - 1] if abs(exp_idx) + 1 <= len(df) else None
            if prev_row is None:
                continue

            # 1단계: 폭발봉 조건 5가지
            # 양봉 +8%+
            change = (exp_row['Close'] - prev_row['Close']) / prev_row['Close']
            if change < self.EXPLOSION_PRICE_MIN:
                continue

            # 거래량 20일 평균 ×4
            vol_avg_20 = volume.iloc[exp_idx - 20:exp_idx].mean()
            if vol_avg_20 <= 0 or exp_row['Volume'] < vol_avg_20 * self.EXPLOSION_VOL_MULT:
                continue

            # 윗꼬리 30% 미만
            range_total = exp_row['High'] - exp_row['Low']
            if range_total > 0:
                upper_wick = (exp_row['High'] - exp_row['Close']) / range_total
                if upper_wick >= self.UPPER_WICK_MAX:
                    continue

            # 20일 SMA 위
            ma20 = close.iloc[exp_idx - 20:exp_idx].mean()
            if exp_row['Close'] < ma20:
                continue

            # 갭다운 -3% 이상 제외
            gap = (exp_row['Open'] - prev_row['Close']) / prev_row['Close']
            if gap < self.GAP_DOWN_MIN:
                continue

            # 2단계: dry-up 조건 4가지 (현재 시점 기준)
            # 가격 유지
            if row['Close'] < exp_row['Open'] * self.PRICE_HOLD_MIN:
                continue
            # 조정폭
            if row['Close'] < exp_row['High'] * self.PRICE_DROP_MAX:
                continue
            # 20일 SMA 위 유지
            ma20_now = close.iloc[-20:].mean()
            if row['Close'] < ma20_now:
                continue
            # 거래량 dry-up: 최근 3일 평균 < 폭발봉 × 40%
            recent_3d_vol = volume.iloc[-3:].mean()
            if recent_3d_vol > exp_row['Volume'] * self.VOL_DRY_THRESHOLD:
                continue

            # 모든 조건 충족 → 시그널 생성
            ep = entry_price or row['Close']
            atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
            # Wyckoff 정석 (LuxAlgo/EBC): "spring/recent low 직하 (consolidation 하단)"
            # 우리 적용: dry-up 구간(폭발봉 이후) 최저가 -0.5% vs 폭발봉 시가 -1% vs ATR×2 cap
            dryup_low = df['Low'].iloc[exp_idx:].min()
            dryup_low_stop_pct = (dryup_low * 0.995 / ep) - 1
            exp_open_stop_pct = (exp_row['Open'] * 0.99 / ep) - 1
            stop_loss_pct = max(dryup_low_stop_pct, exp_open_stop_pct, atr_stop_pct, -0.08)
            target_pct = atr_target_pct

            vol_decrease_pct = (1 - recent_3d_vol / exp_row['Volume']) * 100
            reason = (f"매물 소화 패턴 · {offset}일 전 폭발봉 +{change*100:.1f}% · "
                      f"거래량 {exp_row['Volume']/vol_avg_20:.1f}배 → 현재 -{vol_decrease_pct:.0f}% dry-up · "
                      f"세력 매집 가능성")

            return self._make_signal(
                ticker, ticker_name, sector, ep,
                target_pct=target_pct, stop_loss_pct=stop_loss_pct,
                hold_min=3, hold_max=10, confidence=0.72,
                signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
                reason=reason,
            )

        return None

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
