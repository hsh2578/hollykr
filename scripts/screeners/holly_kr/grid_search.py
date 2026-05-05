"""
Phase 8: 그리드 서치 (전략 파라미터 최적화)

ALPHA 전략에 대해 (target_mult, stop_mult) 조합 워크포워드 검증.
4 윈도우 누적 PF의 95% CI 하한 기준으로 최적 조합 선정.

사용법:
    python -m scripts.screeners.holly_kr.grid_search --strategy wake_up_call \
        --target-mults 4,5,6 --stop-mults 1.5,2,2.5
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.ohlcv_data import get_ohlcv, flush_cache
from scripts.screeners.holly_kr.universe import get_universe
from scripts.screeners.holly_kr.config import LOOKBACK_DAYS
from scripts.screeners.holly_kr.scanner import ALL_STRATEGIES
from scripts.screeners.holly_kr.backtest import (
    run_backtest, _load_universe_ohlcv, bootstrap_pf_ci,
)


def grid_search_strategy(strategy_name: str,
                          target_mults: List[float],
                          stop_mults: List[float],
                          num_windows: int = 4,
                          window_offset_days: int = 60,
                          test_days: int = 200,
                          sample_size: int = 200) -> List[dict]:
    """단일 전략의 (target_mult, stop_mult) 그리드 서치.

    각 조합마다 워크포워드 4 윈도우 백테스트 → 누적 PF/CI 산출.

    Returns:
        결과 리스트 [{'target': X, 'stop': Y, 'pf': Z, 'ci_lower': L, ...}, ...]
    """
    print("=" * 70)
    print(f"  그리드 서치: {strategy_name}")
    print(f"  target × ATR: {target_mults}")
    print(f"  stop × ATR:   {stop_mults}")
    print(f"  조합 수: {len(target_mults) * len(stop_mults)}")
    print(f"  윈도우: {num_windows} × {test_days}일")
    print("=" * 70)

    # 전략 객체 조회
    target_strategy = next((s for s in ALL_STRATEGIES if s.name == strategy_name), None)
    if target_strategy is None:
        print(f"전략 '{strategy_name}' 없음. 사용 가능: {[s.name for s in ALL_STRATEGIES]}")
        return []

    # OHLCV 사전 로드 (모든 그리드 조합에서 재사용)
    universe = get_universe()
    if sample_size > 0 and sample_size < len(universe):
        universe = universe.nlargest(sample_size, 'MarketCap').reset_index(drop=True)

    print(f"\n  OHLCV 로드 중 ({len(universe)}개)...")
    full_ohlcv = _load_universe_ohlcv(
        universe, days=LOOKBACK_DAYS + num_windows * window_offset_days,
        end_date=None,
    )
    flush_cache()

    today = pd.Timestamp.now().normalize()
    results = []

    # 원본 _atr_target_stop 백업
    orig_atr_method = target_strategy.__class__._atr_target_stop

    overall_start = time.time()
    combo_idx = 0
    total_combos = len(target_mults) * len(stop_mults)

    for tm in target_mults:
        for sm in stop_mults:
            combo_idx += 1
            print(f"\n  [{combo_idx}/{total_combos}] target×{tm}, stop×{sm} (RR={tm/sm:.2f})")
            combo_start = time.time()

            # _atr_target_stop를 그리드 값으로 monkey-patch
            def patched_atr(self, df, entry_price,
                            target_multiple=None, stop_multiple=None,
                            _tm=tm, _sm=sm):
                return orig_atr_method(
                    self, df, entry_price,
                    target_multiple=_tm, stop_multiple=_sm,
                )

            target_strategy.__class__._atr_target_stop = patched_atr

            # 워크포워드 4 윈도우
            all_test_trades = []
            wins_per_window = 0
            for w in range(num_windows):
                window_end = today - pd.Timedelta(days=w * window_offset_days)
                windowed_ohlcv = {
                    t: df[df.index <= window_end]
                    for t, df in full_ohlcv.items()
                }
                windowed_ohlcv = {
                    t: df for t, df in windowed_ohlcv.items()
                    if len(df) >= test_days + 60
                }

                reports = run_backtest(
                    test_days=test_days, strategy_filter=strategy_name,
                    save=False, sample_size=sample_size, split=True,
                    entry_mode='close', end_date=window_end,
                    ohlcv_dict=windowed_ohlcv, universe=universe,
                )
                test_report = next((r for r in reports if r.period == 'Test'), None)
                if test_report and test_report.total_trades > 0:
                    all_test_trades.extend(test_report.trades)
                    if test_report.profit_factor >= 1.2 and test_report.win_rate >= 0.4:
                        wins_per_window += 1

            # 누적 통계
            if all_test_trades:
                pnls = [t.pnl_pct for t in all_test_trades]
                total = len(pnls)
                wr = sum(1 for p in pnls if p > 0) / total
                gross_win = sum(p for p in pnls if p > 0)
                gross_loss = abs(sum(p for p in pnls if p <= 0)) or 0.001
                pf = gross_win / gross_loss
                ci_lower, ci_upper = bootstrap_pf_ci(pnls, n_bootstrap=500)
                total_return = sum(pnls)
            else:
                total = 0
                wr = 0
                pf = 0
                ci_lower, ci_upper = 0, 0
                total_return = 0

            elapsed = time.time() - combo_start
            print(f"      → 거래 {total}, WR {wr:.1%}, PF {pf:.2f} "
                  f"[CI {ci_lower:.2f}~{ci_upper:.2f}], {wins_per_window}/{num_windows} 윈도우 PASS")
            print(f"      소요: {elapsed:.0f}초")

            results.append({
                'strategy': strategy_name,
                'target_mult': tm,
                'stop_mult': sm,
                'rr': round(tm / sm, 2),
                'trades': total,
                'win_rate': round(wr, 3),
                'pf': round(pf, 2),
                'ci_lower': round(ci_lower, 2),
                'ci_upper': round(ci_upper, 2),
                'total_return': round(total_return, 3),
                'windows_passed': wins_per_window,
                'is_alpha': ci_lower > 1.0 and total >= 30,
            })

    # 원본 메서드 복원
    target_strategy.__class__._atr_target_stop = orig_atr_method

    # 결과 정렬: ALPHA 우선 → CI 하한 → PF 순
    results.sort(key=lambda r: (-int(r['is_alpha']), -r['ci_lower'], -r['pf']))

    overall_elapsed = time.time() - overall_start
    print(f"\n{'=' * 70}")
    print(f"  그리드 서치 완료: {strategy_name} ({overall_elapsed:.0f}초)")
    print(f"{'=' * 70}")
    print(f"\n  최고 조합:")
    for i, r in enumerate(results[:5], 1):
        alpha = "★ ALPHA" if r['is_alpha'] else "       "
        print(f"    {i}. {alpha} target×{r['target_mult']} stop×{r['stop_mult']} (RR={r['rr']}) "
              f"| 거래 {r['trades']} WR {r['win_rate']:.1%} "
              f"PF {r['pf']:.2f} [CI {r['ci_lower']:.2f}~{r['ci_upper']:.2f}] "
              f"수익 {r['total_return']*100:+.0f}% | {r['windows_passed']}/4 PASS")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HollyKR 그리드 서치')
    parser.add_argument('--strategy', type=str, required=True,
                        help='최적화할 전략명 (예: wake_up_call)')
    parser.add_argument('--target-mults', type=str, default='3,4,5,6',
                        help='target ATR 배수 (콤마 구분)')
    parser.add_argument('--stop-mults', type=str, default='1.5,2,2.5',
                        help='stop ATR 배수 (콤마 구분)')
    parser.add_argument('--windows', type=int, default=4)
    parser.add_argument('--window-offset', type=int, default=60)
    parser.add_argument('--days', type=int, default=200)
    parser.add_argument('--sample', type=int, default=200)
    parser.add_argument('--csv', action='store_true', help='CSV 저장')

    args = parser.parse_args()

    target_mults = [float(x) for x in args.target_mults.split(',')]
    stop_mults = [float(x) for x in args.stop_mults.split(',')]

    results = grid_search_strategy(
        strategy_name=args.strategy,
        target_mults=target_mults,
        stop_mults=stop_mults,
        num_windows=args.windows,
        window_offset_days=args.window_offset,
        test_days=args.days,
        sample_size=args.sample,
    )

    if args.csv and results:
        from datetime import datetime
        from scripts.screeners.holly_kr.config import OUTPUT_DIR
        today = datetime.now().strftime('%Y-%m-%d')
        path = OUTPUT_DIR / f'grid_search_{args.strategy}_{today}.csv'
        pd.DataFrame(results).to_csv(path, index=False, encoding='utf-8-sig')
        print(f"\nCSV 저장: {path}")
