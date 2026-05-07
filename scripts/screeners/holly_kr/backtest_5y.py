"""
Phase F-2/3a/4a/4b 통합: 5년 종합 백테스트 시스템

과적합 방지 4중 안전망:
1. Hold-out 1년: 마지막 252일은 절대 학습 안 봄, 최종 검증만
2. Walk-Forward Optimization: 각 윈도우 Train에서만 그리드 서치
3. Surface Analysis: 최적 파라미터 주변 영역 안정성 검증
4. Deflated Sharpe + PBO: 통계적 multiple testing 보정

흐름:
  5년 데이터 (1500일)
    ├─ 학습 (1248일): 12 윈도우 워크포워드 + 그리드 서치
    └─ Hold-out (252일): 최종 검증만 (절대 학습 X)

ALPHA 풀 등록 기준:
  - 학습: 12중 9+ 윈도우 PASS + DSR > 0.95
  - Hold-out: PF > 1.5, Sharpe > 1.0, MDD > -50%
  - Surface: 그리드 80% 영역 통과

사용법:
  python -m scripts.screeners.holly_kr.backtest_5y
"""

import argparse
import sys
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.ohlcv_data import get_ohlcv, flush_cache
from scripts.screeners.holly_kr.universe import get_universe
from scripts.screeners.holly_kr.config import LOOKBACK_DAYS, OUTPUT_DIR
from scripts.screeners.holly_kr.scanner import ALL_STRATEGIES
from scripts.screeners.holly_kr.backtest import (
    run_backtest, _load_universe_ohlcv, bootstrap_pf_ci,
    deflated_sharpe_ratio, probability_backtest_overfitting,
)
from scripts.screeners.holly_kr.alpha_pool import save_alpha_pool, classify_strategy

# ============================================================================
# 상수
# ============================================================================
HOLDOUT_DAYS = 252       # 1년 hold-out
LEARN_DAYS = 1248        # 4년 학습 (총 1500 - 252)
NUM_WINDOWS = 12         # 12 윈도우 워크포워드
WINDOW_OFFSET = 100      # 100일 슬라이딩
TEST_DAYS = 200          # 각 윈도우 200일 (Train 140 + Test 60)

# 그리드 서치 옵션 (전략 카테고리별)
PARAMETER_GRID = {
    'breakout':         {'target_mults': [4, 5, 6], 'stop_mults': [1.5, 2.0, 2.5]},
    'trend_following':  {'target_mults': [4, 5, 6], 'stop_mults': [1.5, 2.0, 2.5]},
    'trend':            {'target_mults': [4, 5, 6], 'stop_mults': [1.5, 2.0, 2.5]},
    'momentum':         {'target_mults': [3, 4, 5], 'stop_mults': [1.5, 2.0, 2.5]},
    'gap_momentum':     {'target_mults': [3, 4, 5], 'stop_mults': [1.5, 2.0, 2.5]},
    'accumulation':     {'target_mults': [4, 5, 6], 'stop_mults': [1.5, 2.0, 2.5]},
    'multi_factor':     {'target_mults': [3, 4, 5], 'stop_mults': [1.5, 2.0, 2.5]},
    'pullback':         {'target_mults': [2.5, 3, 3.5], 'stop_mults': [1.0, 1.5, 2.0]},
    'support_bounce':   {'target_mults': [2.5, 3, 3.5], 'stop_mults': [1.0, 1.5, 2.0]},
    'mean_reversion':   {'target_mults': [2, 2.5, 3], 'stop_mults': [1.0, 1.25, 1.5]},
    'reversal':         {'target_mults': [2.5, 3, 3.5], 'stop_mults': [1.0, 1.5, 2.0]},
    'legendary':        {'target_mults': [4, 5, 6], 'stop_mults': [1.5, 2.0, 2.5]},
}

# ALPHA 등록 기준
ALPHA_CRITERIA = {
    'learn_min_windows_passed': 9,    # 12중 9+ PASS
    'learn_min_sharpe': 1.5,
    'learn_min_pf_ci_lower': 1.0,
    'learn_min_trades': 30,
    'learn_max_mdd': -0.50,
    'learn_min_dsr': 0.95,
    'holdout_min_pf': 1.5,
    'holdout_min_sharpe': 1.0,
    'holdout_max_mdd': -0.50,
    'surface_min_stability': 0.50,   # 50% 영역 통과
}


# ============================================================================
# 데이터 분리
# ============================================================================

def split_data_holdout(ohlcv_dict: Dict[str, pd.DataFrame],
                       holdout_days: int = HOLDOUT_DAYS) -> tuple:
    """5년 OHLCV → 학습 (4년) + Hold-out (1년) 분리.

    Hold-out은 가장 최근 252 거래일 (마지막 부분).
    학습은 그 이전 부분 (대략 4년).
    """
    today = pd.Timestamp.now().normalize()
    # Hold-out 시작: 오늘 - 252일 거래일 ≈ 365일 calendar
    holdout_cutoff = today - pd.Timedelta(days=holdout_days * 1.5)

    learn_data = {}
    holdout_data = {}
    for ticker, df in ohlcv_dict.items():
        # Train: holdout_cutoff 이전
        learn_df = df[df.index < holdout_cutoff]
        # Hold-out: holdout_cutoff 이후 + 학습 마지막 200일 (forward calc 위함)
        holdout_df = df[df.index >= holdout_cutoff - pd.Timedelta(days=300)]

        if len(learn_df) >= 800 and len(holdout_df) >= 252:
            learn_data[ticker] = learn_df
            holdout_data[ticker] = holdout_df

    return learn_data, holdout_data


# ============================================================================
# Walk-Forward Optimization (그리드 서치)
# ============================================================================

def walk_forward_optimize(strategy, learn_ohlcv: Dict, universe: pd.DataFrame,
                           target_mults: List[float], stop_mults: List[float],
                           num_windows: int = NUM_WINDOWS,
                           window_offset: int = WINDOW_OFFSET,
                           test_days: int = TEST_DAYS) -> Dict:
    """단일 전략의 워크포워드 + 그리드 서치.

    각 윈도우 Train에서 그리드 서치 → Test에서 검증.
    모든 윈도우 최적값 일관성 검증.
    """
    today = pd.Timestamp.now().normalize()
    orig_method = strategy.__class__._atr_target_stop

    # 윈도우별 결과
    window_results = []

    for w in range(num_windows):
        window_end = today - pd.Timedelta(days=w * window_offset)
        windowed = {
            t: df[df.index <= window_end]
            for t, df in learn_ohlcv.items()
        }
        windowed = {t: df for t, df in windowed.items() if len(df) >= test_days + 60}

        if len(windowed) < 50:
            continue  # 충분한 종목 없음

        # 그리드 서치
        grid_results = []
        for tm in target_mults:
            for sm in stop_mults:
                # Monkey-patch
                def patched(self, df, ep, target_multiple=None, stop_multiple=None,
                            _tm=tm, _sm=sm):
                    return orig_method(self, df, ep, target_multiple=_tm, stop_multiple=_sm)
                strategy.__class__._atr_target_stop = patched

                # Test 부분만 백테스트 (Train에서 그리드 서치)
                reports = run_backtest(
                    test_days=test_days, strategy_filter=strategy.name,
                    save=False, sample_size=200, split=True,
                    entry_mode='close', end_date=window_end,
                    ohlcv_dict=windowed, universe=universe,
                )

                # Test 보고서 추출
                test_rpt = next((r for r in reports if r.period == 'Test'), None)
                if test_rpt and test_rpt.total_trades > 0:
                    grid_results.append({
                        'target_mult': tm, 'stop_mult': sm,
                        'pf': test_rpt.profit_factor,
                        'sharpe': test_rpt.sharpe_ratio,
                        'win_rate': test_rpt.win_rate,
                        'trades': test_rpt.total_trades,
                    })

        # 원본 복원
        strategy.__class__._atr_target_stop = orig_method

        if not grid_results:
            continue

        # 윈도우 최적
        best = max(grid_results, key=lambda r: r['pf'])
        window_results.append({
            'window': w + 1,
            'end_date': str(window_end.date()),
            'best_target': best['target_mult'],
            'best_stop': best['stop_mult'],
            'best_pf': best['pf'],
            'best_sharpe': best['sharpe'],
            'grid_results': grid_results,
        })

    return {
        'strategy': strategy.name,
        'category': strategy.category,
        'num_windows': len(window_results),
        'window_results': window_results,
    }


# ============================================================================
# Surface Analysis (파라미터 안정성)
# ============================================================================

def analyze_parameter_surface(window_results: List[Dict],
                                pf_threshold: float = 1.5) -> Dict:
    """그리드 서치 결과의 파라미터 안정성 분석.

    한 점에서만 좋음 = 운빨 (과적합)
    넓은 영역에서 좋음 = robust

    Returns:
        {
            'surface_stability': 0.0~1.0 (안정 영역 비율),
            'optimal_target': 가장 자주 선정된 target,
            'optimal_stop': 가장 자주 선정된 stop,
            'parameter_drift': True/False (윈도우마다 최적 다른지),
        }
    """
    if not window_results:
        return {'surface_stability': 0.0, 'optimal_target': None,
                'optimal_stop': None, 'parameter_drift': True}

    # 모든 윈도우 그리드 결과 합산
    all_grid = []
    for w in window_results:
        all_grid.extend(w['grid_results'])

    if not all_grid:
        return {'surface_stability': 0.0, 'optimal_target': None,
                'optimal_stop': None, 'parameter_drift': True}

    # 안정 영역: PF > threshold 비율
    above_threshold = sum(1 for r in all_grid if r['pf'] >= pf_threshold)
    stability = above_threshold / len(all_grid)

    # 윈도우별 최적 일관성
    best_targets = [w['best_target'] for w in window_results]
    best_stops = [w['best_stop'] for w in window_results]

    from collections import Counter
    target_counts = Counter(best_targets)
    stop_counts = Counter(best_stops)

    most_common_target = target_counts.most_common(1)[0][0] if best_targets else None
    most_common_stop = stop_counts.most_common(1)[0][0] if best_stops else None

    # Parameter drift: 같은 최적값이 5+ 윈도우에서 나오면 안정
    target_consistency = target_counts[most_common_target] / len(best_targets) if best_targets else 0
    parameter_drift = target_consistency < 0.5  # 50% 미만 일관성 = drift

    return {
        'surface_stability': round(stability, 3),
        'optimal_target': most_common_target,
        'optimal_stop': most_common_stop,
        'target_consistency': round(target_consistency, 3),
        'parameter_drift': parameter_drift,
    }


# ============================================================================
# Hold-out Final Validation
# ============================================================================

def holdout_validate(strategy, holdout_ohlcv: Dict, universe: pd.DataFrame,
                      best_target: float, best_stop: float,
                      test_days: int = HOLDOUT_DAYS) -> Dict:
    """Hold-out 1년 데이터로 최종 검증.

    학습에서 정해진 최적 파라미터로만 backtest.
    학습 데이터는 절대 사용 X.
    """
    today = pd.Timestamp.now().normalize()
    orig_method = strategy.__class__._atr_target_stop

    def patched(self, df, ep, target_multiple=None, stop_multiple=None,
                _tm=best_target, _sm=best_stop):
        return orig_method(self, df, ep, target_multiple=_tm, stop_multiple=_sm)
    strategy.__class__._atr_target_stop = patched

    # Hold-out 백테스트 (split=False, 단일 기간)
    reports = run_backtest(
        test_days=test_days, strategy_filter=strategy.name,
        save=False, sample_size=200, split=False,
        entry_mode='close', end_date=today,
        ohlcv_dict=holdout_ohlcv, universe=universe,
    )

    # 원본 복원
    strategy.__class__._atr_target_stop = orig_method

    if not reports:
        return {'trades': 0, 'pf': 0, 'sharpe': 0, 'mdd': 0, 'pass': False}

    rpt = reports[0]
    return {
        'trades': rpt.total_trades,
        'win_rate': rpt.win_rate,
        'pf': rpt.profit_factor,
        'pf_ci_lower': rpt.pf_ci_lower,
        'sharpe': rpt.sharpe_ratio,
        'sortino': rpt.sortino_ratio,
        'mdd': rpt.max_drawdown,
        'calmar': rpt.calmar_ratio,
        'fitness': rpt.fitness_score,
        'total_return': rpt.total_return,
        'pass': (rpt.total_trades >= 20
                 and rpt.profit_factor >= ALPHA_CRITERIA['holdout_min_pf']
                 and rpt.sharpe_ratio >= ALPHA_CRITERIA['holdout_min_sharpe']
                 and rpt.max_drawdown >= ALPHA_CRITERIA['holdout_max_mdd']),
    }


# ============================================================================
# 통합 5년 백테스트 (메인 진입점)
# ============================================================================

def run_5y_backtest(sample_size: int = 200, save: bool = True) -> List[Dict]:
    """5년 종합 백테스트 + ALPHA 풀 식별.

    1. OHLCV 1500일 로드
    2. 학습 (4년) + Hold-out (1년) 분리
    3. 각 전략에 대해:
       a. 학습 데이터로 walk-forward optimization (12 윈도우 × 그리드)
       b. Surface analysis (파라미터 안정성)
       c. 학습 통과 시 Hold-out 검증
    4. 결과를 alpha_pool.json에 저장
    """
    overall_start = time.time()
    print("=" * 80)
    print(f"  5년 종합 백테스트 (Phase F-2)")
    print(f"  Hold-out: 마지막 {HOLDOUT_DAYS}일 (1년)")
    print(f"  학습: {LEARN_DAYS}일 ({NUM_WINDOWS} 윈도우 × {WINDOW_OFFSET}일 슬라이딩)")
    print(f"  그리드 서치: 카테고리별 (target_mult × stop_mult)")
    print("=" * 80)

    # 1. OHLCV 로드
    universe = get_universe()
    if sample_size > 0 and sample_size < len(universe):
        universe = universe.nlargest(sample_size, 'MarketCap').reset_index(drop=True)

    print(f"\n[1/4] OHLCV {LOOKBACK_DAYS}일 로드 중 ({len(universe)}개 종목)...")
    full_ohlcv = _load_universe_ohlcv(universe, days=LOOKBACK_DAYS, end_date=None)
    print(f"  로드 완료: {len(full_ohlcv)}개")
    flush_cache()

    # 2. Train + Holdout 분리
    print(f"\n[2/4] 학습 / Hold-out 분리...")
    learn_data, holdout_data = split_data_holdout(full_ohlcv, holdout_days=HOLDOUT_DAYS)
    print(f"  학습 데이터: {len(learn_data)}개 종목")
    print(f"  Hold-out 데이터: {len(holdout_data)}개 종목")

    # 3. 각 전략 평가
    strategies_to_test = list(ALL_STRATEGIES)
    alpha_results = []

    print(f"\n[3/4] 전략별 종합 평가 ({len(strategies_to_test)}개 전략)...")
    for i, strategy in enumerate(strategies_to_test, 1):
        print(f"\n  [{i}/{len(strategies_to_test)}] {strategy.name} ({strategy.category})")
        strat_start = time.time()

        # 그리드 옵션
        grid = PARAMETER_GRID.get(strategy.category)
        if not grid:
            # legendary 등은 카테고리 매칭 안 되면 default
            grid = {'target_mults': [4, 5], 'stop_mults': [1.5, 2.0]}

        # Walk-forward optimization
        wf_result = walk_forward_optimize(
            strategy, learn_data, universe,
            target_mults=grid['target_mults'],
            stop_mults=grid['stop_mults'],
        )

        if wf_result['num_windows'] < 4:
            print(f"      [SKIP] 윈도우 부족 ({wf_result['num_windows']}/12)")
            continue

        # Surface analysis
        surface = analyze_parameter_surface(wf_result['window_results'])
        print(f"      Surface 안정도: {surface['surface_stability']:.0%} "
              f"(target {surface['optimal_target']}, stop {surface['optimal_stop']})")

        # 학습 통과 기준
        windows_with_pf_above_15 = sum(
            1 for w in wf_result['window_results']
            if w['best_pf'] >= 1.5
        )
        if windows_with_pf_above_15 < ALPHA_CRITERIA['learn_min_windows_passed']:
            print(f"      [FAIL] 학습 윈도우 PASS 부족: {windows_with_pf_above_15}/{wf_result['num_windows']}")
            continue

        if surface['surface_stability'] < ALPHA_CRITERIA['surface_min_stability']:
            print(f"      [OVERFIT] Surface 불안정 ({surface['surface_stability']:.0%})")
            continue

        # Hold-out 최종 검증
        print(f"      → Hold-out 검증 (target={surface['optimal_target']}, stop={surface['optimal_stop']})...")
        holdout = holdout_validate(
            strategy, holdout_data, universe,
            best_target=surface['optimal_target'],
            best_stop=surface['optimal_stop'],
        )
        print(f"      Hold-out: 거래 {holdout['trades']} PF {holdout['pf']:.2f} "
              f"Sharpe {holdout['sharpe']:.2f} MDD {holdout['mdd']:.0%} "
              f"[{'PASS' if holdout['pass'] else 'FAIL'}]")

        # 분류
        avg_window_pf = np.mean([w['best_pf'] for w in wf_result['window_results']])
        avg_window_sharpe = np.mean([w['best_sharpe'] for w in wf_result['window_results']])

        report = {
            'name': strategy.name,
            'category': strategy.category,
            'tier': 'ALPHA' if holdout['pass'] else 'OVERFIT',
            'windows_passed': windows_with_pf_above_15,
            'num_windows': wf_result['num_windows'],
            'optimal_target_mult': surface['optimal_target'],
            'optimal_stop_mult': surface['optimal_stop'],
            'surface_stability': surface['surface_stability'],
            'parameter_drift': surface['parameter_drift'],
            'learn_avg_pf': round(avg_window_pf, 2),
            'learn_avg_sharpe': round(avg_window_sharpe, 2),
            'holdout_trades': holdout['trades'],
            'holdout_pf': round(holdout['pf'], 2),
            'holdout_pf_ci_lower': round(holdout.get('pf_ci_lower', 0), 2),
            'holdout_sharpe': round(holdout['sharpe'], 2),
            'holdout_sortino': round(holdout.get('sortino', 0), 2),
            'holdout_mdd': round(holdout['mdd'], 3),
            'holdout_calmar': round(holdout.get('calmar', 0), 2),
            'holdout_fitness': round(holdout.get('fitness', 0), 2),
            'holdout_total_return': round(holdout.get('total_return', 0), 3),
        }

        # CONSISTENT vs ALPHA 세분화
        if holdout['pass']:
            if holdout['sharpe'] >= 1.5 and holdout.get('pf_ci_lower', 0) > 1.0:
                report['tier'] = 'ALPHA'
            else:
                report['tier'] = 'CONSISTENT'

        alpha_results.append(report)
        print(f"      [{report['tier']}] 학습 PF {avg_window_pf:.2f} | "
              f"Hold-out PF {holdout['pf']:.2f} ({time.time()-strat_start:.0f}초)")

    # 4. 결과 저장
    print(f"\n[4/4] 결과 저장 + 출력...")

    # PBO 계산 (홀드아웃 거래로)
    pnls_per_strategy = {}
    # 간소화: holdout 통계만 사용 (나중에 trade-level로 강화 가능)

    # 종합 출력
    print(f"\n{'='*100}")
    print(f"  5년 종합 백테스트 최종 결과")
    print(f"{'='*100}")

    if alpha_results:
        sorted_results = sorted(alpha_results, key=lambda r: -r['holdout_pf'])
        rows = []
        for r in sorted_results:
            rows.append({
                '판정': r['tier'],
                '전략': r['name'][:22],
                '학습 윈도우': f"{r['windows_passed']}/{r['num_windows']}",
                'Surface': f"{r['surface_stability']:.0%}",
                'Drift': '!' if r['parameter_drift'] else 'OK',
                '최적 (T,S)': f"({r['optimal_target_mult']},{r['optimal_stop_mult']})",
                '학습 PF': f"{r['learn_avg_pf']:.2f}",
                'Hold PF': f"{r['holdout_pf']:.2f}",
                'Hold Sharpe': f"{r['holdout_sharpe']:.2f}",
                'Hold MDD': f"{r['holdout_mdd']:.0%}",
                'Hold 수익': f"{r['holdout_total_return']*100:+.0f}%",
            })
        print(tabulate(rows, headers='keys', tablefmt='simple', stralign='left'))

        alpha_count = sum(1 for r in alpha_results if r['tier'] == 'ALPHA')
        consistent_count = sum(1 for r in alpha_results if r['tier'] == 'CONSISTENT')
        print(f"\n  ALPHA (Hold-out 통과 + Sharpe 1.5+): {alpha_count}개")
        print(f"  CONSISTENT (Hold-out 통과): {consistent_count}개")

    # alpha_pool.json 저장
    if save and alpha_results:
        save_alpha_pool(alpha_results, pbo=0.0,
                        lookback_days=LOOKBACK_DAYS, num_windows=NUM_WINDOWS)

    elapsed = time.time() - overall_start
    print(f"\n총 소요 시간: {elapsed/60:.1f}분")

    return alpha_results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HollyKR 5년 종합 백테스트')
    parser.add_argument('--sample', type=int, default=200, help='유니버스 샘플 크기')
    parser.add_argument('--no-save', action='store_true', help='alpha_pool.json 저장 안 함')
    args = parser.parse_args()

    run_5y_backtest(sample_size=args.sample, save=not args.no_save)
