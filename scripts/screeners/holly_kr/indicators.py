"""
Holly AI 전용 지표 계산

기존 indicators.py 재사용 + 추가 지표 (RS Rating, 캔들 패턴 등).
"""

import numpy as np
import pandas as pd

from scripts.screeners.holly_kr.config import RS_WEIGHTS


# ============================================================================
# RS Rating (상대 강도)
# ============================================================================

def calc_rs_rating(close: pd.Series, benchmark_close: pd.Series) -> float:
    """
    RS Rating 계산 (0~100).
    3/6/9/12개월 수익률의 가중 평균을 전체 유니버스 대비 백분위로 환산.
    """
    periods = {'3month': 63, '6month': 126, '9month': 189, '12month': 252}
    score = 0.0

    for label, days in periods.items():
        weight = RS_WEIGHTS.get(label, 0.0)
        if len(close) <= days or len(benchmark_close) <= days:
            continue
        stock_ret = close.iloc[-1] / close.iloc[-days] - 1
        bench_ret = benchmark_close.iloc[-1] / benchmark_close.iloc[-days] - 1
        relative = stock_ret - bench_ret
        score += relative * weight

    return score


def calc_rs_rating_universe(price_matrix: pd.DataFrame,
                             benchmark_close: pd.Series) -> pd.Series:
    """유니버스 전체 RS Rating → 백분위(0~100) 환산"""
    scores = {}
    for ticker in price_matrix.columns:
        scores[ticker] = calc_rs_rating(price_matrix[ticker].dropna(), benchmark_close)
    raw = pd.Series(scores)
    # 백분위 환산
    return raw.rank(pct=True) * 100


# ============================================================================
# 캔들 패턴
# ============================================================================

def is_hammer(row: pd.Series, prev_row: pd.Series = None) -> bool:
    """해머 캔들 판별: 하단꼬리 >= 몸통×2, 상단꼬리 <= 몸통×0.3"""
    body = abs(row['Close'] - row['Open'])
    if body == 0:
        return False
    lower_wick = min(row['Close'], row['Open']) - row['Low']
    upper_wick = row['High'] - max(row['Close'], row['Open'])
    return lower_wick >= body * 2 and upper_wick <= body * 0.3


def is_engulfing(row: pd.Series, prev_row: pd.Series) -> bool:
    """장악형(Engulfing) 패턴: 전일 음봉 + 당일 양봉이 전일 레인지 감싸기"""
    prev_bearish = prev_row['Close'] < prev_row['Open']
    today_bullish = row['Close'] > row['Open']
    engulf = row['Low'] < prev_row['Low'] and row['Close'] > prev_row['High']
    return prev_bearish and today_bullish and engulf


# ============================================================================
# 보조 지표
# ============================================================================

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI (0~100)"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def close_position_ratio(row: pd.Series) -> float:
    """종가가 당일 레인지에서 어디에 위치하는지 (0.0~1.0)"""
    day_range = row['High'] - row['Low']
    if day_range == 0:
        return 0.5
    return (row['Close'] - row['Low']) / day_range


def range_ratio(df: pd.DataFrame, short: int = 5, long: int = 10) -> pd.Series:
    """단기/장기 레인지 비율"""
    range_short = (df['High'].rolling(short).max() - df['Low'].rolling(short).min()) / df['Close'].rolling(short).mean()
    range_long = (df['High'].rolling(long).max() - df['Low'].rolling(long).min()) / df['Close'].rolling(long).mean()
    return range_short / range_long.replace(0, np.nan)
