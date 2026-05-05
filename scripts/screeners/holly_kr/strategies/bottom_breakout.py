"""전략 35: Bottom Breakout (점수제 12점 만점) [등급 A-] [HYBRID]
충분히 하락 후 바닥 다지고 상승 전환. 6 항목 가중 점수.
RSI 단순 트리거(balloon_under_water)보다 노이즈 작음.
출처: stock-screener-kr bottom_breakout 한국화."""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class BottomBreakout(BaseStrategy):
    name = "bottom_breakout"
    category = "mean_reversion"  # RR 2.0 (2.5x/1.25x ATR)
    exec_timing = "HYBRID"
    grade = "A-"

    MIN_SCORE = 7  # 12점 만점 중 7점 이상만 시그널

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 252:  # 52주 데이터 필요
            return None

        row = df.iloc[-1]
        close = df['Close']
        high = df['High']
        low = df['Low']
        volume = df['Volume']

        # ============================================================
        # 1단계: 필수 조건 (3 모두 충족)
        # ============================================================
        # 1. 52주 고점 대비 -30% ~ -75%
        high_52w = high.iloc[-252:].max()
        drop_pct = (row['Close'] - high_52w) / high_52w
        if drop_pct > -0.30 or drop_pct < -0.75:
            return None

        # 2. 최근 10일 신저가 미갱신 (52주 신저가 아님)
        low_52w = low.iloc[-252:].min()
        recent_10d_low = low.iloc[-10:].min()
        if recent_10d_low <= low_52w * 1.001:  # 0.1% 마진
            return None

        # 3. 5일 평균 거래대금 1억 이상
        avg_value_5d = (close.iloc[-5:] * volume.iloc[-5:]).mean()
        if avg_value_5d < 1_00_000_000:  # 1억
            return None

        # ============================================================
        # 2단계: 점수 항목 (12점 만점, 7점 이상 통과)
        # ============================================================
        score = 0

        # 150일 SMA
        ma150 = close.rolling(150).mean()
        ma150_now = ma150.iloc[-1]
        if pd.isna(ma150_now):
            return None

        ma150_gap = (row['Close'] - ma150_now) / ma150_now

        # 항목 1: 150일선 근접 (-5% ~ +15%) — 2점
        if -0.05 <= ma150_gap <= 0.15:
            score += 2

        # 항목 2: 150일선 돌파 + 거래량 1.5배 + 양봉 (5일 내) — 3점
        for i in range(-5, 0):
            if i + 1 >= 0:
                continue
            ma150_i = ma150.iloc[i]
            ma150_prev = ma150.iloc[i - 1]
            if pd.isna(ma150_i) or pd.isna(ma150_prev):
                continue
            close_i = close.iloc[i]
            close_prev = close.iloc[i - 1]
            open_i = df['Open'].iloc[i]
            vol_i = volume.iloc[i]
            vol_avg_20 = volume.iloc[i - 20:i].mean()
            if vol_avg_20 <= 0:
                continue
            # 아래에서 위로 돌파 + 양봉 + 거래량 1.5배
            if (close_prev <= ma150_prev and close_i > ma150_i
                    and close_i > open_i and vol_i >= vol_avg_20 * 1.5):
                score += 3
                break

        # 항목 3: 저점 상승 (최근 20일 저점 > 이전 20일 저점) — 2점
        recent_low_20 = low.iloc[-20:].min()
        prev_low_20 = low.iloc[-40:-20].min()
        if recent_low_20 > prev_low_20:
            score += 2

        # 항목 4: 150일선 기울기 상승 (20일 기울기 > 0) — 2점
        if len(ma150) >= 21 and not pd.isna(ma150.iloc[-21]):
            slope = (ma150_now - ma150.iloc[-21]) / ma150.iloc[-21]
            if slope > 0:
                score += 2

        # 항목 5: 거래량 5일 평균 > 20일 평균 × 1.5 — 2점
        vol_5 = volume.iloc[-5:].mean()
        vol_20 = volume.iloc[-20:].mean()
        if vol_20 > 0 and vol_5 > vol_20 * 1.5:
            score += 2

        # 항목 6: MACD 골든크로스 5일 내 — 1점
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        for i in range(-5, 0):
            if i + 1 >= 0:
                continue
            if macd.iloc[i - 1] <= signal_line.iloc[i - 1] and macd.iloc[i] > signal_line.iloc[i]:
                score += 1
                break

        # ============================================================
        # 점수 컷
        # ============================================================
        if score < self.MIN_SCORE:
            return None

        ep = entry_price or row['Close']

        # Weinstein 정석 (TraderLion/Bulkowski): "200일 MA 하단 OR 직전 swing low 직하"
        # 우리 적용: 200일 SMA -1% vs 직전 20일 swing low -0.5% vs ATR×1.25 cap
        ma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
        swing_low = low.iloc[-20:].min()
        swing_low_pct = (swing_low * 0.995 / ep) - 1
        atr_target_pct, atr_stop_pct = self._atr_target_stop(df, ep)
        candidates = [swing_low_pct, atr_stop_pct, -0.07]
        if ma200 is not None and not pd.isna(ma200):
            ma200_stop_pct = (ma200 * 0.99 / ep) - 1  # 200일 SMA -1%
            candidates.append(ma200_stop_pct)
        stop_loss_pct = max(candidates)  # 가장 가까운 (덜 손해) 쪽

        target_pct = atr_target_pct

        grade_label = "A급" if score >= 9 else "B급"
        reason = (f"바닥 탈출 점수 {score}/12점 ({grade_label}) · "
                  f"52주 고점 대비 {drop_pct*100:.0f}% 하락 후 반등 신호 · "
                  f"150일선 이격 {ma150_gap*100:+.1f}%")

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=stop_loss_pct,
            hold_min=5, hold_max=15,
            confidence=0.65 + 0.05 * (score - self.MIN_SCORE) / 5,  # 7점=0.65, 12점=0.85
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
            reason=reason,
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
