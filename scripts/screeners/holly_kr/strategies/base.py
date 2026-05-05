"""
BaseStrategy — 모든 전략의 부모 클래스 (Week 2: 카테고리별 ATR + Stage 2 + 거래량 헬퍼)
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict

import pandas as pd

from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.config import (
    RR_THRESHOLD_DEFAULT, RR_THRESHOLD_STRONG,
    RISK_PER_TRADE_PCT, MAX_POSITION_PER_STOCK,
)

# RR 2.5 컷 적용 카테고리 (탑 퀀트 권고: 보유 길거나 진입이 지지선에서 먼 카테고리)
STRONG_RR_CATEGORIES = {
    'breakout', 'trend_following', 'trend',
    'momentum', 'gap_momentum', 'accumulation', 'multi_factor',
}
# legendary 카테고리 내 STRONG (Darvas/Weinstein/Minervini/Livermore)
STRONG_RR_LEGENDARY = {
    'darvas_box', 'weinstein_stage', 'minervini_trend_template',
    'minervini_trend', 'livermore_pivot',
}

# 카테고리별 ATR 배수 프리셋 (target_mult, stop_mult, hold_max)
# 자료조사 기반 (Chandelier 22일/3×, Minervini SEPA, Weinstein Stage)
CATEGORY_ATR_PRESETS = {
    # 추세/돌파: target 멀리, RR 2.5+
    'breakout':         (5.0, 2.0),   # RR 2.5
    'trend_following':  (5.0, 2.0),   # RR 2.5
    'trend':            (5.0, 2.0),
    'momentum':         (4.5, 2.0),   # RR 2.25
    'gap_momentum':     (4.0, 1.6),   # RR 2.5 (빠른 청산)
    'accumulation':     (5.0, 2.0),   # RR 2.5 (장기)
    'multi_factor':     (4.5, 2.0),   # RR 2.25
    # 눌림목/지지/평균회귀: target 가깝, RR 2.0
    'pullback':         (3.0, 1.5),   # RR 2.0
    'support_bounce':   (3.0, 1.5),   # RR 2.0
    'mean_reversion':   (2.5, 1.25),  # RR 2.0
    'reversal':         (3.0, 1.5),   # RR 2.0
    # legendary: 전략명별 개별 처리 (아래 LEGENDARY_PRESETS)
    'legendary':        (4.0, 2.0),   # 기본
}

# legendary 카테고리 전략별 개별 프리셋
LEGENDARY_PRESETS = {
    'darvas_box':                (5.0, 2.0),  # 박스 돌파 → 추세
    'weinstein_stage':           (5.0, 2.0),  # Stage 2 → 장기 추세
    'minervini_trend_template':  (5.0, 2.0),  # SEPA
    'minervini_trend':           (5.0, 2.0),
    'livermore_pivot':           (4.0, 1.5),  # 피보탈 (이미 -3% stop 룰)
    'magic_formula':             (4.0, 2.0),  # 펀더 (비활성)
    'piotroski_fscore':          (4.0, 2.0),  # 펀더 (비활성)
}


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

    def _category_atr_preset(self) -> tuple:
        """전략 카테고리에 따른 (target_multiple, stop_multiple) 반환.

        legendary는 전략명으로 개별 매핑.
        """
        # legendary는 전략명 기반
        if self.category == 'legendary' and self.name in LEGENDARY_PRESETS:
            return LEGENDARY_PRESETS[self.name]
        # 일반 카테고리
        return CATEGORY_ATR_PRESETS.get(self.category, (4.0, 2.0))

    def _atr_target_stop(self, df: pd.DataFrame, entry_price: float,
                          target_multiple: float = None,
                          stop_multiple: float = None) -> tuple:
        """ATR 기반 동적 목표/손절 계산 (카테고리 인식형)

        Args:
            target_multiple: ATR의 N배 = 목표. None이면 카테고리 기본값
            stop_multiple: ATR의 N배 = 손절. None이면 카테고리 기본값

        Returns:
            (target_pct, stop_loss_pct)
        """
        # 카테고리 기본값 자동 적용
        cat_target, cat_stop = self._category_atr_preset()
        if target_multiple is None:
            target_multiple = cat_target
        if stop_multiple is None:
            stop_multiple = cat_stop

        atr = self._calc_atr(df)
        if atr <= 0 or entry_price <= 0:
            return 0.05, -0.03  # fallback

        target_pct = (atr * target_multiple) / entry_price
        stop_loss_pct = -(atr * stop_multiple) / entry_price

        # 최소/최대 제한 (한국 주식 변동성 반영)
        target_pct = max(0.03, min(target_pct, 0.25))    # 25% 상한 (기존 20%에서 확장)
        stop_loss_pct = max(-0.15, min(stop_loss_pct, -0.02))

        return round(target_pct, 4), round(stop_loss_pct, 4)

    def _rr_threshold(self) -> float:
        """카테고리별 RR 컷 (확장: STRONG 2.5, 그 외 2.0). legendary는 전략명별 처리."""
        if self.category == 'legendary':
            return RR_THRESHOLD_STRONG if self.name in STRONG_RR_LEGENDARY else RR_THRESHOLD_DEFAULT
        return RR_THRESHOLD_STRONG if self.category in STRONG_RR_CATEGORIES else RR_THRESHOLD_DEFAULT

    # ========================================================================
    # 거시 필터 헬퍼 (Stage 2, 주봉 추세, 거래량)
    # ========================================================================

    @staticmethod
    def _check_stage_2(df: pd.DataFrame) -> bool:
        """Stage 2 거시 필터 (Weinstein/Minervini/O'Neil 통합 룰)

        4가지 모두 충족:
        1. 종가 > 200일 SMA
        2. 종가 > 50일 SMA
        3. 50일 SMA > 200일 SMA
        4. 200일 SMA 우상향 (1개월 전 대비)
        """
        if len(df) < 220:
            return False
        close = df['Close']
        ma50 = close.rolling(50).mean()
        ma200 = close.rolling(200).mean()
        last_close = close.iloc[-1]
        ma50_now = ma50.iloc[-1]
        ma200_now = ma200.iloc[-1]
        ma200_1m_ago = ma200.iloc[-21]
        if pd.isna(ma200_now) or pd.isna(ma50_now) or pd.isna(ma200_1m_ago):
            return False
        return (last_close > ma200_now and last_close > ma50_now
                and ma50_now > ma200_now and ma200_now > ma200_1m_ago)

    @staticmethod
    def _check_volume_with_climax(df: pd.DataFrame, min_mult: float, max_mult: float = 10.0,
                                   period: int = 50) -> bool:
        """거래량 컷 (하한 + climax 상한).

        period일 평균 거래량 대비 [min_mult, max_mult] 구간이어야 통과.
        max_mult 초과 = volume climax = 천장 신호 → 폐기
        """
        if len(df) < period + 1:
            return False
        avg_vol = df['Volume'].rolling(period).mean().iloc[-1]
        cur_vol = df['Volume'].iloc[-1]
        if avg_vol <= 0:
            return False
        ratio = cur_vol / avg_vol
        return min_mult <= ratio <= max_mult

    @staticmethod
    def _check_pullback_volume_dynamics(df: pd.DataFrame, pullback_days: int = 5) -> bool:
        """눌림목 거래량 dynamics: 눌림 시 dry-up → 반등 시 expansion

        조건:
        - 최근 pullback_days 평균 거래량 < 직전 20일 평균 (dry-up)
        - 당일 거래량 > 최근 pullback_days 평균 × 1.3 (반등 expansion)
        """
        if len(df) < 20 + pullback_days:
            return False
        vol = df['Volume']
        recent_pullback_avg = vol.iloc[-pullback_days-1:-1].mean()
        prior_avg = vol.iloc[-20-pullback_days:-pullback_days].mean()
        today_vol = vol.iloc[-1]
        if prior_avg <= 0 or recent_pullback_avg <= 0:
            return False
        # dry-up: 최근 평균 < 직전 평균 × 0.85
        if recent_pullback_avg >= prior_avg * 0.85:
            return False
        # expansion: 당일 > 최근 평균 × 1.3
        return today_vol > recent_pullback_avg * 1.3

    def _make_signal(self, ticker: str, ticker_name: str, sector: str,
                     entry_price: float, target_pct: float, stop_loss_pct: float,
                     hold_min: int, hold_max: int, confidence: float,
                     signal_date: str, reason: str = "") -> Optional[Signal]:
        """시그널 생성 헬퍼 (엄격한 RR 게이트 — 자동 확장 X)

        Week 3 검증 결과: auto-extend는 실패. 짧은 stop + 먼 target → PF<1.
        대신 각 전략이 명시적으로 ATR-based target을 사용하도록 수정.
        """
        if entry_price <= 0:
            return None
        risk = -stop_loss_pct
        reward = target_pct
        if risk <= 0.005 or risk > 0.10:
            return None  # 비현실적 손절폭 폐기
        if reward <= 0:
            return None  # target=0 또는 음수 폐기 (전략에서 ATR-based로 명시 필요)
        rr = reward / risk
        if rr < self._rr_threshold():
            return None

        # 포지션 사이징 (vol-target): 손절폭에 반비례
        position_size_pct = min(
            RISK_PER_TRADE_PCT / abs(stop_loss_pct),
            MAX_POSITION_PER_STOCK,
        )

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
            reason=reason,
            position_size_pct=round(position_size_pct, 4),
        )
        sig.calc_rr_ratio()
        return sig
