"""
야간 전략 선정 시스템 (v4.0 Section 5)

매일 장 마감 후 실행:
1. 최근 60거래일(~3개월) 룩백 백테스트로 각 전략 성과 측정
2. 최소 기준(승률 40%, 수익팩터 1.2) 미달 전략 탈락
3. 히스테리시스: 3개 서브기간(60-41, 40-21, 20-1) 중 2개 이상 통과 필요
4. 시장 레짐 가중치 적용
5. 내일 활성 전략 Top N 선정 (최대 10, 최소 3)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.filters.market_filter import (
    get_market_regime,
    get_category_weight,
)

# ============================================================================
# 설정
# ============================================================================
LOOKBACK_DAYS = 60          # 룩백 기간 (거래일, 약 3개월)
MIN_WIN_RATE = 0.40         # 승률 최소 40%
MIN_PROFIT_FACTOR = 1.2     # 수익팩터 최소 1.2
MAX_ACTIVE = 10             # 하루 최대 활성 전략
MIN_ACTIVE = 3              # 하루 최소 활성 전략
HYSTERESIS_MIN_PERIODS = 2  # 활성화: 3개 서브기간 중 최소 2개 통과 필요


@dataclass
class StrategyMetrics:
    """전략별 백테스트 성과 지표."""
    strategy_name: str
    category: str
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_rr_ratio: float = 0.0
    signal_count: int = 0
    total_return: float = 0.0
    regime_weight: float = 1.0
    composite_score: float = 0.0
    passed: bool = False
    sub_period_passes: int = 0  # 히스테리시스: 통과한 서브기간 수 (0~3)


def _simulate_signals_on_history(
    strategy: BaseStrategy,
    universe_ohlcv: Dict[str, pd.DataFrame],
    universe_info: pd.DataFrame,
    lookback: int = LOOKBACK_DAYS,
) -> List[Dict]:
    """
    최근 lookback 거래일에 대해 전략의 시그널을 시뮬레이션.

    각 거래일마다 전략을 돌려서 시그널이 발생했다면,
    그 다음날 시가로 진입 -> target/stop_loss 도달 여부 판정.

    Returns:
        List of trade results: [{'pnl': float, 'rr_ratio': float, 'win': bool}, ...]
    """
    trades = []

    for _, row in universe_info.iterrows():
        ticker = row['Code']
        name = row.get('Name', ticker)
        sector = row.get('Sector', '')

        df = universe_ohlcv.get(ticker)
        if df is None or len(df) < lookback + 30:
            continue

        # 최근 lookback+보유기간 범위의 데이터에서 시뮬레이션
        for offset in range(lookback, 0, -1):
            # offset일 전 시점까지의 데이터로 스캔
            hist = df.iloc[:-offset] if offset > 0 else df
            if len(hist) < 30:
                continue

            try:
                entry_price = hist['Close'].iloc[-1]
                sig = strategy.scan(
                    hist, ticker, name,
                    sector=sector, entry_price=entry_price,
                )
            except Exception:
                sig = None

            if sig is None:
                continue

            # 다음날부터 보유기간 동안의 실제 가격으로 결과 판정
            future_start = len(df) - offset
            future_end = min(future_start + sig.hold_days_max, len(df))
            if future_start >= len(df):
                continue

            future = df.iloc[future_start:future_end]
            if len(future) == 0:
                continue

            # 진입가 = 다음날 시가
            actual_entry = future['Open'].iloc[0]
            if actual_entry <= 0:
                continue

            # 보유 기간 중 최고/최저
            max_high = future['High'].max()
            min_low = future['Low'].min()

            # 손절 도달 여부
            stop_hit = min_low <= sig.stop_loss_price
            # 목표 도달 여부
            target_hit = max_high >= sig.target_price

            if stop_hit and target_hit:
                # 둘 다 도달 시 손절 우선 (보수적)
                pnl = sig.stop_loss_pct
                win = False
            elif target_hit:
                pnl = sig.target_pct
                win = True
            elif stop_hit:
                pnl = sig.stop_loss_pct
                win = False
            else:
                # 보유기간 종료 시 마지막 종가로 청산
                exit_price = future['Close'].iloc[-1]
                pnl = (exit_price - actual_entry) / actual_entry
                win = pnl > 0

            trades.append({
                'pnl': pnl,
                'rr_ratio': sig.rr_ratio,
                'win': win,
            })

    return trades


def _calc_metrics(
    strategy: BaseStrategy,
    trades: List[Dict],
    regime_weight: float,
    sub_period_passes: int = 0,
) -> StrategyMetrics:
    """거래 결과로부터 성과 지표 계산.

    Args:
        sub_period_passes: 히스테리시스 - 3개 서브기간 중 통과한 수.
            HYSTERESIS_MIN_PERIODS(2) 이상이어야 최종 passed=True.
    """
    metrics = StrategyMetrics(
        strategy_name=strategy.name,
        category=strategy.category,
        regime_weight=regime_weight,
        sub_period_passes=sub_period_passes,
    )

    if not trades:
        return metrics

    metrics.signal_count = len(trades)

    wins = [t for t in trades if t['win']]
    losses = [t for t in trades if not t['win']]

    metrics.win_rate = len(wins) / len(trades)

    total_profit = sum(t['pnl'] for t in wins) if wins else 0.0
    total_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.0001

    metrics.profit_factor = total_profit / total_loss if total_loss > 0 else 0.0
    metrics.avg_rr_ratio = np.mean([t['rr_ratio'] for t in trades]) if trades else 0.0
    metrics.total_return = sum(t['pnl'] for t in trades)

    # 최소 기준 통과 여부 (기본 기준)
    base_passed = (
        metrics.win_rate >= MIN_WIN_RATE
        and metrics.profit_factor >= MIN_PROFIT_FACTOR
        and metrics.signal_count >= 1
    )

    # 히스테리시스: 서브기간 최소 2/3 통과해야 활성화
    metrics.passed = base_passed and (sub_period_passes >= HYSTERESIS_MIN_PERIODS)

    # 복합 점수: 정규화된 가중합 (스케일 통일)
    norm_wr = metrics.win_rate  # 0~1
    norm_pf = min(metrics.profit_factor, 3.0) / 3.0  # 0~1 (3 이상은 캡)
    norm_rw = metrics.regime_weight  # 0.4~1.3 → 그대로 사용
    norm_sc = np.log1p(metrics.signal_count) / np.log1p(100)  # 0~1 (100건 기준)
    metrics.composite_score = (
        0.3 * norm_wr
        + 0.3 * norm_pf
        + 0.2 * norm_rw
        + 0.2 * min(norm_sc, 1.0)
    )

    return metrics


def _evaluate_sub_period(
    strategy: BaseStrategy,
    trades: List[Dict],
    lookback: int,
    period_start: int,
    period_end: int,
) -> bool:
    """
    서브기간에 해당하는 거래만 필터링하여 기준 통과 여부 판정.

    trades는 전체 lookback 기간의 거래 결과 리스트.
    period_start, period_end는 전체 lookback 내 오프셋 (예: 60~41, 40~21, 20~1).
    거래 인덱스는 trades 리스트 순서로 균등 분할.
    """
    if not trades:
        return False

    total = len(trades)
    # 거래를 lookback 기간에 비례하여 3등분
    ratio_start = (lookback - period_start) / lookback
    ratio_end = (lookback - period_end + 1) / lookback
    idx_start = int(total * ratio_start)
    idx_end = int(total * ratio_end)

    sub_trades = trades[idx_start:idx_end]
    if not sub_trades:
        return False

    wins = [t for t in sub_trades if t['win']]
    losses = [t for t in sub_trades if not t['win']]

    win_rate = len(wins) / len(sub_trades)
    total_profit = sum(t['pnl'] for t in wins) if wins else 0.0
    total_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.0001
    profit_factor = total_profit / total_loss if total_loss > 0 else 0.0

    return (
        win_rate >= MIN_WIN_RATE
        and profit_factor >= MIN_PROFIT_FACTOR
        and len(sub_trades) >= 1
    )


def select_strategies(
    strategies: List[BaseStrategy],
    universe_ohlcv: Dict[str, pd.DataFrame],
    universe_info: pd.DataFrame,
    regime_info: Optional[dict] = None,
    lookback: int = LOOKBACK_DAYS,
    max_active: int = MAX_ACTIVE,
    min_active: int = MIN_ACTIVE,
) -> Tuple[List[BaseStrategy], List[StrategyMetrics]]:
    """
    야간 전략 선정.

    Args:
        strategies: 전체 전략 목록
        universe_ohlcv: {ticker: DataFrame} OHLCV 딕셔너리
        universe_info: 유니버스 DataFrame (Code, Name, Sector, ...)
        regime_info: get_market_regime() 결과 (None이면 자동 조회)
        lookback: 룩백 기간 (거래일)
        max_active: 최대 활성 전략 수
        min_active: 최소 활성 전략 수

    Returns:
        (활성 전략 리스트, 전략별 메트릭스 리스트)
    """
    if regime_info is None:
        regime_info = get_market_regime()

    regime = regime_info.get('regime', '횡보장')
    print(f"\n[야간 전략 선정] 시장 레짐: {regime}")
    print(f"  룩백: {lookback}거래일 (3개 서브기간 히스테리시스), "
          f"최소 승률: {MIN_WIN_RATE*100:.0f}%, 최소 PF: {MIN_PROFIT_FACTOR}")
    print("=" * 60)

    # 서브기간 정의 (역순: 오래된 기간부터)
    # Period 1: days 60-41, Period 2: days 40-21, Period 3: days 20-1
    sub_periods = [
        (lookback, lookback - 19),      # Period 1: 가장 오래된 20일
        (lookback - 20, lookback - 39),  # Period 2: 중간 20일
        (20, 1),                         # Period 3: 최근 20일
    ]

    all_metrics: List[StrategyMetrics] = []

    for strategy in strategies:
        # 레짐 가중치
        rw = get_category_weight(regime_info, strategy.category)

        # 전체 룩백 시뮬레이션
        trades = _simulate_signals_on_history(
            strategy, universe_ohlcv, universe_info, lookback=lookback
        )

        # 히스테리시스: 3개 서브기간 각각 통과 여부 판정
        period_passes = 0
        for p_start, p_end in sub_periods:
            if _evaluate_sub_period(strategy, trades, lookback, p_start, p_end):
                period_passes += 1

        # 성과 지표 계산 (서브기간 통과 수 반영)
        m = _calc_metrics(strategy, trades, regime_weight=rw,
                          sub_period_passes=period_passes)
        all_metrics.append(m)

        status = "PASS" if m.passed else "FAIL"
        print(f"  {strategy.name:<25s} | WR={m.win_rate:.1%} PF={m.profit_factor:.2f} "
              f"RR={m.avg_rr_ratio:.2f} N={m.signal_count:3d} "
              f"RW={rw:.1f} Score={m.composite_score:.3f} "
              f"Sub={period_passes}/3 [{status}]")

    # 1단계: 최소 기준 통과 전략
    passed = [m for m in all_metrics if m.passed]

    # 2단계: 복합 점수 기준 정렬
    passed.sort(key=lambda m: -m.composite_score)

    # 3단계: 최대/최소 제한
    if len(passed) > max_active:
        selected_metrics = passed[:max_active]
    elif len(passed) < min_active:
        # 최소 기준 미달이어도 점수 상위 전략 추가
        all_sorted = sorted(all_metrics, key=lambda m: -m.composite_score)
        selected_metrics = list(passed)
        for m in all_sorted:
            if len(selected_metrics) >= min_active:
                break
            if m not in selected_metrics and m.signal_count > 0:
                selected_metrics.append(m)
    else:
        selected_metrics = passed

    # 전략 객체 매핑
    name_to_strategy = {s.name: s for s in strategies}
    selected_strategies = [
        name_to_strategy[m.strategy_name]
        for m in selected_metrics
        if m.strategy_name in name_to_strategy
    ]

    print(f"\n  통과 전략: {len(passed)}개 / 전체 {len(strategies)}개")
    print(f"  활성 전략: {len(selected_strategies)}개")
    for m in selected_metrics:
        print(f"    - {m.strategy_name} (Score={m.composite_score:.3f})")

    return selected_strategies, all_metrics
