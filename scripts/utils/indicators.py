"""
기술적 지표 계산 유틸리티

모든 계산은 종가(Close 또는 종가) 기준.
한글 컬럼명(종가, 고가, 저가, 거래량) 우선, 영문 폴백.

사용법:
    from scripts.utils.indicators import calculate_sma, calculate_rsi
    sma_20 = calculate_sma(df, 20)
    rsi = calculate_rsi(df, 14)
"""

import numpy as np
import pandas as pd


def _get_col(data: pd.DataFrame, korean: str, english: str) -> pd.Series:
    """한글/영문 컬럼명 자동 감지"""
    if korean in data.columns:
        return data[korean]
    if english in data.columns:
        return data[english]
    raise KeyError(f"DataFrame에 '{korean}' 또는 '{english}' 컬럼이 필요합니다")


def _close(data: pd.DataFrame) -> pd.Series:
    return _get_col(data, '종가', 'Close')


def _high(data: pd.DataFrame) -> pd.Series:
    return _get_col(data, '고가', 'High')


def _low(data: pd.DataFrame) -> pd.Series:
    return _get_col(data, '저가', 'Low')


def _volume(data: pd.DataFrame) -> pd.Series:
    return _get_col(data, '거래량', 'Volume')


# ============================================================================
# 이동평균
# ============================================================================

def calculate_sma(data: pd.DataFrame, period: int) -> pd.Series:
    """단순이동평균선(SMA)"""
    return _close(data).rolling(window=period, min_periods=period).mean()


def calculate_ema(data: pd.DataFrame, period: int) -> pd.Series:
    """지수이동평균선(EMA)"""
    return _close(data).ewm(span=period, adjust=False).mean()


# ============================================================================
# 변동성
# ============================================================================

def calculate_atr(data: pd.DataFrame, period: int = 20) -> pd.Series:
    """ATR(Average True Range)"""
    high = _high(data)
    low = _low(data)
    close = _close(data)
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=period, min_periods=period).mean()


def calculate_volatility(data: pd.DataFrame, period: int = 20) -> float | None:
    """연환산 변동성(%)"""
    close = _close(data)
    if len(close) < period + 1:
        return None
    returns = close.pct_change().dropna().tail(period)
    return float(returns.std() * np.sqrt(252) * 100)


def calculate_bollinger_bands(
    data: pd.DataFrame, period: int = 20, std_multiplier: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """볼린저 밴드 → (상단, 중간, 하단)"""
    close = _close(data)
    middle = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std()
    upper = middle + (std * std_multiplier)
    lower = middle - (std * std_multiplier)
    return upper, middle, lower


# ============================================================================
# 모멘텀
# ============================================================================

def calculate_rsi(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI (0~100)"""
    close = _close(data)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_macd(
    data: pd.DataFrame,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD → (MACD선, 시그널선, 히스토그램)"""
    close = _close(data)
    fast_ema = close.ewm(span=fast_period, adjust=False).mean()
    slow_ema = close.ewm(span=slow_period, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ============================================================================
# 거래량
# ============================================================================

def calculate_volume_avg(data: pd.DataFrame, period: int = 20) -> pd.Series:
    """평균 거래량"""
    return _volume(data).rolling(window=period, min_periods=period).mean()


# ============================================================================
# 수익률/가격
# ============================================================================

def calculate_returns(data: pd.DataFrame, periods: list[int]) -> dict[int, float | None]:
    """기간별 수익률(%)"""
    close = _close(data)
    current_price = close.iloc[-1]
    results = {}
    for period in periods:
        if len(close) > period:
            past_price = close.iloc[-(period + 1)]
            results[period] = ((current_price - past_price) / past_price) * 100 if past_price > 0 else None
        else:
            results[period] = None
    return results


def calculate_52week_high_low(data: pd.DataFrame) -> tuple[float, float]:
    """52주(약 250거래일) 최고가/최저가"""
    recent = data.tail(250)
    return float(_high(recent).max()), float(_low(recent).min())
