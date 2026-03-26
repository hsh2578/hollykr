"""
Engle-Granger 공적분 검정

같은 WICS 섹터 내 종목 쌍에 대해 OLS + ADF 검정 수행.
"""

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller

from scripts.screeners.pairs_trading.config import ADF_PVALUE, BETA_MIN, BETA_MAX


@dataclass
class CointegrationResult:
    stock_a: str
    stock_b: str
    name_a: str = ''
    name_b: str = ''
    sector: str = ''
    alpha: float = 0.0
    beta: float = 0.0
    adf_stat: float = 0.0
    adf_pvalue: float = 1.0
    residuals: np.ndarray = field(default_factory=lambda: np.array([]))
    log_prices_a: np.ndarray = field(default_factory=lambda: np.array([]))
    log_prices_b: np.ndarray = field(default_factory=lambda: np.array([]))


def _test_pair(log_a: pd.Series, log_b: pd.Series) -> tuple:
    """단일 쌍 OLS + ADF 테스트."""
    X = sm.add_constant(log_b.values)
    y = log_a.values

    try:
        model = sm.OLS(y, X).fit()
    except Exception:
        return None

    alpha = model.params[0]
    beta = model.params[1]

    if not (BETA_MIN <= abs(beta) <= BETA_MAX):
        return None

    residuals = model.resid

    try:
        adf_result = adfuller(residuals, maxlag=20, autolag='AIC')
        adf_stat = adf_result[0]
        adf_pvalue = adf_result[1]
    except Exception:
        return None

    return alpha, beta, adf_stat, adf_pvalue, residuals


def run_cointegration(price_matrix: pd.DataFrame,
                      universe: pd.DataFrame) -> list:
    """같은 섹터 내 모든 종목 쌍에 대해 공적분 검정."""
    print("\n[3/7] 공적분 검정 (Engle-Granger)")
    print("=" * 50)

    code_to_name = dict(zip(universe['Code'], universe['Name']))
    code_to_sector = dict(zip(universe['Code'], universe['WICS_Sector']))
    available = set(price_matrix.columns)

    sector_groups = {}
    for code in available:
        sector = code_to_sector.get(code, '')
        if sector:
            sector_groups.setdefault(sector, []).append(code)

    total_pairs = 0
    tested = 0
    results = []
    log_prices = np.log(price_matrix)

    for sector, codes in sector_groups.items():
        if len(codes) < 2:
            continue
        pairs = list(combinations(sorted(codes), 2))
        total_pairs += len(pairs)

        for code_a, code_b in pairs:
            tested += 1
            result = _test_pair(log_prices[code_a], log_prices[code_b])
            if result is None:
                continue

            alpha, beta, adf_stat, adf_pvalue, residuals = result

            if adf_pvalue < ADF_PVALUE:
                results.append(CointegrationResult(
                    stock_a=code_a, stock_b=code_b,
                    name_a=code_to_name.get(code_a, ''),
                    name_b=code_to_name.get(code_b, ''),
                    sector=sector, alpha=alpha, beta=beta,
                    adf_stat=adf_stat, adf_pvalue=adf_pvalue,
                    residuals=residuals,
                    log_prices_a=log_prices[code_a].values,
                    log_prices_b=log_prices[code_b].values,
                ))

        if tested % 500 == 0:
            print(f"  진행: {tested}/{total_pairs} 쌍 검정, {len(results)}개 통과")

    print(f"\n  총 {total_pairs}쌍 중 {len(results)}쌍 공적분 통과 "
          f"(p < {ADF_PVALUE})")
    return results
