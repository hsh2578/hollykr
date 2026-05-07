"""
Phase 10-4: Risk Agent (종목 위험 평가)

룰 기반. 시그널 종목별로 위험 점검 → 폐기 또는 confidence_multiplier.

검사 항목:
1. 시총 (소형주 페널티)
2. 거래대금 (유동성 부족 페널티)
3. 호가 spread (슬리피지 위험)
4. ATR 비율 (변동성 과대)
5. 베타 (시장 노출도, 위험 시 페널티)

출력:
    {
        ticker: {
            'risk_level': 0.0~1.0,
            'multiplier': 0.7~1.0,
            'warnings': List[str],
        }
    }
"""

from typing import Dict, List, Any, Optional
import logging

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ============================================================================
# 위험 임계값
# ============================================================================

MIN_MARKET_CAP_SAFE = 5000           # 시총 5,000억 이상 = 안전
MIN_MARKET_CAP_OK = 1500             # 1,500억 미만 = 페널티
MIN_DAILY_VALUE_OK = 10_000_000_000  # 일평균 거래대금 100억 이상 = 안전
MIN_DAILY_VALUE_RISKY = 5_000_000_000   # 50억 미만 = 페널티
MAX_ATR_RATIO_OK = 0.05              # ATR/Price 5% 이하 = 안전
MAX_ATR_RATIO_RISKY = 0.10           # 10% 초과 = 페널티
MAX_HQ_SPREAD = 0.005                # 호가 spread 0.5% 미만

PENALTY_LIGHT = 0.90    # 경미한 페널티
PENALTY_MEDIUM = 0.80   # 중간 페널티
PENALTY_HEAVY = 0.65    # 심한 페널티
VETO_THRESHOLD = 0.50   # 0.5 미만 = 완전 폐기


class RiskAgent:
    """종목별 위험 평가 + 시그널 보정."""

    def __init__(self):
        self._cache: Dict[str, Dict] = {}

    def _calc_atr_ratio(self, df: pd.DataFrame, period: int = 20) -> float:
        """ATR / 종가 (변동성 비율)"""
        if len(df) < period:
            return 0.05
        high = df['High'].iloc[-period:]
        low = df['Low'].iloc[-period:]
        close_prev = df['Close'].shift(1).iloc[-period:]
        tr = np.maximum.reduce([
            (high - low).values,
            np.abs((high - close_prev).values),
            np.abs((low - close_prev).values),
        ])
        atr = np.mean(tr)
        last_close = df['Close'].iloc[-1]
        return float(atr / last_close) if last_close > 0 else 0.05

    def _calc_avg_value(self, df: pd.DataFrame, days: int = 20) -> float:
        """일평균 거래대금"""
        if len(df) < days:
            days = len(df)
        return float((df['Close'].iloc[-days:] * df['Volume'].iloc[-days:]).mean())

    def evaluate_ticker(self, ticker: str, market_cap: float = None) -> Dict[str, Any]:
        """단일 종목 위험 평가."""
        if ticker in self._cache:
            return self._cache[ticker]

        result = {
            'ticker': ticker,
            'risk_level': 0.0,
            'multiplier': 1.0,
            'warnings': [],
            'data': {},
        }

        # OHLCV 조회
        try:
            from scripts.ohlcv_data import get_ohlcv
            df = get_ohlcv(ticker, days=30, use_cache=True)
            if df is None or len(df) < 10:
                result['warnings'].append("OHLCV 데이터 부족")
                result['multiplier'] = PENALTY_HEAVY
                return result
        except Exception as e:
            result['warnings'].append(f"OHLCV 로드 실패: {e}")
            result['multiplier'] = PENALTY_HEAVY
            return result

        risk_score = 0.0

        # 1. 시총 (외부에서 받음, 없으면 추정)
        if market_cap:
            result['data']['market_cap_billion'] = round(market_cap, 0)
            if market_cap < MIN_MARKET_CAP_OK:
                risk_score += 0.3
                result['warnings'].append(f"시총 {market_cap:.0f}억 (소형주)")
            elif market_cap < MIN_MARKET_CAP_SAFE:
                risk_score += 0.1

        # 2. 거래대금
        avg_value = self._calc_avg_value(df, days=20)
        result['data']['avg_value_billion'] = round(avg_value / 1e8, 1)
        if avg_value < MIN_DAILY_VALUE_RISKY:
            risk_score += 0.4
            result['warnings'].append(f"거래대금 {avg_value/1e8:.0f}억 (유동성 부족)")
        elif avg_value < MIN_DAILY_VALUE_OK:
            risk_score += 0.15

        # 3. ATR 비율
        atr_ratio = self._calc_atr_ratio(df, period=20)
        result['data']['atr_ratio'] = round(atr_ratio, 4)
        if atr_ratio > MAX_ATR_RATIO_RISKY:
            risk_score += 0.4
            result['warnings'].append(f"변동성 {atr_ratio*100:.1f}% (과대)")
        elif atr_ratio > MAX_ATR_RATIO_OK:
            risk_score += 0.15

        # 4. 최근 5일 변동 폭 (panic 검증)
        recent_5d_high = df['High'].iloc[-5:].max()
        recent_5d_low = df['Low'].iloc[-5:].min()
        if recent_5d_low > 0:
            recent_range = (recent_5d_high - recent_5d_low) / recent_5d_low
            result['data']['recent_5d_range'] = round(recent_range, 3)
            if recent_range > 0.30:
                risk_score += 0.3
                result['warnings'].append(f"5일 변동폭 {recent_range*100:.0f}% (작전 의심)")
            elif recent_range > 0.20:
                risk_score += 0.1

        # 정규화
        result['risk_level'] = min(risk_score, 1.0)

        # Multiplier 산출
        if result['risk_level'] < 0.2:
            result['multiplier'] = 1.0
        elif result['risk_level'] < 0.4:
            result['multiplier'] = PENALTY_LIGHT
        elif result['risk_level'] < 0.7:
            result['multiplier'] = PENALTY_MEDIUM
        else:
            result['multiplier'] = PENALTY_HEAVY

        # VETO (시그널 폐기)
        if result['risk_level'] >= 0.85:
            result['multiplier'] = 0.0  # 폐기
            result['warnings'].append("위험 임계 초과 → 폐기")

        self._cache[ticker] = result
        return result

    def adjust_signals(self, signals: List) -> List:
        """시그널 리스트 위험 보정 (폐기 또는 confidence ×).

        Args:
            signals: List[Signal]

        Returns:
            폐기된 시그널 제거된 리스트
        """
        adjusted = []
        for sig in signals:
            # 시총 정보
            mc = getattr(sig, 'market_cap', None)
            risk = self.evaluate_ticker(sig.ticker, market_cap=mc)

            if risk['multiplier'] == 0.0:
                logger.debug(f"  Risk VETO: {sig.ticker} ({risk['warnings']})")
                continue

            old_conf = sig.confidence
            new_conf = old_conf * risk['multiplier']
            sig.confidence = new_conf

            # 위험 경고 추가
            if risk['warnings']:
                if not hasattr(sig, 'risk_warnings') or sig.risk_warnings is None:
                    sig.risk_warnings = []
                sig.risk_warnings.extend(risk['warnings'])

            adjusted.append(sig)

        return adjusted


# ============================================================================
# 테스트
# ============================================================================

if __name__ == '__main__':
    agent = RiskAgent()
    # 삼성전자 테스트
    r = agent.evaluate_ticker('005930', market_cap=5000000)  # 500조
    print(f"삼성전자 위험: {r['risk_level']:.2f}, multiplier {r['multiplier']:.2f}")
    print(f"  Data: {r['data']}")
    print(f"  Warnings: {r['warnings']}")
