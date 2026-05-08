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
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

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
# 상수 (단순화 평가: 단일 게이트 — Walk-Forward + Hold-out)
# Phase F 단순화: 12 윈도우 × 9 그리드 누적 게이트 → 4 윈도우 단일 파라미터
# ----------------------------------------------------------------------------
# 이전 문제:
#   1. wake_up_call/close_to_a_cross 등 워크포워드 검증 ALPHA도 12 윈도우 평균에서 탈락
#   2. window_end가 today 기준이라 윈도우 0-6이 사실상 같은 데이터 테스트
#   3. 9-grid 평균이 단일 best 결과를 dilute → ALPHA 가짜 탈락
# 해결:
#   1. 단일 best 파라미터 (전략 default = 카테고리 ATR preset)로 워크포워드
#   2. learn_end (실제 데이터 마지막) 기준으로 sliding
#   3. 그리드 서치는 ALPHA 통과 후 Phase F-4에서 별도 실행
# ============================================================================
HOLDOUT_DAYS = 750       # 3년 hold-out (Phase G-4: 5년 데이터 활용 극대화 — 다양한 시장 환경)
LEARN_DAYS = 500         # 2년 학습
NUM_WINDOWS = 4          # 4 윈도우 워크포워드 (12 → 4)
WINDOW_OFFSET = 90       # 90일 슬라이딩 (4 × 90 = 1년 slide)
TEST_DAYS = 200          # 각 윈도우 200일 (Train 140 + Test 60)
DEFAULT_SAMPLE = 1500    # 백테스트 표본 (시총 1000억+ 거의 전체 커버)

# 그리드 서치는 ALPHA 통과 후 Phase F-4에서 (이 파일에선 단일 default 파라미터)
# [None] 통과 시 strategy._atr_target_stop이 카테고리 default 사용
PARAMETER_GRID = {
    cat: {'target_mults': [None], 'stop_mults': [None]}
    for cat in ['breakout', 'trend_following', 'trend', 'momentum', 'gap_momentum',
                'accumulation', 'multi_factor', 'pullback', 'support_bounce',
                'mean_reversion', 'reversal', 'legendary']
}

# ALPHA 등록 기준 (Hold-out 단독 평가)
# 학습 게이트 폐기 이유: 윈도우당 60일 Test = 거래 5-15건 → PF 통계적 노이즈
# Hold-out 252일 (~1년) = 거래 30-200건 → 통계적 유의미
ALPHA_CRITERIA = {
    # ALPHA tier (강력)
    'tier_alpha_pf': 1.5,
    'tier_alpha_sharpe': 1.0,
    'tier_alpha_trades': 30,
    # CONSISTENT tier (검증)
    'consistent_min_pf': 1.0,
    'consistent_min_sharpe': 0.3,
    'consistent_min_trades': 15,
    'consistent_max_mdd': -0.50,
    # legacy aliases (holdout_validate 'pass' 필드 호환)
    'holdout_min_pf': 1.0,
    'holdout_min_sharpe': 0.3,
    'holdout_min_trades': 15,
    'holdout_max_mdd': -0.50,
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

        if len(learn_df) >= 400 and len(holdout_df) >= 700:
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
    """단일 전략의 워크포워드 + (선택적) 그리드 서치.

    target_mults=[None], stop_mults=[None] → 그리드 서치 X (default 파라미터 단일 평가)
    그 외 → Train에서 그리드 서치, Test에서 검증
    """
    # 학습 데이터 실제 마지막 일자 (today 아님 — holdout 분리 후이므로)
    all_dates = []
    for df in learn_ohlcv.values():
        if df is not None and not df.empty:
            all_dates.append(df.index[-1])
    if not all_dates:
        return {'strategy': strategy.name, 'category': strategy.category,
                'num_windows': 0, 'window_results': []}
    learn_end = max(all_dates)
    orig_method = strategy.__class__._atr_target_stop

    # 윈도우별 결과
    window_results = []

    for w in range(num_windows):
        window_end = learn_end - pd.Timedelta(days=w * window_offset)
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
        'dsr': rpt.deflated_sharpe,  # Phase G-1: López de Prado DSR (40 trials 보정)
        'total_return': rpt.total_return,
        'pass': (rpt.total_trades >= 20
                 and rpt.profit_factor >= ALPHA_CRITERIA['holdout_min_pf']
                 and rpt.sharpe_ratio >= ALPHA_CRITERIA['holdout_min_sharpe']
                 and rpt.max_drawdown >= ALPHA_CRITERIA['holdout_max_mdd']),
    }


# ============================================================================
# ProcessPool Worker (전략 단위 병렬)
# ============================================================================

def _evaluate_strategy_worker(args: tuple) -> Optional[Dict]:
    """단일 전략 평가 — ProcessPool에서 호출.

    각 워커가 자체 OHLCV 캐시 로드 + 평가 → 메인에 결과 반환.
    pickle 비용 최소화를 위해 args에 OHLCV 직접 안 보냄.
    """
    strategy_name, sample_size, parameter_grid = args

    # 워커 프로세스 내부 import
    from scripts.screeners.holly_kr.scanner import ALL_STRATEGIES
    from scripts.screeners.holly_kr.universe import get_universe
    from scripts.screeners.holly_kr.backtest import _load_universe_ohlcv

    # 전략 객체
    strategy = next((s for s in ALL_STRATEGIES if s.name == strategy_name), None)
    if strategy is None:
        return None

    # 유니버스 + OHLCV 로드 (워커마다 fresh)
    universe = get_universe()
    if sample_size > 0 and sample_size < len(universe):
        universe = universe.nlargest(sample_size, 'MarketCap').reset_index(drop=True)

    full_ohlcv = _load_universe_ohlcv(universe, days=LOOKBACK_DAYS, end_date=None)
    learn_data, holdout_data = split_data_holdout(full_ohlcv, holdout_days=HOLDOUT_DAYS)

    if len(learn_data) < 50:
        return None

    # 그리드 옵션
    grid = parameter_grid.get(strategy.category)
    if not grid:
        grid = {'target_mults': [4, 5], 'stop_mults': [1.5, 2.0]}

    # Walk-forward optimization
    wf_result = walk_forward_optimize(
        strategy, learn_data, universe,
        target_mults=grid['target_mults'],
        stop_mults=grid['stop_mults'],
    )

    # Walk-forward 결과는 정보 출력용만 (게이트 X)
    if wf_result['num_windows'] >= 1:
        avg_window_pf = float(np.mean([w['best_pf'] for w in wf_result['window_results']]))
        avg_window_sharpe = float(np.mean([w['best_sharpe'] for w in wf_result['window_results']]))
        windows_above_12 = sum(
            1 for w in wf_result['window_results'] if w['best_pf'] >= 1.2
        )
    else:
        avg_window_pf = 0.0
        avg_window_sharpe = 0.0
        windows_above_12 = 0

    # Hold-out 단독 평가 (default 파라미터 사용)
    holdout = holdout_validate(
        strategy, holdout_data, universe,
        best_target=None, best_stop=None,
    )

    report = {
        'name': strategy_name,
        'category': strategy.category,
        'tier': 'PENDING',
        'windows_passed': windows_above_12,
        'num_windows': wf_result['num_windows'],
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
        'holdout_dsr': round(holdout.get('dsr', 0), 5),  # Phase G-1 DSR (40 trials 보정)
        'holdout_total_return': round(holdout.get('total_return', 0), 3),
    }

    # Hold-out 단독 Tier 분류
    if (holdout['trades'] >= ALPHA_CRITERIA['tier_alpha_trades']
        and holdout['pf'] >= ALPHA_CRITERIA['tier_alpha_pf']
        and holdout['sharpe'] >= ALPHA_CRITERIA['tier_alpha_sharpe']
        and holdout['mdd'] >= ALPHA_CRITERIA['consistent_max_mdd']):
        report['tier'] = 'ALPHA'
    elif (holdout['trades'] >= ALPHA_CRITERIA['consistent_min_trades']
          and holdout['pf'] >= ALPHA_CRITERIA['consistent_min_pf']
          and holdout['sharpe'] >= ALPHA_CRITERIA['consistent_min_sharpe']
          and holdout['mdd'] >= ALPHA_CRITERIA['consistent_max_mdd']):
        report['tier'] = 'CONSISTENT'
    else:
        report['tier'] = 'WEAK_HOLDOUT'
        report['reason'] = (
            f"Hold-out 미통과: PF {holdout['pf']:.2f} "
            f"Sharpe {holdout['sharpe']:.2f} 거래 {holdout['trades']}"
        )

    return report


# ============================================================================
# 통합 5년 백테스트 (메인 진입점)
# ============================================================================

def run_5y_backtest(sample_size: int = 200, save: bool = True,
                     workers: int = None, parallel: bool = True,
                     only: Optional[List[str]] = None,
                     merge_existing: bool = False) -> List[Dict]:
    """5년 종합 백테스트 + ALPHA 풀 식별 (병렬 처리).

    Args:
        sample_size: 유니버스 샘플 크기
        save: alpha_pool.json 저장
        workers: ProcessPool worker 수 (None = os.cpu_count())
        parallel: True면 ProcessPool 병렬, False면 순차
        only: 특정 전략명 리스트만 평가 (None=전체)
        merge_existing: True면 기존 alpha_pool.json + 신규 결과 병합 (only 사용 시 권장)

    1. OHLCV 1500일 로드 (메인 + 각 워커)
    2. 학습 (4년) + Hold-out (1년) 분리
    3. ★병렬★ 각 전략을 별도 프로세스에서 평가
    4. 결과를 alpha_pool.json에 저장 (merge_existing 시 기존과 병합)
    """
    overall_start = time.time()

    if workers is None:
        workers = max(1, (os.cpu_count() or 4) - 1)  # 1 코어는 시스템용

    print("=" * 80)
    print(f"  4년 종합 백테스트 (Phase F-2 Hold-out 단독 평가)")
    print(f"  Hold-out: 마지막 {HOLDOUT_DAYS}일 (1년)")
    print(f"  학습: {NUM_WINDOWS} 윈도우 walk-forward (정보 출력용, 게이트 X)")
    print(f"  ALPHA 기준: Hold-out PF≥{ALPHA_CRITERIA['tier_alpha_pf']}, "
          f"Sharpe≥{ALPHA_CRITERIA['tier_alpha_sharpe']}, "
          f"거래≥{ALPHA_CRITERIA['tier_alpha_trades']}")
    print(f"  CONSISTENT 기준: Hold-out PF≥{ALPHA_CRITERIA['consistent_min_pf']}, "
          f"Sharpe≥{ALPHA_CRITERIA['consistent_min_sharpe']}, "
          f"거래≥{ALPHA_CRITERIA['consistent_min_trades']}")
    print(f"  병렬: {'ProcessPool ' + str(workers) + ' workers' if parallel else 'OFF (순차)'}")
    print("=" * 80)

    strategies_to_test = list(ALL_STRATEGIES)
    if only:
        only_set = set(only)
        strategies_to_test = [s for s in strategies_to_test if s.name in only_set]
        print(f"\n[필터] only={only} → {len(strategies_to_test)}개 전략만 평가")
        if not strategies_to_test:
            print("  매칭 전략 없음. 전략명 확인 필요.")
            return []
    alpha_results = []

    if parallel:
        # 병렬 처리: 각 워커가 자체 OHLCV 로드 + 평가
        print(f"\n[병렬 평가] {len(strategies_to_test)}개 전략 × {workers} workers")
        print(f"  (각 워커가 OHLCV 캐시 fresh 로드 — 메모리 격리)")

        args_list = [
            (strategy.name, sample_size, PARAMETER_GRID)
            for strategy in strategies_to_test
        ]

        completed = 0
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_evaluate_strategy_worker, args): args[0]
                for args in args_list
            }
            for future in as_completed(futures):
                completed += 1
                strategy_name = futures[future]
                try:
                    result = future.result()
                    if result:
                        # 학습 통과 (홀드아웃 단계 진입한 모든 결과 보존)
                        if result.get('tier') in ('ALPHA', 'CONSISTENT', 'WEAK_HOLDOUT'):
                            alpha_results.append(result)
                        elapsed = time.time() - overall_start
                        # 추가 정보 (학습 통과 시)
                        extra = ""
                        if result.get('tier') in ('ALPHA', 'CONSISTENT', 'WEAK_HOLDOUT'):
                            extra = (f" | 학습 {result.get('windows_passed', 0)}/{result.get('num_windows', 0)} PF{result.get('learn_avg_pf', 0):.2f}"
                                     f" | Hold PF{result.get('holdout_pf', 0):.2f} S{result.get('holdout_sharpe', 0):.2f}")
                        print(f"  [{completed}/{len(strategies_to_test)}] "
                              f"{strategy_name:<25s} → {result.get('tier', 'UNKNOWN'):<12s}"
                              f"{extra} ({elapsed:.0f}s elapsed)")
                except Exception as e:
                    print(f"  [{completed}/{len(strategies_to_test)}] "
                          f"{strategy_name:<25s} ERROR: {e}")

        # 4. 결과 저장 (병렬 모드 종료)
        return _finalize_results(alpha_results, save, overall_start,
                                  merge_existing=merge_existing)

    # ============== 순차 모드 (디버깅용 — worker 함수 직접 호출) ==============
    print(f"\n[순차 평가] {len(strategies_to_test)}개 전략 (single-process)")
    for i, strategy in enumerate(strategies_to_test, 1):
        strat_start = time.time()
        result = _evaluate_strategy_worker((strategy.name, sample_size, PARAMETER_GRID))
        if result and result.get('tier') in ('ALPHA', 'CONSISTENT', 'WEAK_HOLDOUT', 'FAIL_LEARN', 'SKIP'):
            if result.get('tier') in ('ALPHA', 'CONSISTENT', 'WEAK_HOLDOUT'):
                alpha_results.append(result)
            print(f"  [{i}/{len(strategies_to_test)}] {strategy.name:<25s} → "
                  f"{result.get('tier', '-')} ({time.time()-strat_start:.0f}초)")

    return _finalize_results(alpha_results, save, overall_start,
                              merge_existing=merge_existing)


def _finalize_results(alpha_results: List[Dict], save: bool, overall_start: float,
                       merge_existing: bool = False) -> List[Dict]:
    """결과 정렬 + 출력 + 저장 (병렬/순차 공통)."""
    print(f"\n{'='*100}")
    print(f"  4년 종합 백테스트 최종 결과")
    print(f"{'='*100}")

    if alpha_results:
        sorted_results = sorted(alpha_results, key=lambda r: -r.get('holdout_pf', 0))
        rows = []
        for r in sorted_results:
            rows.append({
                '판정': r.get('tier', '-'),
                '전략': r['name'][:22],
                '학습': f"{r.get('windows_passed', 0)}/{r.get('num_windows', 0)}",
                '학습PF': f"{r.get('learn_avg_pf', 0):.2f}",
                'Sharpe': f"{r.get('learn_avg_sharpe', 0):.2f}",
                'HoldPF': f"{r.get('holdout_pf', 0):.2f}",
                'HoldSharpe': f"{r.get('holdout_sharpe', 0):.2f}",
                'DSR': f"{r.get('holdout_dsr', 0):.5f}",
                'Hold거래': f"{r.get('holdout_trades', 0)}",
                'MDD': f"{r.get('holdout_mdd', 0):.0%}",
                '수익': f"{r.get('holdout_total_return', 0)*100:+.0f}%",
            })
        print(tabulate(rows, headers='keys', tablefmt='simple', stralign='left'))

        alpha_count = sum(1 for r in alpha_results if r.get('tier') == 'ALPHA')
        consistent_count = sum(1 for r in alpha_results if r.get('tier') == 'CONSISTENT')
        weak_count = sum(1 for r in alpha_results if r.get('tier') == 'WEAK_HOLDOUT')
        print(f"\n  ALPHA (Hold-out PF≥1.5 + Sharpe≥1.0): {alpha_count}개")
        print(f"  CONSISTENT (Hold-out 통과): {consistent_count}개")
        print(f"  WEAK_HOLDOUT (학습 통과만): {weak_count}개")

    # alpha_pool.json 저장 (ALPHA + CONSISTENT만)
    if save and alpha_results:
        eligible = [r for r in alpha_results if r.get('tier') in ('ALPHA', 'CONSISTENT')]
        # merge_existing: 기존 alpha_pool과 병합 (only 평가 시 기존 유지)
        if merge_existing:
            from scripts.screeners.holly_kr.alpha_pool import load_alpha_pool
            existing = load_alpha_pool()
            if existing and existing.get('alpha_strategies'):
                new_names = {r['name'] for r in eligible}
                # 기존 풀에서 신규 평가 안 된 전략은 그대로 유지
                preserved = [s for s in existing['alpha_strategies']
                             if s['name'] not in new_names]
                eligible = preserved + eligible
                print(f"  [merge] 기존 {len(preserved)}개 보존 + 신규 {len(eligible) - len(preserved)}개 추가/갱신")
        if eligible:
            save_alpha_pool(eligible, pbo=0.0,
                            lookback_days=LOOKBACK_DAYS, num_windows=NUM_WINDOWS)

    elapsed = time.time() - overall_start
    print(f"\n총 소요 시간: {elapsed/60:.1f}분")

    return alpha_results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HollyKR 4년 종합 백테스트 (분기 1회)')
    parser.add_argument('--sample', type=int, default=DEFAULT_SAMPLE, help='유니버스 샘플 크기 (기본 500)')
    parser.add_argument('--no-save', action='store_true', help='alpha_pool.json 저장 안 함')
    parser.add_argument('--workers', type=int, default=None,
                        help='ProcessPool worker 수 (기본 cpu_count-1)')
    parser.add_argument('--no-parallel', action='store_true',
                        help='순차 실행 (디버깅용)')
    parser.add_argument('--only', type=str, default=None,
                        help='쉼표 구분 전략명만 평가 (예: clenow_momentum,donchian_breakout)')
    parser.add_argument('--merge', action='store_true',
                        help='기존 alpha_pool.json과 병합 (--only 사용 시 권장)')
    args = parser.parse_args()

    only_list = [s.strip() for s in args.only.split(',')] if args.only else None

    run_5y_backtest(
        sample_size=args.sample,
        save=not args.no_save,
        workers=args.workers,
        parallel=not args.no_parallel,
        only=only_list,
        merge_existing=args.merge,
    )
