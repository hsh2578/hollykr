"""
테마주/작전주 자동 제외 필터
"""

import pandas as pd

from scripts.screeners.holly_kr.config import (
    THEME_TV_MCAP_RATIO,
    THEME_5D_RETURN_LIMIT,
    THEME_SECTOR_SURGE_COUNT,
    THEME_CONFIDENCE_DISCOUNT,
)


def is_theme_stock(df: pd.DataFrame, market_cap: float) -> bool:
    """
    테마주/작전주 여부 판별.

    Args:
        df: OHLCV DataFrame
        market_cap: 시가총액 (억원)
    """
    if len(df) < 5:
        return False

    # 5일 평균 거래대금 / 시총 > 5%
    if market_cap > 0:
        avg_tv = (df['Close'] * df['Volume']).tail(5).mean() / 1e8
        if avg_tv / market_cap > THEME_TV_MCAP_RATIO:
            return True

    # 5일 수익률 > 50%
    ret_5d = df['Close'].iloc[-1] / df['Close'].iloc[-6] - 1 if len(df) >= 6 else 0
    if ret_5d > THEME_5D_RETURN_LIMIT:
        return True

    return False


def check_sector_surge(signals: list, sector_returns: dict) -> list:
    """
    동일 섹터 5개+ 동시 급등 시 신뢰도 할인.

    Args:
        signals: Signal 리스트
        sector_returns: {섹터명: 당일 급등 종목 수}
    """
    for sig in signals:
        surge_count = sector_returns.get(sig.sector, 0)
        if surge_count >= THEME_SECTOR_SURGE_COUNT:
            sig.confidence *= THEME_CONFIDENCE_DISCOUNT
            sig.risk_warnings.append('테마섹터경보')
    return signals
