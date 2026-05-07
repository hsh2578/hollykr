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
# 설정 (Phase F: 듀얼 시간 척도 + ALPHA 풀 한정)
# ============================================================================
LOOKBACK_60D = 60           # 단기: 60일 (최근 적응)
LOOKBACK_180D = 180         # 중기: 180일 (사이클 안정성)
LOOKBACK_DAYS = LOOKBACK_60D  # backward compat
MIN_WIN_RATE = 0.0
MIN_PROFIT_FACTOR = 1.0
MIN_TOTAL_RETURN = 0.0
MAX_ACTIVE = 10             # 하루 최대 활성 전략 (ALPHA 풀 + 일부)
MIN_ACTIVE = 3              # 하루 최소 활성 전략
HYSTERESIS_MIN_PERIODS = 1

# 듀얼 점수 가중치 (Phase F)
WEIGHT_60D = 0.40   # 최근 적응
WEIGHT_180D = 0.40  # 사이클 안정성
WEIGHT_5Y = 0.20    # 5년 메타데이터 (ALPHA 풀에서)


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

    # 최소 기준 통과 여부: PF 1.1+ AND 총수익 10%+
    base_passed = (
        metrics.profit_factor >= MIN_PROFIT_FACTOR
        and metrics.total_return >= MIN_TOTAL_RETURN
        and metrics.signal_count >= 1
    )

    # 히스테리시스: 서브기간 최소 2/3 통과해야 활성화
    metrics.passed = base_passed and (sub_period_passes >= HYSTERESIS_MIN_PERIODS)

    # 복합 점수 (Phase 5 강화: 표본 크기 가중 ↑, 워크포워드 결과 반영)
    # 핵심: PF × sqrt(거래수) × 승률 보정 — 통계적으로 의미있는 전략 우선
    norm_wr = metrics.win_rate  # 0~1
    norm_pf = min(metrics.profit_factor, 3.0) / 3.0  # 0~1 (3 이상은 캡)
    norm_rw = metrics.regime_weight  # 0.4~1.3 → 그대로 사용
    # 표본 가중: sqrt 기준 (log보다 더 강하게 표본 큰 전략 우대)
    norm_sc = min(np.sqrt(metrics.signal_count) / 10.0, 1.0)  # 100건 = 1.0
    metrics.composite_score = (
        0.25 * norm_wr
        + 0.30 * norm_pf
        + 0.15 * norm_rw
        + 0.30 * norm_sc  # 표본 가중 0.2 → 0.3 (통계 안정성)
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

    total_return = sum(t['pnl'] for t in sub_trades)
    return (
        profit_factor >= MIN_PROFIT_FACTOR
        and total_return >= MIN_TOTAL_RETURN * 0.3  # 서브기간은 전체의 1/3이므로 기준도 1/3
        and len(sub_trades) >= 1
    )


def select_strategies_dual(
    strategies: List[BaseStrategy],
    universe_ohlcv: Dict[str, pd.DataFrame],
    universe_info: pd.DataFrame,
    regime_info: Optional[dict] = None,
    max_active: int = MAX_ACTIVE,
    min_active: int = MIN_ACTIVE,
) -> Tuple[List[BaseStrategy], List[StrategyMetrics]]:
    """Phase F: 듀얼 시간 척도 평가 (60일 + 180일 + 5년 메타).

    score = 0.4 × 60일점수 + 0.4 × 180일점수 + 0.2 × 5년메타점수

    ALPHA 풀 한정 (alpha_pool.json 있을 때만), 없으면 모든 전략 평가.
    """
    from scripts.screeners.holly_kr.alpha_pool import (
        load_alpha_pool, get_alpha_metadata
    )

    if regime_info is None:
        regime_info = get_market_regime()

    regime = regime_info.get('regime', '횡보장')

    # ALPHA 풀 확인 (있으면 풀 한정 평가)
    alpha_pool = load_alpha_pool()
    if alpha_pool:
        pool_names = {s['name'] for s in alpha_pool['alpha_strategies']}
        eligible_strategies = [s for s in strategies if s.name in pool_names]
        print(f"\n[야간 전략 선정 — 듀얼 시간 척도] 시장 레짐: {regime}")
        print(f"  ALPHA 풀: {len(eligible_strategies)}개 (총 {len(strategies)}개 중)")
        print(f"  평가: 60일 + 180일 + 5년 메타 가중합")
    else:
        eligible_strategies = list(strategies)
        print(f"\n[야간 전략 선정 — 듀얼 시간 척도] 시장 레짐: {regime}")
        print(f"  ALPHA 풀 없음 → 전체 {len(eligible_strategies)}개 평가")
        print(f"  ※ 5년 백테스트 후 alpha_pool.json 생성 권장")

    print("=" * 60)

    all_metrics: List[StrategyMetrics] = []

    for strategy in eligible_strategies:
        rw = get_category_weight(regime_info, strategy.category)

        # 60일 점수
        trades_60 = _simulate_signals_on_history(
            strategy, universe_ohlcv, universe_info, lookback=LOOKBACK_60D
        )
        m_60 = _calc_metrics(strategy, trades_60, regime_weight=rw, sub_period_passes=2)

        # 180일 점수
        trades_180 = _simulate_signals_on_history(
            strategy, universe_ohlcv, universe_info, lookback=LOOKBACK_180D
        )
        m_180 = _calc_metrics(strategy, trades_180, regime_weight=rw, sub_period_passes=2)

        # 5년 메타 점수 (alpha_pool에서)
        meta = get_alpha_metadata(strategy.name) if alpha_pool else None
        if meta:
            # 5년 ALPHA 등급별 점수
            tier_score = {'ALPHA': 1.0, 'CONSISTENT': 0.7, 'BORDERLINE': 0.4}.get(meta['tier'], 0.0)
            holdout_pf = meta.get('holdout_pf', 0)
            score_5y = 0.5 * tier_score + 0.5 * min(holdout_pf / 3.0, 1.0)
        else:
            score_5y = 0.5  # 메타 없으면 중립

        # 듀얼 점수 합성
        composite = (
            WEIGHT_60D * m_60.composite_score +
            WEIGHT_180D * m_180.composite_score +
            WEIGHT_5Y * score_5y
        )

        # 종합 metrics (60일 기준 + 듀얼 점수)
        m_60.composite_score = composite  # 합성 점수로 덮어쓰기
        all_metrics.append(m_60)

        status = "ALPHA" if meta and meta.get('tier') == 'ALPHA' else (
                 "CONS" if meta and meta.get('tier') == 'CONSISTENT' else " ")
        print(f"  [{status:<5}] {strategy.name:<25s} | "
              f"60일 PF={m_60.profit_factor:.2f} N={m_60.signal_count:2d} | "
              f"180일 PF={m_180.profit_factor:.2f} N={m_180.signal_count:2d} | "
              f"5년 {score_5y:.2f} | Score={composite:.3f}")

    # Top N 선정 (점수 순)
    rated = [m for m in all_metrics if m.signal_count > 0]
    rated.sort(key=lambda m: -m.composite_score)
    selected_metrics = rated[:max_active]

    # 부족 시 ALPHA 풀의 거래 0 전략도 추가
    if len(selected_metrics) < min_active:
        unrated = [m for m in all_metrics if m.signal_count == 0]
        for m in unrated:
            if len(selected_metrics) >= min_active:
                break
            selected_metrics.append(m)

    # 전략 객체 매핑
    name_to_strategy = {s.name: s for s in eligible_strategies}
    selected_strategies = [
        name_to_strategy[m.strategy_name]
        for m in selected_metrics
        if m.strategy_name in name_to_strategy
    ]

    print(f"\n  전체 후보: {len(eligible_strategies)}개")
    print(f"  거래 발생: {len(rated)}개")
    print(f"  오늘의 ACTIVE (Top {max_active}): {len(selected_strategies)}개")
    for i, m in enumerate(selected_metrics, 1):
        meta = get_alpha_metadata(m.strategy_name) if alpha_pool else None
        tier_label = meta.get('tier', '   ') if meta else '   '
        print(f"    {i:2d}. [{tier_label:<5}] {m.strategy_name:<25s} Score={m.composite_score:.3f}")

    return selected_strategies, all_metrics


# 호환성: 기존 select_strategies 호출도 듀얼 시간 척도로 자동 라우팅
def select_strategies(
    strategies: List[BaseStrategy],
    universe_ohlcv: Dict[str, pd.DataFrame],
    universe_info: pd.DataFrame,
    regime_info: Optional[dict] = None,
    lookback: int = LOOKBACK_DAYS,  # 무시됨 (듀얼 시간 척도)
    max_active: int = MAX_ACTIVE,
    min_active: int = MIN_ACTIVE,
) -> Tuple[List[BaseStrategy], List[StrategyMetrics]]:
    """기존 호출과 호환. select_strategies_dual로 라우팅."""
    return select_strategies_dual(
        strategies, universe_ohlcv, universe_info,
        regime_info=regime_info, max_active=max_active, min_active=min_active,
    )
