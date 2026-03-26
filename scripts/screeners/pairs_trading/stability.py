"""
안정성 검증

롤링 ADF 테스트 + 반감기 계산으로 공적분 관계의 지속성 평가.
"""

from dataclasses import dataclass

import numpy as np
from statsmodels.tsa.stattools import adfuller

from scripts.screeners.pairs_trading.cointegration import CointegrationResult
from scripts.screeners.pairs_trading.config import (
    ROLLING_WINDOW, ADF_PVALUE, STABILITY_MIN_PCT,
    HALF_LIFE_MIN, HALF_LIFE_MAX,
)


@dataclass
class StabilityResult:
    coint: CointegrationResult
    stability_pct: float
    grade: str
    half_life: float


def _calc_half_life(residuals: np.ndarray) -> float:
    """OU 프로세스 반감기 계산."""
    z = residuals
    z_lag = z[:-1]
    dz = z[1:] - z[:-1]

    if len(z_lag) < 10:
        return float('inf')

    z_lag_mean = z_lag - z_lag.mean()
    denom = np.sum(z_lag_mean ** 2)
    if denom == 0:
        return float('inf')

    rho = np.sum(dz * z_lag_mean) / denom

    if rho >= 0:
        return float('inf')

    try:
        half_life = -np.log(2) / np.log(1 + rho)
    except (ValueError, RuntimeWarning):
        return float('inf')

    return max(half_life, 0.1)


def _rolling_adf(residuals: np.ndarray,
                 window: int = ROLLING_WINDOW,
                 p_threshold: float = ADF_PVALUE) -> float:
    """롤링 ADF 통과 비율."""
    n = len(residuals)
    if n < window + 20:
        try:
            result = adfuller(residuals, maxlag=20, autolag='AIC')
            return 100.0 if result[1] < p_threshold else 0.0
        except Exception:
            return 0.0

    step = 30
    pass_count = 0
    total = 0

    for start in range(0, n - window + 1, step):
        segment = residuals[start:start + window]
        try:
            result = adfuller(segment, maxlag=15, autolag='AIC')
            if result[1] < p_threshold:
                pass_count += 1
        except Exception:
            pass
        total += 1

    return (pass_count / total * 100) if total > 0 else 0.0


def check_stability(coint_results: list) -> list:
    """공적분 결과에 안정성 검증 적용."""
    print("\n[4/7] 안정성 검증 (롤링 ADF + 반감기)")
    print("=" * 50)

    results = []
    grade_counts = {'A': 0, 'B': 0, 'C': 0, 'F': 0}

    for coint in coint_results:
        half_life = _calc_half_life(coint.residuals)

        if not (HALF_LIFE_MIN <= half_life <= HALF_LIFE_MAX):
            grade_counts['F'] += 1
            continue

        stability_pct = _rolling_adf(coint.residuals)

        if stability_pct >= STABILITY_MIN_PCT and half_life <= 15:
            grade = 'A'
        elif stability_pct >= STABILITY_MIN_PCT:
            grade = 'B'
        else:
            grade = 'C'

        grade_counts[grade] += 1

        if grade == 'C':
            continue

        results.append(StabilityResult(
            coint=coint, stability_pct=stability_pct,
            grade=grade, half_life=half_life,
        ))

    print(f"  등급 분포: A={grade_counts['A']}, B={grade_counts['B']}, "
          f"C={grade_counts['C']}, 반감기탈락={grade_counts['F']}")
    print(f"  안정성 통과: {len(results)}쌍 (A+B)")
    return results
