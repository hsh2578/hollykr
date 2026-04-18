"""
BaseStrategy — 모든 전략의 부모 클래스
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict

import pandas as pd

from scripts.screeners.holly_kr.signal_model import Signal


class BaseStrategy(ABC):
    name: str = ""
    category: str = ""
    exec_timing: str = "EOD"
    grade: str = "B"

    @abstractmethod
    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0) -> Optional[Signal]:
        """
        일봉 데이터로 시그널 스캔.

        Args:
            df: OHLCV DataFrame (Open, High, Low, Close, Volume)
            ticker: 종목코드
            ticker_name: 종목명
            sector: WICS 섹터명
            entry_price: 진입 예상가 (다음날 시가 추정 = 당일 종가)

        Returns:
            Signal or None
        """
        pass

    @abstractmethod
    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        """
        청산 조건 확인.

        Returns: None(유지), 'stop_loss', 'target', 'time', 'condition'
        """
        pass

    @staticmethod
    def _calc_atr(df: pd.DataFrame, period: int = 20) -> float:
        """ATR (Average True Range) 계산"""
        high = df['High']
        low = df['Low']
        close = df['Close']
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr) if not pd.isna(atr) else 0.0

    def _atr_target_stop(self, df: pd.DataFrame, entry_price: float,
                          target_multiple: float = 3.0,
                          stop_multiple: float = 2.0) -> tuple:
        """ATR 기반 동적 목표/손절 계산

        Args:
            target_multiple: ATR의 N배 = 목표 (기본 3배)
            stop_multiple: ATR의 N배 = 손절 (기본 2배)

        Returns:
            (target_pct, stop_loss_pct)
        """
        atr = self._calc_atr(df)
        if atr <= 0 or entry_price <= 0:
            return 0.05, -0.03  # fallback

        target_pct = (atr * target_multiple) / entry_price
        stop_loss_pct = -(atr * stop_multiple) / entry_price

        # 최소/최대 제한
        target_pct = max(0.03, min(target_pct, 0.20))
        stop_loss_pct = max(-0.15, min(stop_loss_pct, -0.02))

        return round(target_pct, 4), round(stop_loss_pct, 4)

    def _make_signal(self, ticker: str, ticker_name: str, sector: str,
                     entry_price: float, target_pct: float, stop_loss_pct: float,
                     hold_min: int, hold_max: int, confidence: float,
                     signal_date: str) -> Signal:
        """시그널 생성 헬퍼"""
        sig = Signal(
            strategy_name=self.name,
            ticker=ticker,
            ticker_name=ticker_name,
            entry_price=entry_price,
            target_price=entry_price * (1 + target_pct),
            stop_loss_price=entry_price * (1 + stop_loss_pct),
            target_pct=target_pct,
            stop_loss_pct=stop_loss_pct,
            hold_days_min=hold_min,
            hold_days_max=hold_max,
            confidence=confidence,
            exec_timing=self.exec_timing,
            category=self.category,
            grade=self.grade,
            signal_date=signal_date,
            sector=sector,
        )
        sig.calc_rr_ratio()
        return sig
