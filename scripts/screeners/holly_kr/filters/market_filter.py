"""
시장 환경 필터 (v4.0)

KOSPI/KOSDAQ 추세, 변동성, 외국인 수급 기반 시장 레짐 판별.
레짐별 전략 카테고리 가중치 매핑 제공.
"""

import numpy as np
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from typing import Dict, Optional


# ============================================================================
# 레짐별 전략 카테고리 가중치
# ============================================================================
REGIME_WEIGHTS: Dict[str, Dict[str, float]] = {
    '상승장_저변동': {
        'breakout': 1.3,
        'gap_momentum': 1.3,
        'legendary': 1.2,      # legendary_trend
        'momentum': 1.2,
        'trend': 1.2,
        'mean_reversion': 0.7,
        'support_bounce': 1.0,
        'pullback': 0.9,
    },
    '상승장_고변동': {
        'breakout': 0.7,       # 거짓 돌파 많아짐
        'gap_momentum': 0.9,
        'legendary': 1.0,
        'momentum': 0.9,
        'trend': 0.9,
        'mean_reversion': 1.0,
        'support_bounce': 1.3,
        'pullback': 1.3,
    },
    '횡보장': {
        'breakout': 0.8,
        'gap_momentum': 0.7,
        'legendary': 0.9,
        'momentum': 0.8,
        'trend': 0.8,
        'mean_reversion': 1.3,
        'support_bounce': 1.3,
        'pullback': 1.1,
    },
    '하락장': {
        'breakout': 0.4,
        'gap_momentum': 0.4,
        'legendary': 0.5,
        'momentum': 0.4,
        'trend': 0.4,
        'mean_reversion': 0.6,
        'support_bounce': 0.6,
        'pullback': 0.5,
    },
}

# 하락장 최소 현금 비율
BEAR_CASH_WEIGHT = 0.5


def _fetch_index(ticker: str, days: int = 120) -> Optional[pd.DataFrame]:
    """지수 OHLCV 가져오기."""
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        df = fdr.DataReader(ticker, start.strftime('%Y-%m-%d'))
        if df is not None and len(df) > 50:
            return df
    except Exception:
        pass
    return None


def _calc_trend(df: pd.DataFrame) -> str:
    """50일 이평선 대비 추세 판단."""
    ma50 = df['Close'].rolling(50).mean()
    current = df['Close'].iloc[-1]
    ma50_val = ma50.iloc[-1]
    if pd.isna(ma50_val):
        return 'unknown'
    return 'up' if current > ma50_val else 'down'


def _calc_volatility(df: pd.DataFrame, window: int = 20) -> float:
    """20일 실현 변동성 (연율화, %)."""
    returns = df['Close'].pct_change().dropna().tail(window)
    if len(returns) < window // 2:
        return 15.0  # 기본값
    return float(returns.std() * np.sqrt(252) * 100)


def _calc_foreign_flow(df_kospi: Optional[pd.DataFrame]) -> str:
    """
    외국인 수급 방향 추정.

    KOSPI 지수의 최근 5일 수익률 방향과 거래량 변화로 간접 추정.
    (직접적인 외국인 순매수 데이터는 개별 종목 수급에서 처리)
    """
    if df_kospi is None or len(df_kospi) < 10:
        return 'neutral'

    recent_5d = df_kospi['Close'].iloc[-5:]
    ret_5d = (recent_5d.iloc[-1] / recent_5d.iloc[0]) - 1

    if ret_5d > 0.01:
        return 'inflow'
    elif ret_5d < -0.01:
        return 'outflow'
    return 'neutral'


def get_market_regime() -> dict:
    """
    시장 레짐 판별 (v4.0).

    Returns:
        {
            'kospi_trend': 'up' | 'down' | 'unknown',
            'kosdaq_trend': 'up' | 'down' | 'unknown',
            'regime': '상승장_저변동' | '상승장_고변동' | '횡보장' | '하락장',
            'kospi_volatility': float (연율화 %),
            'kosdaq_volatility': float (연율화 %),
            'kospi_bullish': bool,
            'foreign_flow': 'inflow' | 'outflow' | 'neutral',
            'category_weights': dict,     # 카테고리별 가중치
            'bear_cash_weight': float,    # 하락장일 때 최소 현금 비율
        }
    """
    result = {}
    df_kospi = None

    for name, ticker in [('kospi', 'KS11'), ('kosdaq', 'KQ11')]:
        df = _fetch_index(ticker)
        if name == 'kospi':
            df_kospi = df

        if df is not None and len(df) > 50:
            result[f'{name}_trend'] = _calc_trend(df)
            result[f'{name}_bullish'] = df['Close'].iloc[-1] > df['Open'].iloc[-1]
            result[f'{name}_volatility'] = _calc_volatility(df)
        else:
            result[f'{name}_trend'] = 'unknown'
            result[f'{name}_bullish'] = True
            result[f'{name}_volatility'] = 15.0

    # 외국인 수급 방향
    result['foreign_flow'] = _calc_foreign_flow(df_kospi)

    # ---------------------------------------------------------------
    # 레짐 판별 로직
    # ---------------------------------------------------------------
    kospi_up = result.get('kospi_trend') == 'up'
    kosdaq_up = result.get('kosdaq_trend') == 'up'
    avg_vol = (result.get('kospi_volatility', 15) + result.get('kosdaq_volatility', 15)) / 2
    low_vol = avg_vol < 20

    # KOSPI와 KOSDAQ 모두 고려
    both_up = kospi_up and kosdaq_up
    either_up = kospi_up or kosdaq_up
    both_down = not kospi_up and not kosdaq_up

    if both_down and not low_vol:
        regime = '하락장'
    elif either_up and low_vol:
        regime = '상승장_저변동'
    elif either_up and not low_vol:
        regime = '상승장_고변동'
    elif both_down and low_vol:
        regime = '횡보장'
    else:
        regime = '횡보장'

    # 외국인 대규모 이탈 시 하락장 격상
    if result['foreign_flow'] == 'outflow' and both_down:
        regime = '하락장'

    result['regime'] = regime
    result['category_weights'] = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS['횡보장'])
    result['bear_cash_weight'] = BEAR_CASH_WEIGHT if regime == '하락장' else 0.0

    return result


def get_category_weight(regime_info: dict, category: str) -> float:
    """
    특정 전략 카테고리의 레짐 가중치 반환.

    Args:
        regime_info: get_market_regime() 반환값
        category: 전략 카테고리 (breakout, pullback, ...)

    Returns:
        가중치 float (1.0 = 기본)
    """
    weights = regime_info.get('category_weights', {})
    return weights.get(category, 1.0)
