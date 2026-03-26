"""
HollyKR 백테스트 엔진

전략별 과거 시뮬레이션 → 승률/수익률/MDD/샤프 등 성과 리포트 생성.

사용법:
    python -m scripts.screeners.holly_kr.backtest                  # 전체 32개 전략
    python -m scripts.screeners.holly_kr.backtest --days 120       # 최근 120거래일
    python -m scripts.screeners.holly_kr.backtest --strategy engulfing  # 특정 전략만
    python -m scripts.screeners.holly_kr.backtest --csv            # CSV 저장
    python -m scripts.screeners.holly_kr.backtest --no-split       # OOS 분할 비활성화
"""

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.ohlcv_data import get_ohlcv, flush_cache
from scripts.screeners.holly_kr.universe import get_universe
from scripts.screeners.holly_kr.config import LOOKBACK_DAYS, OUTPUT_DIR, ROUND_TRIP_COST
from scripts.screeners.holly_kr.scanner import PHASE1_STRATEGIES, PHASE2_STRATEGIES


# ============================================================================
# 데이터 클래스
# ============================================================================

@dataclass
class Trade:
    """개별 거래 기록."""
    strategy: str
    ticker: str
    name: str
    entry_date: str
    entry_price: float
    exit_date: str = ''
    exit_price: float = 0.0
    exit_reason: str = ''      # target, stop_loss, time_exit
    pnl_pct: float = 0.0       # 수익률 (0.03 = 3%)  - 거래비용 차감 후
    hold_days: int = 0
    target_pct: float = 0.0
    stop_loss_pct: float = 0.0
    hold_days_max: int = 10    # 전략별 최대 보유일


@dataclass
class StrategyReport:
    """전략별 성과 리포트."""
    name: str
    grade: str
    exec_timing: str
    category: str
    period: str = ''                # 'Train', 'Test', 또는 '' (분할 미사용)
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    total_return: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    avg_hold_days: float = 0.0
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    trades: List[Trade] = field(default_factory=list)


# ============================================================================
# 백테스트 엔진
# ============================================================================

def _get_slippage_pct(market_cap: float) -> float:
    """시가총액 기반 슬리피지 비율 반환.

    Large cap (5조+): 0.1%, Mid cap (1조~5조): 0.2%, Small cap (<1조): 0.5%
    """
    if market_cap >= 5_000_000_000_000:    # 5조 이상
        return 0.001
    elif market_cap >= 1_000_000_000_000:  # 1조 이상
        return 0.002
    else:
        return 0.005


def _simulate_strategy(strategy, universe_ohlcv: Dict[str, pd.DataFrame],
                        universe_info: pd.DataFrame,
                        test_days: int = 120,
                        start_offset: int = 0,
                        end_offset: int = 0,
                        entry_mode: str = 'open') -> List[Trade]:
    """
    단일 전략의 과거 시뮬레이션.

    test_days 거래일 동안 매일 스캔 → 시그널 발생 시 다음날 시가 진입
    → target/stop/max_hold로 청산.

    Args:
        strategy: 전략 인스턴스
        universe_ohlcv: 종목별 OHLCV 딕셔너리
        universe_info: 유니버스 DataFrame
        test_days: 전체 테스트 기간 (거래일)
        start_offset: 시뮬레이션 시작 오프셋 (0=처음부터)
        end_offset: 시뮬레이션 끝 오프셋 (0=끝까지)
    """
    trades = []

    # 실제 시뮬레이션 범위 계산
    sim_start = test_days - start_offset   # day_offset 시작 (큰 값 = 오래된 과거)
    sim_end = max(1, end_offset)           # day_offset 끝 (작은 값 = 최근)

    for _, row in universe_info.iterrows():
        ticker = row['Code']
        name = row.get('Name', ticker)
        sector = row.get('Sector', '')
        market_cap = row.get('MarketCap', 0)

        df = universe_ohlcv.get(ticker)
        if df is None or len(df) < test_days + 60:
            continue

        # 슬리피지 계산
        slippage_pct = _get_slippage_pct(market_cap)

        # 지정된 범위 동안 매일 스캔
        active_trade = None  # 종목당 동시 1건만

        for day_offset in range(sim_start, sim_end - 1, -1):
            scan_end = len(df) - day_offset
            if scan_end < 60:
                continue

            # 활성 거래가 있으면 청산 확인
            if active_trade is not None:
                current_idx = scan_end
                if current_idx >= len(df):
                    continue

                current = df.iloc[current_idx]
                days_held = active_trade.hold_days + 1
                active_trade.hold_days = days_held

                # 손절 확인 (장중 저가)  - 슬리피지 적용
                if active_trade.stop_loss_pct != 0:
                    stop_price = active_trade.entry_price * (1 + active_trade.stop_loss_pct)
                    if current['Low'] <= stop_price:
                        exit_price = stop_price * (1 - slippage_pct)
                        active_trade.exit_date = str(current.name.date()) if hasattr(current.name, 'date') else ''
                        active_trade.exit_price = exit_price
                        active_trade.pnl_pct = (exit_price - active_trade.entry_price) / active_trade.entry_price - ROUND_TRIP_COST
                        active_trade.exit_reason = 'stop_loss'
                        trades.append(active_trade)
                        active_trade = None
                        continue

                # 목표 확인 (장중 고가)  - 슬리피지 적용
                if active_trade.target_pct != 0:
                    target_price = active_trade.entry_price * (1 + active_trade.target_pct)
                    if current['High'] >= target_price:
                        exit_price = target_price * (1 - slippage_pct)
                        active_trade.exit_date = str(current.name.date()) if hasattr(current.name, 'date') else ''
                        active_trade.exit_price = exit_price
                        active_trade.pnl_pct = (exit_price - active_trade.entry_price) / active_trade.entry_price - ROUND_TRIP_COST
                        active_trade.exit_reason = 'target'
                        trades.append(active_trade)
                        active_trade = None
                        continue

                # 최대 보유일 초과  - Trade에 저장된 전략별 hold_days_max 사용
                max_hold = active_trade.hold_days_max
                if days_held >= max_hold:
                    exit_price = current['Close'] * (1 - slippage_pct)
                    active_trade.exit_date = str(current.name.date()) if hasattr(current.name, 'date') else ''
                    active_trade.exit_price = exit_price
                    active_trade.pnl_pct = (exit_price - active_trade.entry_price) / active_trade.entry_price - ROUND_TRIP_COST
                    active_trade.exit_reason = 'time_exit'
                    trades.append(active_trade)
                    active_trade = None
                    continue

                continue  # 활성 거래 있으면 새 시그널 안 봄

            # 스캔 (활성 거래 없을 때만)
            hist = df.iloc[:scan_end]
            if len(hist) < 30:
                continue

            try:
                entry_price = hist['Close'].iloc[-1]
                sig = strategy.scan(hist, ticker, name,
                                    sector=sector, entry_price=entry_price)
            except Exception:
                sig = None

            if sig is None:
                continue

            # 진입가 결정
            if entry_mode == 'close':
                # 종가매매: 당일 종가로 진입 (슬리피지 최소)
                actual_entry = hist['Close'].iloc[-1] * (1 + slippage_pct * 0.2)  # 동시호가 슬리피지 20%만
                entry_date = str(hist.index[-1].date()) if hasattr(hist.index[-1], 'date') else ''
            else:
                # 시가매매: 다음날 시가로 진입
                next_idx = scan_end
                if next_idx >= len(df):
                    continue
                next_day = df.iloc[next_idx]
                actual_entry = next_day['Open'] * (1 + slippage_pct)
                entry_date = str(next_day.name.date()) if hasattr(next_day.name, 'date') else ''

            if actual_entry <= 0:
                continue

            active_trade = Trade(
                strategy=strategy.name,
                ticker=ticker,
                name=name,
                entry_date=entry_date,
                entry_price=actual_entry,
                target_pct=sig.target_pct,
                stop_loss_pct=sig.stop_loss_pct,
                hold_days=0,
                hold_days_max=sig.hold_days_max,
            )

        # 기간 끝났는데 아직 열린 거래가 있으면 강제 청산  - 슬리피지 적용
        if active_trade is not None:
            last = df.iloc[-1]
            exit_price = last['Close'] * (1 - slippage_pct)
            active_trade.exit_date = str(last.name.date()) if hasattr(last.name, 'date') else ''
            active_trade.exit_price = exit_price
            active_trade.pnl_pct = (exit_price - active_trade.entry_price) / active_trade.entry_price - ROUND_TRIP_COST
            active_trade.exit_reason = 'forced_close'
            trades.append(active_trade)

    return trades


def _calc_report(strategy, trades: List[Trade], period: str = '') -> StrategyReport:
    """거래 기록 → 성과 리포트."""
    report = StrategyReport(
        name=strategy.name,
        grade=strategy.grade,
        exec_timing=strategy.exec_timing,
        category=strategy.category,
        period=period,
        trades=trades,
    )

    if not trades:
        return report

    pnls = [t.pnl_pct for t in trades]
    report.total_trades = len(trades)
    report.wins = sum(1 for p in pnls if p > 0)
    report.losses = sum(1 for p in pnls if p <= 0)
    report.win_rate = report.wins / report.total_trades if report.total_trades > 0 else 0
    report.avg_return = np.mean(pnls)
    report.total_return = sum(pnls)
    report.best_trade = max(pnls)
    report.worst_trade = min(pnls)
    report.avg_hold_days = np.mean([t.hold_days for t in trades])

    win_pnls = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p <= 0]
    report.avg_win = np.mean(win_pnls) if win_pnls else 0
    report.avg_loss = np.mean(loss_pnls) if loss_pnls else 0

    total_profit = sum(win_pnls)
    total_loss = abs(sum(loss_pnls))
    report.profit_factor = total_profit / total_loss if total_loss > 0 else 999

    # MDD (누적 수익 기준)
    cumulative = np.cumsum(pnls)
    peak = np.maximum.accumulate(cumulative)
    drawdown = cumulative - peak
    report.max_drawdown = float(np.min(drawdown)) if len(drawdown) > 0 else 0

    # Sharpe (일간 수익률 기준, 연환산)
    if len(pnls) > 1 and np.std(pnls) > 0:
        report.sharpe_ratio = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252 / max(report.avg_hold_days, 1))
    else:
        report.sharpe_ratio = 0

    # Calmar = 연간 수익률 / MDD
    if report.max_drawdown < 0:
        report.calmar_ratio = abs(report.total_return / report.max_drawdown)
    else:
        report.calmar_ratio = 999

    return report


# ============================================================================
# OHLCV 수집
# ============================================================================

def _load_universe_ohlcv(universe: pd.DataFrame, days: int = 300) -> Dict[str, pd.DataFrame]:
    """유니버스 전종목 OHLCV 로드 (캐시 활용)."""
    ohlcv_dict = {}
    total = len(universe)

    for i, (_, row) in enumerate(universe.iterrows(), 1):
        ticker = row['Code']
        df = get_ohlcv(ticker, days=days, use_cache=True)
        if df is not None and len(df) > 0:
            ohlcv_dict[ticker] = df
        if i % 200 == 0:
            print(f"    OHLCV 로드: {i}/{total} ({len(ohlcv_dict)}개)")

    return ohlcv_dict


# ============================================================================
# 리포트 출력
# ============================================================================

def print_summary(reports: List[StrategyReport], split: bool = False):
    """전략별 성과 요약 테이블."""

    if split:
        _print_summary_split(reports)
    else:
        _print_summary_simple(reports)


def _print_summary_simple(reports: List[StrategyReport]):
    """기존 단일 기간 요약 출력."""
    # 거래 있는 전략만
    active = [r for r in reports if r.total_trades > 0]
    inactive = [r for r in reports if r.total_trades == 0]

    if not active:
        print("\n시그널이 발생한 전략이 없습니다.")
        return

    # 승률 기준 정렬
    active.sort(key=lambda r: (-r.win_rate, -r.profit_factor))

    rows = []
    for r in active:
        verdict = 'PASS' if r.win_rate >= 0.4 and r.profit_factor >= 1.2 else 'FAIL'
        rows.append({
            '판정': verdict,
            '전략': r.name[:25],
            '등급': r.grade,
            '거래수': r.total_trades,
            '승률': f'{r.win_rate:.1%}',
            '평균수익': f'{r.avg_return:+.2%}',
            '총수익': f'{r.total_return:+.1%}',
            'PF': f'{r.profit_factor:.2f}',
            '평균보유': f'{r.avg_hold_days:.1f}일',
            'MDD': f'{r.max_drawdown:.1%}',
            'Sharpe': f'{r.sharpe_ratio:.2f}',
            '최고': f'{r.best_trade:+.1%}',
            '최악': f'{r.worst_trade:+.1%}',
        })

    print(f"\n{'='*90}")
    print(f"전략 백테스트 결과 ({len(active)}개 전략, {len(inactive)}개 시그널 없음)")
    print(f"{'='*90}")
    print(tabulate(rows, headers='keys', tablefmt='simple', stralign='left'))

    # 요약
    passed = [r for r in active if r.win_rate >= 0.4 and r.profit_factor >= 1.2]
    print(f"\n통과(PASS): {len(passed)}개 / 전체 {len(reports)}개")
    if passed:
        avg_wr = np.mean([r.win_rate for r in passed])
        avg_pf = np.mean([r.profit_factor for r in passed])
        print(f"통과 전략 평균 승률: {avg_wr:.1%}, 평균 PF: {avg_pf:.2f}")

    if inactive:
        print(f"\n시그널 없음 ({len(inactive)}개): {', '.join(r.name for r in inactive)}")


def _print_summary_split(reports: List[StrategyReport]):
    """Train/Test 분할 결과를 나란히 표시."""
    train_reports = {r.name: r for r in reports if r.period == 'Train'}
    test_reports = {r.name: r for r in reports if r.period == 'Test'}

    strategy_names = list(dict.fromkeys(
        [r.name for r in reports if r.total_trades > 0]
    ))

    if not strategy_names:
        print("\n시그널이 발생한 전략이 없습니다.")
        return

    rows = []
    overfit_count = 0
    pass_count = 0

    for name in strategy_names:
        tr = train_reports.get(name)
        te = test_reports.get(name)

        # Train 판정
        train_pass = (tr and tr.total_trades > 0
                      and tr.win_rate >= 0.4 and tr.profit_factor >= 1.2)
        # Test 판정 (최종 판정 기준)
        test_pass = (te and te.total_trades > 0
                     and te.win_rate >= 0.4 and te.profit_factor >= 1.2)

        if train_pass and not test_pass:
            verdict = 'OVERFIT'
            overfit_count += 1
        elif test_pass:
            verdict = 'PASS'
            pass_count += 1
        else:
            verdict = 'FAIL'

        row = {
            '판정': verdict,
            '전략': name[:20],
            '등급': tr.grade if tr else (te.grade if te else ''),
        }

        # Train 열
        if tr and tr.total_trades > 0:
            row['Train거래'] = tr.total_trades
            row['Train승률'] = f'{tr.win_rate:.1%}'
            row['TrainPF'] = f'{tr.profit_factor:.2f}'
            row['Train수익'] = f'{tr.total_return:+.1%}'
        else:
            row['Train거래'] = 0
            row['Train승률'] = '-'
            row['TrainPF'] = '-'
            row['Train수익'] = '-'

        # Test 열
        if te and te.total_trades > 0:
            row['Test거래'] = te.total_trades
            row['Test승률'] = f'{te.win_rate:.1%}'
            row['TestPF'] = f'{te.profit_factor:.2f}'
            row['Test수익'] = f'{te.total_return:+.1%}'
        else:
            row['Test거래'] = 0
            row['Test승률'] = '-'
            row['TestPF'] = '-'
            row['Test수익'] = '-'

        rows.append(row)

    # 판정 기준 정렬: PASS > OVERFIT > FAIL
    verdict_order = {'PASS': 0, 'OVERFIT': 1, 'FAIL': 2}
    rows.sort(key=lambda r: verdict_order.get(r['판정'], 3))

    total_strategies = len(set(r.name for r in reports))
    no_signal = total_strategies - len(strategy_names)

    print(f"\n{'='*110}")
    print(f"전략 백테스트 결과  - Train/Test 분할 (OOS 검증)")
    print(f"{'='*110}")
    print(tabulate(rows, headers='keys', tablefmt='simple', stralign='left'))

    print(f"\n통과(PASS, Test 기준): {pass_count}개 / 전체 {total_strategies}개")
    print(f"과적합(OVERFIT  - Train PASS, Test FAIL): {overfit_count}개")
    fail_count = len(strategy_names) - pass_count - overfit_count
    print(f"실패(FAIL): {fail_count}개")
    if no_signal > 0:
        inactive_names = [r.name for r in reports
                          if r.total_trades == 0 and r.period in ('Train', '')]
        print(f"시그널 없음: {no_signal}개  - {', '.join(set(inactive_names))}")


def save_csv(reports: List[StrategyReport], trades_all: List[Trade]):
    """백테스트 결과 CSV 저장."""
    today = datetime.now().strftime('%Y-%m-%d')

    # 전략별 요약
    summary_rows = []
    for r in reports:
        summary_rows.append({
            'strategy': r.name, 'grade': r.grade, 'timing': r.exec_timing,
            'category': r.category, 'trades': r.total_trades,
            'wins': r.wins, 'losses': r.losses, 'win_rate': round(r.win_rate, 4),
            'avg_return': round(r.avg_return, 4), 'total_return': round(r.total_return, 4),
            'profit_factor': round(r.profit_factor, 2), 'mdd': round(r.max_drawdown, 4),
            'sharpe': round(r.sharpe_ratio, 2), 'avg_hold_days': round(r.avg_hold_days, 1),
        })
    summary_path = OUTPUT_DIR / f'backtest_summary_{today}.csv'
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False, encoding='utf-8-sig')
    print(f"  전략 요약: {summary_path}")

    # 개별 거래
    if trades_all:
        trade_rows = [{
            'strategy': t.strategy, 'ticker': t.ticker, 'name': t.name,
            'entry_date': t.entry_date, 'entry_price': round(t.entry_price),
            'exit_date': t.exit_date, 'exit_price': round(t.exit_price),
            'exit_reason': t.exit_reason, 'pnl_pct': round(t.pnl_pct, 4),
            'hold_days': t.hold_days,
        } for t in trades_all]
        trades_path = OUTPUT_DIR / f'backtest_trades_{today}.csv'
        pd.DataFrame(trade_rows).to_csv(trades_path, index=False, encoding='utf-8-sig')
        print(f"  거래 내역: {trades_path}")


# ============================================================================
# 메인
# ============================================================================

def run_backtest(test_days: int = 120, strategy_filter: str = None,
                  save: bool = False, sample_size: int = 200,
                  split: bool = True, entry_mode: str = 'open') -> List[StrategyReport]:
    """
    백테스트 실행.

    Args:
        test_days: 테스트 기간 (거래일)
        strategy_filter: 특정 전략만 (이름)
        save: CSV 저장 여부
        sample_size: 유니버스 샘플 크기 (0=전체, N=시총 상위 N개)
        split: True면 Train(70%)/Test(30%) OOS 분할 검증
    """
    print("=" * 60)
    print("  HollyKR 백테스트 엔진")
    print(f"  테스트 기간: 최근 {test_days}거래일")
    if split:
        train_days = int(test_days * 0.7)
        test_days_oos = test_days - train_days
        print(f"  OOS 분할: Train {train_days}일 / Test {test_days_oos}일")
    print("=" * 60)

    start = time.time()

    # 1. 유니버스
    universe = get_universe()
    if sample_size > 0 and sample_size < len(universe):
        universe = universe.nlargest(sample_size, 'MarketCap').reset_index(drop=True)
        print(f"  샘플링: 시총 상위 {sample_size}개 종목")

    # 2. OHLCV 로드
    print(f"\n  OHLCV 로드 중 ({len(universe)}개 종목)...")
    ohlcv_dict = _load_universe_ohlcv(universe, days=LOOKBACK_DAYS)
    print(f"  OHLCV 로드 완료: {len(ohlcv_dict)}개 종목")

    # OHLCV 캐시 저장
    flush_cache()

    # 3. 전략 목록
    all_strategies = PHASE1_STRATEGIES + PHASE2_STRATEGIES
    if strategy_filter:
        all_strategies = [s for s in all_strategies if s.name == strategy_filter]
        if not all_strategies:
            print(f"전략 '{strategy_filter}' 을 찾을 수 없습니다.")
            return []

    print(f"\n  전략 수: {len(all_strategies)}개")
    print(f"  테스트 기간: {test_days}거래일")
    if split:
        print(f"  Train/Test 분할: 활성화 (70/30)")
    print("=" * 60)

    # 4. 전략별 백테스트
    reports = []
    all_trades = []

    for i, strategy in enumerate(all_strategies, 1):
        print(f"\n  [{i}/{len(all_strategies)}] {strategy.name} ({strategy.grade}, {strategy.exec_timing})")

        if split:
            # --- Train 기간: 처음 70% (과거 쪽) ---
            # day_offset 범위: test_days ~ test_days_oos+1 (오래된 과거 → 중간)
            train_trades = _simulate_strategy(
                strategy, ohlcv_dict, universe,
                test_days=test_days,
                start_offset=0,
                end_offset=test_days_oos,
                entry_mode=entry_mode,
            )
            train_report = _calc_report(strategy, train_trades, period='Train')
            reports.append(train_report)
            all_trades.extend(train_trades)

            # --- Test 기간: 마지막 30% (최근 쪽) ---
            test_trades = _simulate_strategy(
                strategy, ohlcv_dict, universe,
                test_days=test_days,
                start_offset=train_days,
                end_offset=0,
                entry_mode=entry_mode,
            )
            test_report = _calc_report(strategy, test_trades, period='Test')
            reports.append(test_report)
            all_trades.extend(test_trades)

            # 콘솔 출력
            for label, rpt in [('Train', train_report), ('Test', test_report)]:
                if rpt.total_trades > 0:
                    print(f"    [{label}] 거래: {rpt.total_trades}건, 승률: {rpt.win_rate:.1%}, "
                          f"PF: {rpt.profit_factor:.2f}, 총수익: {rpt.total_return:+.1%}")
                else:
                    print(f"    [{label}] 시그널 없음")
        else:
            # 분할 없이 전체 기간
            trades = _simulate_strategy(strategy, ohlcv_dict, universe, test_days=test_days, entry_mode=entry_mode)
            report = _calc_report(strategy, trades)
            reports.append(report)
            all_trades.extend(trades)

            if report.total_trades > 0:
                print(f"    거래: {report.total_trades}건, 승률: {report.win_rate:.1%}, "
                      f"PF: {report.profit_factor:.2f}, 총수익: {report.total_return:+.1%}")
            else:
                print(f"    시그널 없음")

    # 5. 결과 출력
    elapsed = time.time() - start
    print_summary(reports, split=split)

    if save:
        save_csv(reports, all_trades)

    print(f"\n총 거래: {len(all_trades)}건, 소요 시간: {elapsed:.1f}초")

    return reports


# ============================================================================
# CLI
# ============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HollyKR 백테스트 엔진')
    parser.add_argument('--days', type=int, default=120,
                        help='테스트 기간 거래일 (기본 120 = ~6개월)')
    parser.add_argument('--strategy', type=str, default=None,
                        help='특정 전략만 테스트')
    parser.add_argument('--csv', action='store_true', help='CSV 저장')
    parser.add_argument('--sample', type=int, default=200,
                        help='유니버스 샘플 크기 (0=전체, 기본 200)')
    parser.add_argument('--no-split', action='store_true',
                        help='Train/Test OOS 분할 비활성화 (기본: 분할 활성)')
    parser.add_argument('--entry', type=str, default='open',
                        choices=['open', 'close'],
                        help='진입 모드: open=다음날 시가, close=당일 종가')

    args = parser.parse_args()
    run_backtest(
        test_days=args.days,
        strategy_filter=args.strategy,
        save=args.csv,
        sample_size=args.sample,
        split=not args.no_split,
        entry_mode=args.entry,
    )
