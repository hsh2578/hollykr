"""전략 8: Darvas Box [등급 A] [EOD]
박스 횡보 → 상단 돌파 + 거래량 2배 → 매수."""

from typing import Optional, Dict
import pandas as pd
import numpy as np
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.indicators import close_position_ratio


class DarvasBox(BaseStrategy):
    name = "darvas_box"
    category = "legendary"
    exec_timing = "EOD"
    grade = "A"

    def _find_darvas_box(self, df: pd.DataFrame):
        """
        Darvas Box 찾기:
        1. 20일 신고가 발생
        2. 이후 3일간 해당 고가 미돌파 → 박스 상단 확정
        3. 박스 상단 확정 후 3일간 최저가 = 박스 하단
        4. 박스 높이 <= 중간값의 15%
        """
        if len(df) < 10:
            return None, None

        highs = df['High']
        lows = df['Low']

        # 최근 데이터에서 20일 신고가 시점 찾기 (최소 7일 전 ~ 4일 전)
        # 박스 상단 후보: 20일 신고가를 찍은 날
        for offset in range(7, min(25, len(df) - 1)):
            idx = len(df) - 1 - offset
            if idx < 20:
                break

            # 이 날이 20일 신고가인지 확인
            window_high = highs.iloc[max(0, idx - 19):idx + 1].max()
            if highs.iloc[idx] < window_high:
                continue

            box_top = highs.iloc[idx]

            # 이후 3일간 box_top 미돌파 확인
            after_high_start = idx + 1
            after_high_end = min(idx + 4, len(df) - 1)  # 3일
            if after_high_end - after_high_start < 3:
                continue

            broken = False
            for j in range(after_high_start, after_high_end):
                if highs.iloc[j] > box_top:
                    broken = True
                    break
            if broken:
                continue

            # 박스 하단: 박스 상단 확정 후 3일간 최저가
            bottom_start = after_high_start
            bottom_end = min(after_high_start + 3, len(df))
            if bottom_end <= bottom_start:
                continue
            box_bottom = lows.iloc[bottom_start:bottom_end].min()

            # 박스 높이 체크: 중간값의 15% 이내
            box_mid = (box_top + box_bottom) / 2
            if box_mid <= 0:
                continue
            if (box_top - box_bottom) / box_mid > 0.15:
                continue

            return box_top, box_bottom

        return None, None

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        if len(df) < 25:
            return None

        row = df.iloc[-1]

        # Darvas Box 찾기
        box_top, box_bottom = self._find_darvas_box(df.iloc[:-1])  # 당일 제외하고 박스 탐색
        if box_top is None or box_bottom is None:
            return None

        # 돌파: 종가 > 박스 상단 x 1.005
        if row['Close'] <= box_top * 1.005:
            return None

        # 거래량 20일 평균의 2배
        if row['Volume'] <= df['Volume'].rolling(20).mean().iloc[-1] * 2.0:
            return None

        # 종가 레인지 상위 30% (position >= 0.7)
        if close_position_ratio(row) < 0.7:
            return None

        ep = entry_price or row['Close']
        box_height = box_top - box_bottom
        target = ep + box_height
        target_pct = max((target / ep - 1), 0.05)  # 최소 5% 목표
        # 손절: 박스 하단 또는 entry x 0.95
        stop = max(box_bottom, ep * 0.95)

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=target_pct, stop_loss_pct=(stop / ep - 1),
            hold_min=1, hold_max=10, confidence=0.70,
            signal_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else '',
        )

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        return None
