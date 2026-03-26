"""
시그널 생성 (메인 오케스트레이터)

전체 파이프라인: 유니버스 → 가격 → 공적분 → 안정성 → Z-Score → 시그널.
"""

from dataclasses import dataclass, field

from scripts.screeners.pairs_trading.universe import get_universe
from scripts.screeners.pairs_trading.data_prep import build_price_matrix
from scripts.screeners.pairs_trading.cointegration import run_cointegration
from scripts.screeners.pairs_trading.stability import check_stability, StabilityResult
from scripts.screeners.pairs_trading.zscore import calc_zscore, ZScoreSnapshot
from scripts.screeners.pairs_trading.config import (
    ENTRY_STRONG_Z, WATCH_Z, EXIT_Z, STOP_Z, ROUND_TRIP_COST,
)


@dataclass
class PairSignal:
    stock_a: str
    stock_b: str
    name_a: str
    name_b: str
    sector: str
    beta: float
    adf_pvalue: float
    grade: str
    stability_pct: float
    half_life: float
    zscore: ZScoreSnapshot
    signal: str
    direction: str
    expected_return: float
    risk_warnings: list = field(default_factory=list)


def _classify_signal(z: ZScoreSnapshot) -> tuple:
    abs_main = abs(z.z_main)
    abs_fast = abs(z.z_fast)
    abs_slow = abs(z.z_slow)

    if abs_main > STOP_Z or abs_slow > STOP_Z:
        direction = 'LONG_B' if z.z_main > 0 else 'LONG_A'
        return 'STOP', direction

    if abs_main >= ENTRY_STRONG_Z and abs_fast >= ENTRY_STRONG_Z and abs_slow < 3.5:
        direction = 'LONG_B' if z.z_main > 0 else 'LONG_A'
        return 'ENTRY_STRONG', direction

    if abs_main >= WATCH_Z:
        direction = 'LONG_B' if z.z_main > 0 else 'LONG_A'
        return 'WATCH', direction

    if abs_main < EXIT_Z:
        return 'EXIT', 'NEUTRAL'

    return 'HOLD', 'NEUTRAL'


def _calc_expected_return(z: ZScoreSnapshot, half_life: float) -> float:
    if z.spread_std == 0:
        return 0.0
    expected_pct = abs(z.z_main) * z.spread_std
    if z.spread_mean != 0:
        expected_pct = expected_pct / abs(z.spread_mean) * 100
    else:
        expected_pct = 0.0
    return expected_pct


def _tag_risks(sig: PairSignal) -> list:
    warnings = []
    if sig.grade == 'B':
        warnings.append('안정성B등급')
    if sig.half_life > 20:
        warnings.append(f'반감기{sig.half_life:.0f}일(장기)')
    if abs(sig.zscore.z_slow) > 3.0:
        warnings.append('장기Z-Score높음')
    if sig.adf_pvalue > 0.03:
        warnings.append('ADF경계선')
    if abs(sig.beta) > 2.0:
        warnings.append('고베타')
    return warnings


def screen_pairs() -> list:
    """페어 트레이딩 전체 파이프라인 실행."""
    universe = get_universe()
    if len(universe) < 2:
        print("유니버스 종목 부족")
        return []

    price_matrix = build_price_matrix(universe)

    coint_results = run_cointegration(price_matrix, universe)
    if not coint_results:
        print("공적분 통과 쌍 없음")
        return []

    stable_results = check_stability(coint_results)
    if not stable_results:
        print("안정성 통과 쌍 없음")
        return []

    print("\n[5/7] Z-Score 계산")
    print("=" * 50)

    signals = []
    cost_filtered = 0

    for sr in stable_results:
        coint = sr.coint
        zscore = calc_zscore(coint.residuals)
        signal, direction = _classify_signal(zscore)
        expected_return = _calc_expected_return(zscore, sr.half_life)

        min_return = ROUND_TRIP_COST * 100 * 2
        if signal in ('ENTRY_STRONG', 'WATCH') and expected_return < min_return:
            cost_filtered += 1
            continue

        pair_signal = PairSignal(
            stock_a=coint.stock_a, stock_b=coint.stock_b,
            name_a=coint.name_a, name_b=coint.name_b,
            sector=coint.sector, beta=coint.beta,
            adf_pvalue=coint.adf_pvalue, grade=sr.grade,
            stability_pct=sr.stability_pct, half_life=sr.half_life,
            zscore=zscore, signal=signal, direction=direction,
            expected_return=expected_return,
        )
        pair_signal.risk_warnings = _tag_risks(pair_signal)
        signals.append(pair_signal)

    if cost_filtered:
        print(f"  비용 필터 제외: {cost_filtered}쌍")

    signal_priority = {
        'ENTRY_STRONG': 0, 'WATCH': 1, 'STOP': 2, 'EXIT': 3, 'HOLD': 4
    }
    signals.sort(key=lambda s: (signal_priority.get(s.signal, 99),
                                -abs(s.zscore.z_main)))

    print(f"\n[6/7] 시그널 생성 완료")
    print("=" * 50)
    signal_counts = {}
    for s in signals:
        signal_counts[s.signal] = signal_counts.get(s.signal, 0) + 1
    for sig_type, count in sorted(signal_counts.items()):
        print(f"  {sig_type}: {count}쌍")
    print(f"  총 {len(signals)}쌍")

    return signals
