"""
Z-Score 계산

멀티 윈도우 Z-Score (fast/main/slow) 산출.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from scripts.screeners.pairs_trading.config import ZSCORE_FAST, ZSCORE_MAIN, ZSCORE_SLOW


@dataclass
class ZScoreSnapshot:
    z_fast: float
    z_main: float
    z_slow: float
    spread_current: float
    spread_mean: float
    spread_std: float


def _rolling_zscore(spread: np.ndarray, window: int) -> np.ndarray:
    s = pd.Series(spread)
    mean = s.rolling(window=window, min_periods=window).mean()
    std = s.rolling(window=window, min_periods=window).std()
    z = (s - mean) / std.replace(0, np.nan)
    return z.values


def calc_zscore(residuals: np.ndarray) -> ZScoreSnapshot:
    """멀티 윈도우 Z-Score 스냅샷 계산."""
    z_fast = _rolling_zscore(residuals, ZSCORE_FAST)
    z_main = _rolling_zscore(residuals, ZSCORE_MAIN)
    z_slow = _rolling_zscore(residuals, ZSCORE_SLOW)

    spread = pd.Series(residuals)
    mean_main = spread.rolling(ZSCORE_MAIN).mean().iloc[-1]
    std_main = spread.rolling(ZSCORE_MAIN).std().iloc[-1]

    return ZScoreSnapshot(
        z_fast=_safe_last(z_fast),
        z_main=_safe_last(z_main),
        z_slow=_safe_last(z_slow),
        spread_current=residuals[-1] if len(residuals) > 0 else 0.0,
        spread_mean=mean_main if not np.isnan(mean_main) else 0.0,
        spread_std=std_main if not np.isnan(std_main) else 0.0,
    )


def _safe_last(arr: np.ndarray) -> float:
    if len(arr) == 0:
        return 0.0
    val = arr[-1]
    return float(val) if not np.isnan(val) else 0.0
