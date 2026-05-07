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
    """지수 OHLCV 가져오기.

    Phase 10-1: Yahoo Finance 우선 사용 (FDR/KRX API는 LOGOUT 에러 빈번).
    Yahoo 실패 시 FDR 폴백.

    ticker 매핑:
        'KS11' → '^KS11' (KOSPI)
        'KQ11' → '^KQ11' (KOSDAQ)
    """
    end = datetime.now()
    start = end - timedelta(days=days)

    # 1차: Yahoo Finance (안정적)
    try:
        import yfinance as yf
        yahoo_ticker = f'^{ticker}'  # KS11 → ^KS11
        period_str = '1y' if days > 200 else ('6mo' if days > 90 else '3mo')
        yf_df = yf.Ticker(yahoo_ticker).history(period=period_str)
        if yf_df is not None and len(yf_df) > 50:
            # Yahoo 컬럼: Open/High/Low/Close/Volume (그대로 사용 가능)
            # timezone 제거 (FDR 호환)
            if yf_df.index.tz is not None:
                yf_df.index = yf_df.index.tz_localize(None)
            return yf_df
    except Exception as e:
        import logging
        logging.warning(f"[market_filter] Yahoo {ticker} fetch 실패: {e}")

    # 2차 폴백: FDR
    try:
        df = fdr.DataReader(ticker, start.strftime('%Y-%m-%d'))
        if df is not None and len(df) > 50:
            return df
    except Exception as e:
        import logging
        logging.warning(f"[market_filter] FDR {ticker} fetch 실패: {e}")

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


def _check_kill_switch_conditions(df_kospi: Optional[pd.DataFrame]) -> dict:
    """Kill Switch 조건 점검 (Phase 6).

    Returns:
        {
            'kill_switch': bool,
            'reasons': List[str],
            'kospi_5d_return': float,
            'kospi_below_200ma': bool,
            'volatility_panic': bool,
        }
    """
    out = {
        'kill_switch': False,
        'reasons': [],
        'kospi_5d_return': 0.0,
        'kospi_below_200ma': False,
        'volatility_panic': False,
    }
    if df_kospi is None or len(df_kospi) < 200:
        return out

    close = df_kospi['Close']

    # 1. 5일 누적 수익률 < -5%
    if len(close) >= 6:
        ret_5d = (close.iloc[-1] / close.iloc[-6]) - 1
        out['kospi_5d_return'] = float(ret_5d)
        if ret_5d <= -0.05:
            out['kill_switch'] = True
            out['reasons'].append(f"KOSPI 5일 누적 {ret_5d*100:.1f}% (≤-5%)")

    # 2. KOSPI < 200일 SMA AND 200일 SMA 우하향
    ma200 = close.rolling(200).mean()
    if not pd.isna(ma200.iloc[-1]):
        below_200 = close.iloc[-1] < ma200.iloc[-1]
        out['kospi_below_200ma'] = below_200
        if below_200 and len(close) >= 220:
            ma200_now = ma200.iloc[-1]
            ma200_1m_ago = ma200.iloc[-21]
            if ma200_1m_ago > ma200_now:  # 200일 SMA 우하향
                out['kill_switch'] = True
                out['reasons'].append("KOSPI 200일 SMA 하향 + 우하향 (Stage 4)")

    # 3. 변동성 panic (>35% 연율화)
    vol = _calc_volatility(df_kospi)
    if vol >= 35:
        out['volatility_panic'] = True
        out['kill_switch'] = True
        out['reasons'].append(f"KOSPI 연율화 변동성 {vol:.0f}% (≥35% panic)")

    return out


def get_market_regime() -> dict:
    """
    시장 레짐 판별 (Phase 6 강화).

    Returns:
        {
            'kospi_trend': 'up' | 'down' | 'unknown',
            'kosdaq_trend': 'up' | 'down' | 'unknown',
            'regime': '강한상승' | '상승장_저변동' | '상승장_고변동' | '횡보장' | '완만하락' | '강한하락',
            'kospi_volatility': float,
            'kosdaq_volatility': float,
            'kospi_bullish': bool,
            'foreign_flow': str,
            'category_weights': dict,
            'bear_cash_weight': float,
            'kill_switch': bool,        # Phase 6: 시그널 송출 동결 신호
            'kill_reasons': List[str],   # Kill Switch 발동 사유
            'kospi_5d_return': float,
            'kospi_below_200ma': bool,
        }
    """
    result = {}
    df_kospi = None

    for name, ticker in [('kospi', 'KS11'), ('kosdaq', 'KQ11')]:
        df = _fetch_index(ticker, days=300)  # 200일 SMA 계산용
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

    # Kill Switch 점검
    kill_info = _check_kill_switch_conditions(df_kospi)
    result['kill_switch'] = kill_info['kill_switch']
    result['kill_reasons'] = kill_info['reasons']
    result['kospi_5d_return'] = kill_info['kospi_5d_return']
    result['kospi_below_200ma'] = kill_info['kospi_below_200ma']

    # ---------------------------------------------------------------
    # 5단계 레짐 판별
    # ---------------------------------------------------------------
    kospi_up = result.get('kospi_trend') == 'up'
    kosdaq_up = result.get('kosdaq_trend') == 'up'
    avg_vol = (result.get('kospi_volatility', 15) + result.get('kosdaq_volatility', 15)) / 2
    low_vol = avg_vol < 20

    both_up = kospi_up and kosdaq_up
    either_up = kospi_up or kosdaq_up
    both_down = not kospi_up and not kosdaq_up

    if kill_info['kill_switch']:
        regime = '강한하락'
    elif both_down and not low_vol:
        regime = '완만하락'
    elif both_up and low_vol and result['kospi_5d_return'] > 0.03:
        regime = '강한상승'
    elif either_up and low_vol:
        regime = '상승장_저변동'
    elif either_up and not low_vol:
        regime = '상승장_고변동'
    elif both_down and low_vol:
        regime = '횡보장'
    else:
        regime = '횡보장'

    # 외국인 대규모 이탈 + 둘 다 하락 → 강한하락 격상
    if result['foreign_flow'] == 'outflow' and both_down and not kill_info['kill_switch']:
        regime = '완만하락'

    result['regime'] = regime
    # 5단계 매핑 (기존 4단계 카테고리 가중치 재사용)
    weight_map = {
        '강한상승': REGIME_WEIGHTS['상승장_저변동'],
        '상승장_저변동': REGIME_WEIGHTS['상승장_저변동'],
        '상승장_고변동': REGIME_WEIGHTS['상승장_고변동'],
        '횡보장': REGIME_WEIGHTS['횡보장'],
        '완만하락': REGIME_WEIGHTS['하락장'],
        '강한하락': REGIME_WEIGHTS['하락장'],
    }
    result['category_weights'] = weight_map.get(regime, REGIME_WEIGHTS['횡보장'])
    result['bear_cash_weight'] = (
        BEAR_CASH_WEIGHT if regime in ('완만하락', '강한하락') else 0.0
    )

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
