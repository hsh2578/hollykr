"""
Phase 10-2: Macro Agent (시장 환경 평가)

룰 기반 (LLM X). KOSPI/KOSDAQ + USD/KRW + 미장 + 유가 → 시장 점수 산출.
모든 시그널의 confidence × multiplier 보정.

출력:
    {
        'kill_switch': bool,           # 시그널 송출 동결
        'risk_level': 0.0~1.0,         # 0=안전, 1=극위험
        'confidence_multiplier': 0.5~1.0,  # 시그널 신뢰도 보정
        'regime': str,                  # 강한상승/상승저변동/.../강한하락/패닉
        'reasons': List[str],          # 판정 근거
        'data': dict,                   # 원시 지표
    }
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# Yahoo Finance 데이터 fetch
# ============================================================================

def _fetch_yahoo(ticker: str, period: str = '6mo') -> Optional[pd.DataFrame]:
    """Yahoo Finance로 지수/통화/원자재 데이터 가져오기."""
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period=period)
        if df is not None and len(df) > 30:
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
    except Exception as e:
        logger.warning(f"[macro_agent] Yahoo {ticker} fetch 실패: {e}")
    return None


# ============================================================================
# 지표 계산
# ============================================================================

def _calc_returns(df: pd.DataFrame, days: int) -> float:
    """N일 누적 수익률 (%)"""
    if df is None or len(df) < days + 1:
        return 0.0
    return float((df['Close'].iloc[-1] / df['Close'].iloc[-days - 1] - 1))


def _calc_volatility(df: pd.DataFrame, window: int = 20) -> float:
    """N일 연율화 변동성 (%)"""
    if df is None or len(df) < window:
        return 15.0
    returns = df['Close'].pct_change().dropna().tail(window)
    if len(returns) < window // 2:
        return 15.0
    return float(returns.std() * np.sqrt(252) * 100)


def _calc_ma_gap(df: pd.DataFrame, ma_period: int = 200) -> float:
    """현재가 vs N일 SMA 이격도 (%)"""
    if df is None or len(df) < ma_period:
        return 0.0
    ma = df['Close'].rolling(ma_period).mean().iloc[-1]
    if pd.isna(ma) or ma <= 0:
        return 0.0
    return float((df['Close'].iloc[-1] / ma - 1) * 100)


def _calc_ma_slope(df: pd.DataFrame, ma_period: int = 200, lookback: int = 20) -> str:
    """N일 SMA 기울기 방향 (up/down/flat)"""
    if df is None or len(df) < ma_period + lookback:
        return 'unknown'
    ma = df['Close'].rolling(ma_period).mean()
    if pd.isna(ma.iloc[-1]) or pd.isna(ma.iloc[-lookback - 1]):
        return 'unknown'
    delta = (ma.iloc[-1] / ma.iloc[-lookback - 1] - 1) * 100
    if delta > 0.5:
        return 'up'
    elif delta < -0.5:
        return 'down'
    return 'flat'


# ============================================================================
# Macro Agent 본체
# ============================================================================

class MacroAgent:
    """시장 환경 평가 → 시그널 신뢰도 보정.

    Phase 10-2 핵심:
    1. KOSPI/KOSDAQ 추세 + 변동성 + 5일 수익률
    2. USD/KRW 흐름 (외국인 자금 유출입 proxy)
    3. 미장 영향 (^GSPC = S&P500)
    4. 유가 (CL=F) — 한국 인플레 영향
    5. Buying climax 룰 (5일 +10%+ + 변동성 > 30%)
    """

    def __init__(self):
        self._cache: Dict[str, Any] = {}

    def evaluate(self) -> Dict[str, Any]:
        """현재 시장 환경 평가."""
        result = {
            'kill_switch': False,
            'risk_level': 0.0,
            'confidence_multiplier': 1.0,
            'regime': '횡보장',
            'reasons': [],
            'warnings': [],
            'data': {},
        }

        # 1. 데이터 수집
        kospi = _fetch_yahoo('^KS11', '1y')
        kosdaq = _fetch_yahoo('^KQ11', '1y')
        usdkrw = _fetch_yahoo('KRW=X', '3mo')
        sp500 = _fetch_yahoo('^GSPC', '3mo')
        oil = _fetch_yahoo('CL=F', '3mo')

        # 2. 지표 산출
        data = {
            'kospi_5d_return': _calc_returns(kospi, 5),
            'kospi_20d_return': _calc_returns(kospi, 20),
            'kospi_volatility': _calc_volatility(kospi, 20),
            'kospi_60d_volatility': _calc_volatility(kospi, 60),
            'kospi_vs_200ma': _calc_ma_gap(kospi, 200),
            'kospi_200ma_slope': _calc_ma_slope(kospi, 200, 20),
            'kosdaq_5d_return': _calc_returns(kosdaq, 5),
            'kosdaq_volatility': _calc_volatility(kosdaq, 20),
            'usdkrw_5d_return': _calc_returns(usdkrw, 5),
            'sp500_5d_return': _calc_returns(sp500, 5),
            'oil_5d_return': _calc_returns(oil, 5),
        }
        result['data'] = data

        risk_score = 0.0  # 누적 위험 점수
        warnings = []
        reasons = []

        # ==========================================================
        # 위험 평가 (각 조건마다 risk_score 가산)
        # ==========================================================

        # A. KOSPI 5일 누적 수익률 < -5% (급락)
        if data['kospi_5d_return'] <= -0.05:
            risk_score += 1.0
            warnings.append(f"KOSPI 5일 {data['kospi_5d_return']*100:+.1f}% 급락")
            result['kill_switch'] = True

        # B. KOSPI 변동성 ≥ 35% (panic)
        if data['kospi_volatility'] >= 35:
            risk_score += 1.0
            warnings.append(f"KOSPI 변동성 {data['kospi_volatility']:.0f}% panic")
            result['kill_switch'] = True

        # C. Stage 4 (KOSPI < 200일 SMA + 200일 SMA 우하향)
        if data['kospi_vs_200ma'] < -2 and data['kospi_200ma_slope'] == 'down':
            risk_score += 1.0
            warnings.append(f"KOSPI Stage 4 (200일선 하향 {data['kospi_vs_200ma']:.1f}%)")
            result['kill_switch'] = True

        # ==========================================================
        # Buying Climax (강세장 과열) 룰 — 신뢰도 ↓
        # ==========================================================

        # D. 5일 +10%+ AND 변동성 > 30% = blow-off top
        if data['kospi_5d_return'] >= 0.10 and data['kospi_volatility'] >= 30:
            risk_score += 0.7
            warnings.append(f"Buying climax 의심 "
                            f"(5일 +{data['kospi_5d_return']*100:.1f}% + 변동성 {data['kospi_volatility']:.0f}%)")

        # E. 200일 SMA +50%+ 과열
        if data['kospi_vs_200ma'] >= 50:
            risk_score += 0.5
            warnings.append(f"KOSPI 200일선 {data['kospi_vs_200ma']:+.0f}% 과열")
        elif data['kospi_vs_200ma'] >= 30:
            risk_score += 0.2

        # ==========================================================
        # 외부 영향 (USD/KRW, 미장)
        # ==========================================================

        # F. USD/KRW 5일 +2%+ (원화 약세 → 외국인 이탈)
        if data['usdkrw_5d_return'] >= 0.02:
            risk_score += 0.3
            reasons.append(f"USD/KRW 5일 +{data['usdkrw_5d_return']*100:.1f}% (원화 약세)")

        # G. S&P 500 5일 -3%+ (미장 부진)
        if data['sp500_5d_return'] <= -0.03:
            risk_score += 0.3
            reasons.append(f"S&P500 5일 {data['sp500_5d_return']*100:+.1f}% 부진")

        # H. 유가 5일 +5%+ (인플레 우려)
        if data['oil_5d_return'] >= 0.05:
            risk_score += 0.2
            reasons.append(f"유가 5일 +{data['oil_5d_return']*100:.1f}% (인플레)")

        # ==========================================================
        # risk_level 정규화 (0.0 ~ 1.0)
        # ==========================================================

        result['risk_level'] = min(risk_score / 3.0, 1.0)

        # ==========================================================
        # confidence_multiplier 산출
        # ==========================================================

        if result['kill_switch']:
            result['confidence_multiplier'] = 0.0  # 송출 중단
        elif risk_score >= 1.5:
            result['confidence_multiplier'] = 0.5  # 위험 ↑ 시그널 약화
        elif risk_score >= 1.0:
            result['confidence_multiplier'] = 0.7
        elif risk_score >= 0.5:
            result['confidence_multiplier'] = 0.85
        else:
            result['confidence_multiplier'] = 1.0  # 정상

        # ==========================================================
        # 레짐 판별
        # ==========================================================

        if result['kill_switch']:
            result['regime'] = '강한하락' if data['kospi_5d_return'] < -0.03 else '패닉'
        elif data['kospi_5d_return'] >= 0.05 and data['kospi_volatility'] < 25:
            result['regime'] = '강한상승'
        elif data['kospi_5d_return'] >= 0 and data['kospi_volatility'] < 20:
            result['regime'] = '상승장_저변동'
        elif data['kospi_5d_return'] >= 0 and data['kospi_volatility'] >= 20:
            result['regime'] = '상승장_고변동'
        elif data['kospi_5d_return'] < 0 and data['kospi_volatility'] >= 20:
            result['regime'] = '완만하락'
        else:
            result['regime'] = '횡보장'

        result['warnings'] = warnings
        result['reasons'] = reasons

        return result


# ============================================================================
# 테스트
# ============================================================================

if __name__ == '__main__':
    agent = MacroAgent()
    r = agent.evaluate()

    print("=" * 60)
    print(f"  Macro Agent - 시장 환경 평가")
    print("=" * 60)
    print(f"  레짐:           {r['regime']}")
    print(f"  Risk Level:     {r['risk_level']:.2f} / 1.0")
    print(f"  신뢰도 보정:     x {r['confidence_multiplier']:.2f}")
    print(f"  Kill Switch:    {'[ON]' if r['kill_switch'] else 'OFF'}")
    print()

    if r['warnings']:
        print("  [경고]")
        for w in r['warnings']:
            print(f"    - {w}")
        print()

    if r['reasons']:
        print("  [참고 사유]")
        for s in r['reasons']:
            print(f"    - {s}")
        print()

    print("  [원시 지표]")
    for k, v in r['data'].items():
        if isinstance(v, float):
            if 'return' in k or 'gap' in k:
                print(f"    {k:<25s}: {v*100:+.2f}%")
            else:
                print(f"    {k:<25s}: {v:.2f}")
        else:
            print(f"    {k:<25s}: {v}")
