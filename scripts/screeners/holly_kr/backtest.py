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
from scripts.screeners.holly_kr.config import (
    LOOKBACK_DAYS, OUTPUT_DIR, ROUND_TRIP_COST,
    TRAILING_STOP_PCT, PARTIAL_PROFIT_PCT, FIRST_DAY_LOSS_PCT,
    GAP_DOWN_EXIT_AT_OPEN,
    CATEGORY_TRAILING_PCT, FIRST_DAY_RULE_CATEGORIES,
)
from scripts.screeners.holly_kr.scanner import PHASE1_STRATEGIES, PHASE2_STRATEGIES, ALL_STRATEGIES


# ============================================================================
# 데이터 클래스
# ============================================================================

@dataclass
class Trade:
    """개별 거래 기록 (실전 청산 일치)."""
    strategy: str
    category: str = ''           # Phase C: 카테고리별 trailing 적용용
    ticker: str = ''
    name: str = ''
    entry_date: str = ''
    entry_price: float = 0.0
    exit_date: str = ''
    exit_price: float = 0.0
    exit_reason: str = ''      # target, stop_loss, time_exit, gap_down, first_day, trailing, partial+trailing 등
    pnl_pct: float = 0.0       # 최종 수익률 (50% 익절 + 잔량 청산 합산, 거래비용 차감 후)
    hold_days: int = 0
    target_pct: float = 0.0
    stop_loss_pct: float = 0.0
    hold_days_max: int = 10    # 전략별 최대 보유일

    # 실전 청산 트래킹
    target_hit: bool = False             # 목표가 한 번이라도 도달
    partial_done: bool = False           # 50% 익절 완료
    partial_exit_price: float = 0.0      # 50% 청산가 (목표가 도달 시점, 슬리피지 적용)
    max_close_during_hold: float = 0.0   # 보유 중 최고 종가 (트레일링용)
    trail_stop_price: float = 0.0        # 트레일링 스탑 가격


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
    pf_ci_lower: float = 0.0       # 95% CI 하한 (bootstrap)
    pf_ci_upper: float = 0.0       # 95% CI 상한
    pf_significant: bool = False   # PF lower CI > 1.0 (진짜 알파)
    max_drawdown: float = 0.0
    avg_hold_days: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0     # Phase A: 하방 변동성만 (trend-following 권장)
    calmar_ratio: float = 0.0
    fitness_score: float = 0.0      # Phase D: WorldQuant 종합 (sqrt(|Ret|/Turnover) × Sharpe)
    deflated_sharpe: float = 0.0    # Phase B: López de Prado Deflated SR (multiple testing 보정)
    pbo: float = 0.0                # Phase B: Probability of Backtest Overfitting (0~1)
    best_trade: float = 0.0
    worst_trade: float = 0.0
    trades: List[Trade] = field(default_factory=list)


def bootstrap_pf_ci(pnls: List[float], n_bootstrap: int = 1000,
                    ci: float = 0.95, seed: int = 42) -> tuple:
    """Trade-level PnL 부트스트랩 → PF의 신뢰구간.

    Returns:
        (lower, upper) — ci% 신뢰구간
    """
    if len(pnls) < 5:
        return 0.0, 0.0
    rng = np.random.default_rng(seed)  # 결정적 결과 보장
    pf_samples = []
    n = len(pnls)
    pnls_arr = np.array(pnls)
    for _ in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        sample = pnls_arr[idx]
        wins = sample[sample > 0].sum()
        losses = abs(sample[sample <= 0].sum())
        if losses > 0:
            pf_samples.append(wins / losses)
        elif wins > 0:
            pf_samples.append(20.0)  # 손실 없으면 큰 값 (cap)
    if not pf_samples:
        return 0.0, 0.0
    alpha = (1 - ci) / 2
    lower = float(np.percentile(pf_samples, alpha * 100))
    upper = float(np.percentile(pf_samples, (1 - alpha) * 100))
    return lower, upper


# ============================================================================
# Phase B: López de Prado 방법론 (Deflated Sharpe + PBO)
# ============================================================================

def deflated_sharpe_ratio(sharpe: float, n_trials: int, skewness: float = 0.0,
                           kurtosis: float = 3.0, n_obs: int = 100) -> float:
    """Deflated Sharpe Ratio (López de Prado 2014).

    Multiple testing 보정 + 비정규 분포 보정.
    참고: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

    Args:
        sharpe: 관측 Sharpe ratio
        n_trials: 테스트한 전략 수 (multiple testing 보정용)
        skewness: PnL 분포 왜도 (0=정규)
        kurtosis: PnL 분포 첨도 (3=정규)
        n_obs: 관측 수 (거래 수)

    Returns:
        DSR (0~1, 1 가까우면 진짜 알파). DSR < 0.95 → 통계적 의미 부족.
    """
    if n_obs < 5 or n_trials < 1:
        return 0.0
    from scipy.stats import norm

    # Expected max Sharpe (under null hypothesis: SR=0)
    # SR_max ≈ √(2 ln(N)) (다중 검정 시 우연으로 얻는 최대 Sharpe)
    euler_mascheroni = 0.5772156649
    n = max(n_trials, 1)
    expected_max_sr = (
        (1 - euler_mascheroni) * norm.ppf(1 - 1.0 / n)
        + euler_mascheroni * norm.ppf(1 - 1.0 / (n * np.e))
    )

    # Standard error of Sharpe (비정규 분포 보정)
    sr_std = np.sqrt(
        (1 - skewness * sharpe + (kurtosis - 1) / 4 * sharpe ** 2) / (n_obs - 1)
    )

    # DSR (PSR with deflation)
    if sr_std <= 0:
        return 0.0
    z = (sharpe - expected_max_sr) / sr_std
    dsr = float(norm.cdf(z))
    return max(0.0, min(1.0, dsr))


def probability_backtest_overfitting(pnls_per_strategy: Dict[str, List[float]]) -> float:
    """Probability of Backtest Overfitting (Bailey, López de Prado et al. 2014).

    참고: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

    각 전략의 PnL을 N등분 → 모든 조합으로 Train/Test 분리 → 순위 일관성 측정
    PBO = "Train에서 1등이 Test에서 하위 50%로 떨어지는 비율"

    Args:
        pnls_per_strategy: {strategy_name: [pnl1, pnl2, ...]}

    Returns:
        PBO (0~1). 0=과적합 X, 1=완전 과적합. 0.5 미만이 양호.
    """
    if len(pnls_per_strategy) < 2:
        return 0.5  # 평가 불가 → 중립

    from itertools import combinations

    # 각 전략 PnL을 동일 길이로 padding (가장 짧은 전략 길이로)
    min_len = min(len(p) for p in pnls_per_strategy.values())
    if min_len < 16:
        return 0.5  # 데이터 부족

    # 16개 chunk로 분할
    n_chunks = 16
    chunk_size = min_len // n_chunks
    if chunk_size < 1:
        return 0.5

    strategies = list(pnls_per_strategy.keys())
    chunks = {}
    for s in strategies:
        chunks[s] = [
            pnls_per_strategy[s][i * chunk_size:(i + 1) * chunk_size]
            for i in range(n_chunks)
        ]

    # Combinatorial: chunks를 N/2 train, N/2 test로 모든 조합 분리
    half = n_chunks // 2
    overfit_count = 0
    total_count = 0

    for train_idx in combinations(range(n_chunks), half):
        train_idx_set = set(train_idx)
        test_idx = [i for i in range(n_chunks) if i not in train_idx_set]

        # Train PnL (전략별)
        train_pnls = {}
        test_pnls = {}
        for s in strategies:
            train_pnls[s] = [v for i in train_idx for v in chunks[s][i]]
            test_pnls[s] = [v for i in test_idx for v in chunks[s][i]]

        # Train에서 가장 좋은 전략
        train_pf = {}
        for s in strategies:
            wins = sum(p for p in train_pnls[s] if p > 0)
            losses = abs(sum(p for p in train_pnls[s] if p <= 0)) or 0.001
            train_pf[s] = wins / losses
        best_train = max(train_pf, key=train_pf.get)

        # Test에서 그 전략의 순위
        test_pf = {}
        for s in strategies:
            wins = sum(p for p in test_pnls[s] if p > 0)
            losses = abs(sum(p for p in test_pnls[s] if p <= 0)) or 0.001
            test_pf[s] = wins / losses
        sorted_test = sorted(test_pf, key=test_pf.get, reverse=True)
        rank_in_test = sorted_test.index(best_train) + 1

        # 하위 50%로 떨어지면 overfit
        if rank_in_test > len(strategies) / 2:
            overfit_count += 1
        total_count += 1

        # 1000개 조합으로 제한 (계산 비용)
        if total_count >= 1000:
            break

    return overfit_count / total_count if total_count > 0 else 0.5


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


def _close_trade(trade: 'Trade', final_exit_price: float, exit_date: str,
                 reason: str, slippage_pct: float):
    """거래 종료 — 50% 익절 분과 잔량 청산 분 PnL 합산.

    50% 부분익절이 발생했으면:
        총수익 = 0.5 × (partial_exit - entry)/entry + 0.5 × (final_exit - entry)/entry - 거래비용
    아니면 (전량 청산):
        총수익 = (final_exit - entry)/entry - 거래비용
    """
    trade.exit_price = final_exit_price
    trade.exit_date = exit_date
    trade.exit_reason = reason

    entry = trade.entry_price
    if entry <= 0:
        trade.pnl_pct = 0.0
        return

    if trade.partial_done and trade.partial_exit_price > 0:
        partial_ret = (trade.partial_exit_price - entry) / entry
        final_ret = (final_exit_price - entry) / entry
        trade.pnl_pct = (
            PARTIAL_PROFIT_PCT * partial_ret
            + (1 - PARTIAL_PROFIT_PCT) * final_ret
            - ROUND_TRIP_COST
        )
        # 부분익절 발생 시 reason 라벨에 표기
        if reason in ('time_exit', 'trailing', 'trailing_gap'):
            trade.exit_reason = f'partial_{reason}'
    else:
        trade.pnl_pct = (final_exit_price - entry) / entry - ROUND_TRIP_COST


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

            # 활성 거래가 있으면 청산 확인 (실전 ExitManager와 일치)
            if active_trade is not None:
                current_idx = scan_end
                if current_idx >= len(df):
                    continue

                current = df.iloc[current_idx]
                days_held = active_trade.hold_days + 1
                active_trade.hold_days = days_held
                today_open = current['Open']
                today_high = current['High']
                today_low = current['Low']
                today_close = current['Close']
                today_date = str(current.name.date()) if hasattr(current.name, 'date') else ''

                # 보유 중 최고 종가 갱신 (트레일링용)
                active_trade.max_close_during_hold = max(
                    active_trade.max_close_during_hold, today_close
                )

                stop_price = active_trade.entry_price * (1 + active_trade.stop_loss_pct)
                target_price = active_trade.entry_price * (1 + active_trade.target_pct)

                # ============================================================
                # 우선순위 1: 갭다운 (시초가 < 손절가) → 시초가 즉시 청산
                # ============================================================
                if GAP_DOWN_EXIT_AT_OPEN and today_open <= stop_price:
                    exit_price = today_open * (1 - slippage_pct)
                    _close_trade(active_trade, exit_price, today_date,
                                 reason='gap_down', slippage_pct=slippage_pct)
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # ============================================================
                # 우선순위 2: 손절 (장중 저가) — target 미도달 상태에서만
                # (target 도달 후에는 trailing stop이 손절 역할)
                # ============================================================
                if not active_trade.target_hit and today_low <= stop_price:
                    exit_price = stop_price * (1 - slippage_pct)
                    _close_trade(active_trade, exit_price, today_date,
                                 reason='stop_loss', slippage_pct=slippage_pct)
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # Phase C: 카테고리별 trailing 비율 (Build Alpha 연구)
                trailing_pct = CATEGORY_TRAILING_PCT.get(
                    active_trade.category, TRAILING_STOP_PCT
                )

                # ============================================================
                # 우선순위 3: 목표가 도달 시 50% 익절 (한 번만)
                # ============================================================
                if not active_trade.target_hit and today_high >= target_price:
                    active_trade.target_hit = True
                    active_trade.partial_done = True
                    active_trade.partial_exit_price = target_price * (1 - slippage_pct)
                    # 트레일링 스탑 초기화 (카테고리별 % 적용)
                    active_trade.trail_stop_price = (
                        active_trade.max_close_during_hold * (1 - trailing_pct)
                    )
                    # 50%만 청산, 나머지 50%는 계속 보유 → 다른 청산 조건 평가 진행

                # ============================================================
                # 우선순위 4: 트레일링 스탑 (목표 도달 후만, 카테고리별 %)
                # ============================================================
                if active_trade.target_hit:
                    new_trail = active_trade.max_close_during_hold * (1 - trailing_pct)
                    active_trade.trail_stop_price = max(
                        active_trade.trail_stop_price, new_trail
                    )
                    # 트레일링 갭다운
                    if GAP_DOWN_EXIT_AT_OPEN and today_open <= active_trade.trail_stop_price:
                        exit_price = today_open * (1 - slippage_pct)
                        _close_trade(active_trade, exit_price, today_date,
                                     reason='trailing_gap', slippage_pct=slippage_pct)
                        trades.append(active_trade)
                        active_trade = None
                        continue
                    # 트레일링 장중 저가
                    if today_low <= active_trade.trail_stop_price:
                        exit_price = active_trade.trail_stop_price * (1 - slippage_pct)
                        _close_trade(active_trade, exit_price, today_date,
                                     reason='trailing', slippage_pct=slippage_pct)
                        trades.append(active_trade)
                        active_trade = None
                        continue

                # ============================================================
                # 우선순위 5: First-day -3% 룰 (Phase C: 추세/돌파 카테고리만)
                # 평균회귀/지지반등은 작은 음봉도 정상이라 미적용
                # ============================================================
                if (days_held == 1 and not active_trade.target_hit
                        and active_trade.category in FIRST_DAY_RULE_CATEGORIES):
                    first_day_return = (today_close - active_trade.entry_price) / active_trade.entry_price
                    if first_day_return <= FIRST_DAY_LOSS_PCT:
                        next_idx = current_idx + 1
                        if next_idx < len(df):
                            next_row = df.iloc[next_idx]
                            next_date = str(next_row.name.date()) if hasattr(next_row.name, 'date') else ''
                            exit_price = next_row['Open'] * (1 - slippage_pct)
                            _close_trade(active_trade, exit_price, next_date,
                                         reason='first_day_3pct', slippage_pct=slippage_pct)
                            trades.append(active_trade)
                            active_trade = None
                            continue

                # ============================================================
                # 우선순위 6: 최대 보유일 초과
                # ============================================================
                if days_held >= active_trade.hold_days_max:
                    exit_price = today_close * (1 - slippage_pct)
                    _close_trade(active_trade, exit_price, today_date,
                                 reason='time_exit', slippage_pct=slippage_pct)
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
                category=strategy.category,  # Phase C: 카테고리별 청산용
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
            last_date = str(last.name.date()) if hasattr(last.name, 'date') else ''
            exit_price = last['Close'] * (1 - slippage_pct)
            _close_trade(active_trade, exit_price, last_date,
                         reason='forced_close', slippage_pct=slippage_pct)
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

    # PF 95% 신뢰구간 (bootstrap, deterministic seed)
    if len(pnls) >= 5:
        lo, hi = bootstrap_pf_ci(pnls, n_bootstrap=1000)
        report.pf_ci_lower = round(lo, 2)
        report.pf_ci_upper = round(hi, 2)
        # 진짜 알파: 95% CI 하한 > 1.0 (PF가 거의 확실히 1보다 큼)
        report.pf_significant = lo > 1.0

    # MDD (누적 수익 기준, %)
    cumulative = np.cumsum(pnls)
    peak = np.maximum.accumulate(cumulative)
    drawdown = cumulative - peak
    report.max_drawdown = float(np.min(drawdown)) if len(drawdown) > 0 else 0

    # Sharpe (일간 수익률 기준, 연환산)
    if len(pnls) > 1 and np.std(pnls) > 0:
        report.sharpe_ratio = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252 / max(report.avg_hold_days, 1))
    else:
        report.sharpe_ratio = 0

    # Sortino (하방 변동성만, trend-following 표준)
    pnls_arr = np.array(pnls)
    downside = pnls_arr[pnls_arr < 0]
    if len(downside) > 1 and np.std(downside) > 0:
        report.sortino_ratio = (np.mean(pnls) / np.std(downside)) * np.sqrt(252 / max(report.avg_hold_days, 1))
    else:
        report.sortino_ratio = 0

    # Calmar = 연간 수익률 / MDD
    if report.max_drawdown < 0:
        report.calmar_ratio = abs(report.total_return / report.max_drawdown)
    else:
        report.calmar_ratio = 999

    # WorldQuant Fitness (Phase D)
    turnover_proxy = len(pnls) / max(report.avg_hold_days * 252 / 365, 1)
    fitness_returns = abs(report.total_return)
    if fitness_returns > 0:
        report.fitness_score = float(
            np.sqrt(fitness_returns / max(turnover_proxy, 0.125)) * abs(report.sharpe_ratio)
        )
    else:
        report.fitness_score = 0

    # Deflated Sharpe Ratio (Phase B, López de Prado)
    # 우리는 37개 전략 테스트 = N_trials = 37
    if len(pnls) >= 5 and report.sharpe_ratio > 0:
        try:
            from scipy.stats import skew, kurtosis as ks
            pnl_skew = float(skew(pnls)) if len(pnls) > 3 else 0.0
            pnl_kurt = float(ks(pnls, fisher=False)) if len(pnls) > 3 else 3.0
            report.deflated_sharpe = deflated_sharpe_ratio(
                sharpe=report.sharpe_ratio,
                n_trials=37,  # HollyKR 전략 수
                skewness=pnl_skew,
                kurtosis=pnl_kurt,
                n_obs=len(pnls),
            )
        except Exception:
            report.deflated_sharpe = 0.0

    return report


# ============================================================================
# OHLCV 수집
# ============================================================================

def _load_universe_ohlcv(universe: pd.DataFrame, days: int = 300,
                          end_date: Optional[pd.Timestamp] = None) -> Dict[str, pd.DataFrame]:
    """유니버스 전종목 OHLCV 로드 (캐시 활용).

    Args:
        end_date: 백테스트 기준일 (None=오늘). 지정 시 모든 OHLCV가 end_date까지로 잘림.
                  비결정성 방지 (cache 자라도 동일 결과 보장)
    """
    ohlcv_dict = {}
    total = len(universe)

    for i, (_, row) in enumerate(universe.iterrows(), 1):
        ticker = row['Code']
        df = get_ohlcv(ticker, days=days, use_cache=True)
        if df is not None and len(df) > 0:
            # end_date 고정으로 결정성 보장
            if end_date is not None:
                df = df[df.index <= end_date]
            if len(df) > 0:
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
    significant_count = 0  # 통계적으로 진짜 알파 (PF lower CI > 1.0)

    for name in strategy_names:
        tr = train_reports.get(name)
        te = test_reports.get(name)

        # Train 판정 (느슨)
        train_pass = (tr and tr.total_trades >= 10
                      and tr.win_rate >= 0.4 and tr.profit_factor >= 1.2)
        # Test 판정 (Phase A 강화: PF + Sharpe + MDD 동시)
        test_pass = (te and te.total_trades >= 30
                     and te.win_rate >= 0.4
                     and te.profit_factor >= 1.2
                     and te.sharpe_ratio >= 1.0       # 신규: Sharpe ≥ 1.0
                     and te.max_drawdown > -0.50)     # 신규: MDD > -50% (cumsum)
        # ALPHA 판정 (Phase A 강화: + Sharpe ≥ 1.5)
        test_alpha = (te and te.total_trades >= 30
                      and te.pf_significant
                      and te.win_rate >= 0.4
                      and te.sharpe_ratio >= 1.5      # 신규: Sharpe 1.5+
                      and te.max_drawdown > -0.50)

        if test_alpha:
            verdict = 'ALPHA'
            pass_count += 1
            significant_count += 1
        elif test_pass:
            verdict = 'PASS'
            pass_count += 1
        elif train_pass and not test_pass:
            verdict = 'OVERFIT'
            overfit_count += 1
        else:
            verdict = 'FAIL'

        row = {
            '판정': verdict,
            '전략': name[:20],
            '등급': tr.grade if tr else (te.grade if te else ''),
        }

        # Train 열 (요약)
        if tr and tr.total_trades > 0:
            row['Tr거래'] = tr.total_trades
            row['TrPF'] = f'{tr.profit_factor:.2f}'
            row['TrSharpe'] = f'{tr.sharpe_ratio:.1f}'
        else:
            row['Tr거래'] = 0
            row['TrPF'] = '-'
            row['TrSharpe'] = '-'

        # Test 열 (Phase A: PF + Sharpe + Sortino + MDD + Calmar)
        if te and te.total_trades > 0:
            row['Te거래'] = te.total_trades
            row['Te승률'] = f'{te.win_rate:.1%}'
            row['TePF'] = f'{te.profit_factor:.2f}'
            row['PF_CI'] = f'[{te.pf_ci_lower:.2f},{te.pf_ci_upper:.2f}]'
            row['Sharpe'] = f'{te.sharpe_ratio:.2f}'
            row['Sortino'] = f'{te.sortino_ratio:.2f}'
            row['MDD'] = f'{te.max_drawdown:.1%}'
            row['Calmar'] = f'{te.calmar_ratio:.2f}'
            row['Fitness'] = f'{te.fitness_score:.1f}'
            row['Te수익'] = f'{te.total_return:+.0%}'
        else:
            row['Te거래'] = 0
            row['Te승률'] = '-'
            row['TePF'] = '-'
            row['PF_CI'] = '-'
            row['Sharpe'] = '-'
            row['Sortino'] = '-'
            row['MDD'] = '-'
            row['Calmar'] = '-'
            row['Fitness'] = '-'
            row['Te수익'] = '-'

        rows.append(row)

    # 판정 기준 정렬: ALPHA > PASS > OVERFIT > FAIL
    verdict_order = {'ALPHA': 0, 'PASS': 1, 'OVERFIT': 2, 'FAIL': 3}
    rows.sort(key=lambda r: verdict_order.get(r['판정'], 4))

    total_strategies = len(set(r.name for r in reports))
    no_signal = total_strategies - len(strategy_names)

    print(f"\n{'='*110}")
    print(f"전략 백테스트 결과  - Train/Test 분할 (OOS 검증)")
    print(f"{'='*110}")
    print(tabulate(rows, headers='keys', tablefmt='simple', stralign='left'))

    print(f"\n통과(PASS+ALPHA, Test 기준): {pass_count}개 / 전체 {total_strategies}개")
    print(f"  └ 통계적 진짜 알파 (PF 95% CI 하한 > 1.0): {significant_count}개")
    print(f"과적합(OVERFIT  - Train PASS, Test FAIL): {overfit_count}개")
    fail_count = len(strategy_names) - pass_count - overfit_count
    print(f"실패(FAIL): {fail_count}개")

    # ============================================================
    # Phase 9: Survivorship bias 정직성 경고
    # ============================================================
    print("\n" + "=" * 90)
    print("  [!] SURVIVORSHIP BIAS 경고 (Phase 9 - 정직성 보정)")
    print("=" * 90)
    print("  현재 유니버스: '오늘 시점' 시총 1,000억+ 종목 (살아남은 종목 풀)")
    print("  실제 영향:")
    print("    - 200일 동안 상폐된 종목 → 백테스트 풀에서 누락")
    print("    - 200일 전 시총 작았던 종목이 급등하여 현재 1000억+ → '운 좋게' 포함")
    print("    - 결과: Test PF가 실전보다 약 20-30% 부풀려져 있음")
    print()
    print("  보정 추정값 (PF × 0.75 가정):")
    for r in rows[:5]:  # 상위 5개만
        if r.get('TestPF', '-') != '-':
            try:
                pf = float(r['TestPF'])
                adjusted = pf * 0.75
                marker = "★" if r['판정'] == 'ALPHA' else " "
                print(f"    {marker} {r['전략']:<22s} | 보고 PF {pf:.2f} → 추정 실전 PF {adjusted:.2f}")
            except (ValueError, KeyError):
                continue
    print()
    print("  진짜 알파 판정도 보수적으로 해석 필요:")
    print("    - PF 95% CI 하한 × 0.75 > 1.0 인 전략만 진짜 alpha")
    print("    - 한국거래소 historical 종목 마스터 통합 시 정확 측정 가능 (Phase 9 미완)")
    print("=" * 90)
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
            'profit_factor': round(r.profit_factor, 2),
            'pf_ci_lower': round(r.pf_ci_lower, 2), 'pf_ci_upper': round(r.pf_ci_upper, 2),
            'mdd': round(r.max_drawdown, 4),
            'sharpe': round(r.sharpe_ratio, 2),
            'sortino': round(r.sortino_ratio, 2),
            'calmar': round(r.calmar_ratio, 2),
            'fitness': round(r.fitness_score, 2),
            'avg_hold_days': round(r.avg_hold_days, 1),
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
# 워크포워드
# ============================================================================

def run_walk_forward(num_windows: int = 4, window_offset_days: int = 60,
                      test_days: int = 200, sample_size: int = 200,
                      entry_mode: str = 'close', strategy_filter: str = None,
                      save: bool = False) -> Dict[str, list]:
    """워크포워드 검증: 다중 윈도우로 각 전략 평가.

    Args:
        num_windows: 윈도우 수 (기본 4)
        window_offset_days: 윈도우 간 슬라이딩 거리 (기본 60일)
        test_days: 각 윈도우 백테스트 기간

    Returns:
        {strategy_name: [report_w1, report_w2, ...]}
    """
    print("=" * 70)
    print(f"  워크포워드 백테스트: {num_windows} 윈도우 × {test_days}일 × {window_offset_days}일 슬라이딩")
    print("=" * 70)

    overall_start = time.time()

    # 1. OHLCV 한 번만 로드 (모든 윈도우에서 재사용)
    universe = get_universe()
    if sample_size > 0 and sample_size < len(universe):
        universe = universe.nlargest(sample_size, 'MarketCap').reset_index(drop=True)
        print(f"  유니버스: 시총 상위 {sample_size}개")

    print(f"\n  OHLCV 로드 (최대 LOOKBACK_DAYS={LOOKBACK_DAYS} + offset)...")
    full_ohlcv = _load_universe_ohlcv(
        universe, days=LOOKBACK_DAYS + num_windows * window_offset_days,
        end_date=None
    )
    print(f"  로드 완료: {len(full_ohlcv)}개 종목")
    flush_cache()

    # 2. 각 윈도우 실행
    today = pd.Timestamp.now().normalize()
    window_results: Dict[str, list] = {}  # {name: [test_report, ...]}
    aggregated_test_trades: Dict[str, list] = {}  # {name: [trades, ...]}

    for w in range(num_windows):
        window_end = today - pd.Timedelta(days=w * window_offset_days)
        print(f"\n{'─' * 70}")
        print(f"  윈도우 {w+1}/{num_windows} | end_date = {window_end.date()}")
        print(f"{'─' * 70}")

        # 윈도우별 OHLCV 슬라이싱
        windowed_ohlcv = {
            t: df[df.index <= window_end]
            for t, df in full_ohlcv.items()
        }
        # 길이 부족 종목 제외
        windowed_ohlcv = {
            t: df for t, df in windowed_ohlcv.items()
            if len(df) >= test_days + 60
        }

        reports = run_backtest(
            test_days=test_days, strategy_filter=strategy_filter,
            save=False, sample_size=sample_size, split=True,
            entry_mode=entry_mode, end_date=window_end,
            ohlcv_dict=windowed_ohlcv, universe=universe,
        )

        # Test 리포트만 모음
        for r in reports:
            if r.period == 'Test':
                window_results.setdefault(r.name, []).append(r)
                aggregated_test_trades.setdefault(r.name, []).extend(r.trades)

    # 3. 집계 출력
    elapsed = time.time() - overall_start
    print(f"\n{'=' * 70}")
    print(f"  워크포워드 종합 결과 (4 윈도우 Test 누적)")
    print(f"{'=' * 70}")

    summary_rows = []
    alpha_count = 0
    consistent_count = 0  # 4 윈도우 중 3+ 통과

    for name, w_reports in window_results.items():
        if not w_reports:
            continue
        # 윈도우별 PASS 횟수 (Phase A 강화: PF + Sharpe + MDD)
        wins = sum(1 for r in w_reports
                   if r.total_trades >= 5
                   and r.profit_factor >= 1.2
                   and r.win_rate >= 0.4
                   and r.sharpe_ratio >= 1.0
                   and r.max_drawdown > -0.50)
        # 누적 trades로 통계 의미 평가
        all_trades = aggregated_test_trades.get(name, [])
        if not all_trades:
            continue
        all_pnls = [t.pnl_pct for t in all_trades]
        total = len(all_pnls)
        agg_wr = sum(1 for p in all_pnls if p > 0) / total if total else 0
        agg_pf = (sum(p for p in all_pnls if p > 0)
                  / abs(sum(p for p in all_pnls if p <= 0))
                  if any(p <= 0 for p in all_pnls) else 999.0)
        agg_lo, agg_hi = bootstrap_pf_ci(all_pnls, n_bootstrap=1000) if total >= 5 else (0, 0)

        # 누적 Sharpe / MDD / Sortino
        pnls_arr = np.array(all_pnls)
        avg_hold = np.mean([t.hold_days for t in all_trades]) if all_trades else 1
        agg_sharpe = (np.mean(pnls_arr) / np.std(pnls_arr)) * np.sqrt(252 / max(avg_hold, 1)) if len(pnls_arr) > 1 and np.std(pnls_arr) > 0 else 0
        downside = pnls_arr[pnls_arr < 0]
        agg_sortino = (np.mean(pnls_arr) / np.std(downside)) * np.sqrt(252 / max(avg_hold, 1)) if len(downside) > 1 and np.std(downside) > 0 else 0
        cumulative = np.cumsum(all_pnls)
        peak = np.maximum.accumulate(cumulative)
        agg_mdd = float(np.min(cumulative - peak)) if len(cumulative) > 0 else 0
        agg_total_ret = sum(all_pnls)
        agg_calmar = abs(agg_total_ret / agg_mdd) if agg_mdd < 0 else 999

        # ALPHA 판정 (Phase A 강화: + Sharpe ≥ 1.5 + MDD > -50%)
        if (total >= 30 and agg_lo > 1.0 and wins >= 3
                and agg_sharpe >= 1.5 and agg_mdd > -0.50):
            verdict = 'ALPHA'
            alpha_count += 1
            consistent_count += 1
        elif wins >= 3 and total >= 20 and agg_sharpe >= 1.0:
            verdict = 'CONSISTENT'
            consistent_count += 1
        elif total >= 20 and agg_pf >= 1.2:
            verdict = 'BORDERLINE'
        else:
            verdict = 'FAIL'

        summary_rows.append({
            '판정': verdict,
            '전략': name[:22],
            '윈도우': f'{wins}/{num_windows}',
            '거래': total,
            '승률': f'{agg_wr:.1%}',
            'PF': f'{agg_pf:.2f}',
            'PF_CI95': f'[{agg_lo:.2f},{agg_hi:.2f}]',
            'Sharpe': f'{agg_sharpe:.2f}',
            'Sortino': f'{agg_sortino:.2f}',
            'MDD': f'{agg_mdd:.0%}',
            'Calmar': f'{agg_calmar:.2f}',
            '수익': f'{agg_total_ret:+.0%}',
        })

    summary_rows.sort(key=lambda r: {'ALPHA': 0, 'CONSISTENT': 1, 'BORDERLINE': 2, 'FAIL': 3}[r['판정']])

    print(tabulate(summary_rows, headers='keys', tablefmt='simple', stralign='left'))
    print(f"\n진짜 알파 (Sharpe 1.5+ AND PF CI 하한 > 1.0 AND 4중 3+ AND MDD > -50%): {alpha_count}개")
    print(f"일관성 있는 PASS (Sharpe 1.0+ AND 4중 3+): {consistent_count}개")

    # Phase B: Probability of Backtest Overfitting (López de Prado)
    pnls_per_strategy = {
        name: [t.pnl_pct for t in trades]
        for name, trades in aggregated_test_trades.items()
        if len(trades) >= 16
    }
    if len(pnls_per_strategy) >= 2:
        pbo = probability_backtest_overfitting(pnls_per_strategy)
        pbo_status = "양호" if pbo < 0.5 else "과적합 의심"
        print(f"\n[PBO] Probability of Backtest Overfitting: {pbo:.0%} [{pbo_status}]")
        print(f"      (Lopez de Prado 2014. <50% 양호, >=50% 과적합 의심)")

    print(f"\n총 소요 시간: {elapsed:.1f}초")

    if save:
        today_str = datetime.now().strftime('%Y-%m-%d')
        wf_path = OUTPUT_DIR / f'walkforward_summary_{today_str}.csv'
        pd.DataFrame(summary_rows).to_csv(wf_path, index=False, encoding='utf-8-sig')
        print(f"  CSV 저장: {wf_path}")

    return window_results


# ============================================================================
# 메인
# ============================================================================

def run_backtest(test_days: int = 120, strategy_filter: str = None,
                  save: bool = False, sample_size: int = 200,
                  split: bool = True, entry_mode: str = 'open',
                  end_date: Optional[pd.Timestamp] = None,
                  ohlcv_dict: Optional[Dict[str, pd.DataFrame]] = None,
                  universe: Optional[pd.DataFrame] = None) -> List[StrategyReport]:
    """
    백테스트 실행.

    Args:
        test_days: 테스트 기간 (거래일)
        strategy_filter: 특정 전략만 (이름)
        save: CSV 저장 여부
        sample_size: 유니버스 샘플 크기 (0=전체, N=시총 상위 N개)
        split: True면 Train(70%)/Test(30%) OOS 분할 검증
        end_date: 백테스트 기준일 (None=오늘). 비결정성 방지용
        ohlcv_dict, universe: 외부 주입 (워크포워드에서 재사용)
    """
    print("=" * 60)
    print("  HollyKR 백테스트 엔진")
    print(f"  테스트 기간: 최근 {test_days}거래일")
    if end_date is not None:
        print(f"  기준일 (end_date): {end_date.date() if hasattr(end_date, 'date') else end_date}")
    if split:
        train_days = int(test_days * 0.7)
        test_days_oos = test_days - train_days
        print(f"  OOS 분할: Train {train_days}일 / Test {test_days_oos}일")
    print("=" * 60)

    start = time.time()

    # 1. 유니버스 (외부 주입 우선)
    if universe is None:
        universe = get_universe()
        if sample_size > 0 and sample_size < len(universe):
            universe = universe.nlargest(sample_size, 'MarketCap').reset_index(drop=True)
            print(f"  샘플링: 시총 상위 {sample_size}개 종목")

    # 2. OHLCV 로드 (외부 주입 우선, 워크포워드에서 재사용)
    if ohlcv_dict is None:
        print(f"\n  OHLCV 로드 중 ({len(universe)}개 종목)...")
        ohlcv_dict = _load_universe_ohlcv(universe, days=LOOKBACK_DAYS, end_date=end_date)
        print(f"  OHLCV 로드 완료: {len(ohlcv_dict)}개 종목")

    # OHLCV 캐시 저장
    flush_cache()

    # 3. 전략 목록
    all_strategies = list(ALL_STRATEGIES)  # Phase 7 신규 5개 포함, 총 37개
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
            # Phase B: Train/Test 사이 5일 embargo (López de Prado purging)
            # 추세 추종 전략은 평균 보유 5-10일이라 train의 끝과 test 시작이 겹치면 leakage
            embargo_days = 5
            # --- Train 기간: 처음 70% (과거 쪽) ---
            # Train 끝나는 시점이 test_days_oos + embargo (test 시작 5일 전)
            train_trades = _simulate_strategy(
                strategy, ohlcv_dict, universe,
                test_days=test_days,
                start_offset=0,
                end_offset=test_days_oos + embargo_days,  # embargo로 train 끝 5일 빼기
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
    parser.add_argument('--walk-forward', type=int, default=0,
                        help='워크포워드 윈도우 수 (0=비활성, 4=권장). 결정성 + 다중 윈도우 검증')
    parser.add_argument('--window-offset', type=int, default=60,
                        help='워크포워드 윈도우 슬라이딩 거리 (일, 기본 60)')

    args = parser.parse_args()
    if args.walk_forward > 0:
        run_walk_forward(
            num_windows=args.walk_forward,
            window_offset_days=args.window_offset,
            test_days=args.days,
            sample_size=args.sample,
            entry_mode=args.entry,
            strategy_filter=args.strategy,
            save=args.csv,
        )
    else:
        run_backtest(
            test_days=args.days,
            strategy_filter=args.strategy,
            save=args.csv,
            sample_size=args.sample,
            split=not args.no_split,
            entry_mode=args.entry,
        )
