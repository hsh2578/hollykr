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
# 설정 (Phase G-7: ALPHA 풀 보존 + 시장 적응 Top 3)
# ============================================================================
LOOKBACK_60D = 60           # 단기: 60일 (최근 적응 — 시장 환경 자동 반영)
LOOKBACK_180D = 180         # 중기: 180일 (사이클 안정성)
LOOKBACK_DAYS = LOOKBACK_60D  # backward compat
MIN_WIN_RATE = 0.0
MIN_PROFIT_FACTOR = 1.0
MIN_TOTAL_RETURN = 0.0
MAX_NON_POOL = 3            # 풀 외 매일 동적 Top N (시장 환경 자동 적응)
MAX_ACTIVE = 5              # ALPHA 풀(2) + 시장 적응(3) = 5 cap
MIN_ACTIVE = 2              # 최소 = ALPHA 풀만이라도 보존
HYSTERESIS_MIN_PERIODS = 1

# 듀얼 점수 가중치 (Phase G-7: 60일 강조 → 최근 시장 빠른 적응)
# 강세장 → trend_following 60일 PF↑ → 자동 진입
# 약세장 → mean_reversion 60일 PF↑ → 자동 진입
# 횡보장 → range/pullback 60일 PF↑ → 자동 진입
WEIGHT_60D = 0.50   # 최근 적응 (강조 — 시장 환경 변화 빠른 반영)
WEIGHT_180D = 0.30  # 사이클 안정성 (노이즈 보정)
WEIGHT_5Y = 0.20    # 5년 메타데이터 (ALPHA 풀 보너스)


@dataclass
class StrategyMetrics:
    """전략별 백테스트 성과 지표 (Phase G-8: BRAIN + López de Prado 통합)."""
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
    # Phase G-8 신규 지표
    sortino: float = 0.0          # Downside-only Sharpe (진짜 위험 측정)
    calmar: float = 0.0           # CAGR / |MDD| (수익/낙폭)
    fitness: float = 0.0          # BRAIN: Sharpe × √(|R|/MDD)
    expectancy_pct: float = 0.0   # 거래당 기대값 (%)
    margin_bps: float = 0.0       # 거래당 평균 수익 (bps, 수수료 후)
    max_drawdown: float = 0.0     # MDD (음수)
    turnover_health: float = 0.0  # 회전율 적정성 (0~1)
    sharpe: float = 0.0           # 기존 Sharpe (참고)


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
    lookback_days: int = 60,
) -> StrategyMetrics:
    """거래 결과로부터 성과 지표 계산 (Phase G-8: BRAIN + López de Prado).

    탈락 기준 X — 모든 전략 점수만으로 순위 (사용자 요청).
    BRAIN Fitness 정확 공식: Sharpe × √(|R| / max(Turnover, 0.125))
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
    pnls = np.array([t['pnl'] for t in trades])

    wins = [t for t in trades if t['win']]
    losses = [t for t in trades if not t['win']]

    metrics.win_rate = len(wins) / len(trades)

    total_profit = sum(t['pnl'] for t in wins) if wins else 0.0
    total_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.0001

    metrics.profit_factor = total_profit / total_loss if total_loss > 0 else 0.0
    metrics.avg_rr_ratio = np.mean([t['rr_ratio'] for t in trades]) if trades else 0.0
    metrics.total_return = sum(t['pnl'] for t in trades)

    # ===== Phase G-8 신규 지표 (BRAIN + López de Prado) =====

    # 1. Sharpe (참고용 — 정상 분포 가정)
    pnl_std = float(np.std(pnls)) if len(pnls) > 1 else 0.0001
    pnl_mean = float(np.mean(pnls))
    metrics.sharpe = (pnl_mean / pnl_std) * np.sqrt(252) if pnl_std > 0 else 0.0

    # 2. Sortino (downside-only Sharpe — 진짜 위험)
    downside_pnls = pnls[pnls < 0]
    if len(downside_pnls) > 1:
        downside_std = float(np.std(downside_pnls))
        metrics.sortino = (pnl_mean / downside_std) * np.sqrt(252) if downside_std > 0 else 0.0
    else:
        metrics.sortino = metrics.sharpe * 1.5 if metrics.sharpe > 0 else 0.0

    # 3. Maximum Drawdown (학술 표준 — equity peak-to-trough)
    equity = 1.0 + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    safe_peak = np.where(peak > 0.001, peak, 0.001)
    drawdown = (equity - peak) / safe_peak
    metrics.max_drawdown = max(float(np.min(drawdown)), -1.0)

    # 4. Calmar Ratio (CAGR / |MDD|)
    # 거래당 평균 × 연 거래수 ≈ 연간 수익 (단순 추정)
    trades_per_year = 252 / 5  # 평균 보유 5일 가정
    annual_return = pnl_mean * trades_per_year
    if abs(metrics.max_drawdown) > 0.01:
        metrics.calmar = annual_return / abs(metrics.max_drawdown)
    else:
        metrics.calmar = annual_return * 100  # MDD 0에 가까우면 큰 점수

    # 5. Fitness (BRAIN 정확 공식) = Sharpe × √(|R| / max(Turnover, 0.125))
    # 출처: WorldQuant BRAIN 공식 — Turnover 사용 (MDD X)
    # 우리 시스템: Turnover proxy = 시그널 발생 빈도 (signal_count / lookback)
    turnover_proxy = metrics.signal_count / max(lookback_days, 1)
    abs_returns = abs(metrics.total_return)
    if abs_returns > 0 and turnover_proxy > 0:
        metrics.fitness = metrics.sharpe * np.sqrt(abs_returns / max(turnover_proxy, 0.125))
        if metrics.total_return < 0:
            metrics.fitness = -abs(metrics.fitness)  # 음수 returns → 음수 fitness
    else:
        metrics.fitness = 0.0

    # 6. Expectancy = (WR × AvgWin) - (LR × |AvgLoss|)
    avg_win = float(np.mean([t['pnl'] for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t['pnl'] for t in losses])) if losses else 0.0
    loss_rate = 1 - metrics.win_rate
    metrics.expectancy_pct = (
        metrics.win_rate * avg_win + loss_rate * avg_loss
    ) * 100  # %

    # 7. Margin (bps) — 거래당 평균 수익 (수수료 후)
    # ROUND_TRIP_COST = 0.0021 (21 bps)
    metrics.margin_bps = (pnl_mean - 0.0021) * 10000  # bps

    # 8. Turnover Health (회전율 적정성)
    # 우리 시스템 Turnover = signal_count / lookback_days (전체 lookback 기준 일관성)
    # BRAIN 권장: 0.01~0.70 (한국 보정: 0.05~0.50, 호가 슬리피지 고려)
    if 0.05 <= turnover_proxy <= 0.50:
        metrics.turnover_health = 1.0
    elif turnover_proxy < 0.05:
        metrics.turnover_health = max(turnover_proxy / 0.05, 0.0)
    else:  # > 0.50
        metrics.turnover_health = max(0.0, 1.0 - (turnover_proxy - 0.50))

    # 탈락 기준 없음 (사용자 요청) — 모든 전략 순위에 포함
    metrics.passed = metrics.signal_count >= 1

    # ===== Composite Score (Phase G-8 BRAIN 가중치) =====
    # 0.35 Sortino + 0.20 Calmar + 0.15 Fitness + 0.15 Expectancy
    # + 0.10 Turnover_health + 0.05 Sample_sqrt
    sortino_norm = max(0.0, min(metrics.sortino / 2.0, 1.0))      # Sortino 2.0 = 1.0
    calmar_norm = max(0.0, min(metrics.calmar / 1.0, 1.0))        # Calmar 1.0 = 1.0
    fitness_norm = max(0.0, min(metrics.fitness / 2.0, 1.0))      # Fitness 2.0 = 1.0
    expectancy_norm = max(0.0, min(metrics.expectancy_pct / 2.0, 1.0))  # 2% = 1.0
    sample_norm = min(np.sqrt(metrics.signal_count) / 10.0, 1.0)  # 100건 = 1.0

    metrics.composite_score = (
        0.35 * sortino_norm
        + 0.20 * calmar_norm
        + 0.15 * fitness_norm
        + 0.15 * expectancy_norm
        + 0.10 * metrics.turnover_health
        + 0.05 * sample_norm
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

    # Phase G-7: ALPHA 풀 (보존) + 시장 적응 Top N (매일 동적 평가)
    # 사용자 의도: "ALPHA pool 보존 + 최근 시장 적응 Top 3"
    # 60일 백테스팅 = 최근 시장 환경 반영 → 강세장이면 trend, 약세장이면 mean_rev 자동 진입
    alpha_pool = load_alpha_pool()
    if alpha_pool:
        pool_names = {s['name'] for s in alpha_pool['alpha_strategies']}
        eligible_strategies = list(strategies)
        print(f"\n[야간 전략 선정 — Phase G-7 시장 적응] 시장 레짐: {regime}")
        print(f"  ALPHA 풀 (항상 ACTIVE, 5년 검증): {len(pool_names)}개 — {sorted(pool_names)}")
        print(f"  풀 외 시장 적응 Top {MAX_NON_POOL} (매일 동적): {len(eligible_strategies) - len(pool_names)}개 후보")
        print(f"  점수: {WEIGHT_60D}×60일 + {WEIGHT_180D}×180일 + {WEIGHT_5Y}×5년 메타 (60일 강조 → 시장 빠른 적응)")
    else:
        pool_names = set()
        eligible_strategies = list(strategies)
        print(f"\n[야간 전략 선정 — 시장 적응] 시장 레짐: {regime}")
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
        m_60 = _calc_metrics(
            strategy, trades_60, regime_weight=rw,
            sub_period_passes=2, lookback_days=LOOKBACK_60D,
        )

        # 180일 점수
        trades_180 = _simulate_signals_on_history(
            strategy, universe_ohlcv, universe_info, lookback=LOOKBACK_180D
        )
        m_180 = _calc_metrics(
            strategy, trades_180, regime_weight=rw,
            sub_period_passes=2, lookback_days=LOOKBACK_180D,
        )

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
        # Phase G-9: 백테스팅 결과 강화 표시 (WR/Sharpe/MDD + BRAIN 지표)
        print(f"  [{status:<5}] {strategy.name:<25s} (60일 N={m_60.signal_count})")
        print(f"         60일: WR={m_60.win_rate*100:5.1f}% PF={m_60.profit_factor:.2f} "
              f"Sharpe={m_60.sharpe:+.2f} Sortino={m_60.sortino:+.2f} "
              f"MDD={m_60.max_drawdown*100:+.1f}% Calmar={m_60.calmar:+.2f} "
              f"Fit={m_60.fitness:+.2f} Margin={m_60.margin_bps:+.0f}bps")
        print(f"         180일: WR={m_180.win_rate*100:5.1f}% PF={m_180.profit_factor:.2f} "
              f"Sharpe={m_180.sharpe:+.2f} Sortino={m_180.sortino:+.2f} "
              f"MDD={m_180.max_drawdown*100:+.1f}% N={m_180.signal_count}")
        print(f"         종합 Score={composite:.3f} (5y meta={score_5y:.2f})")

    # Phase G-7 선정:
    # 1) ALPHA 풀은 항상 ACTIVE (보존 — 5년 strict 검증된 안전 자산)
    # 2) 풀 외에서 시장 적응 Top MAX_NON_POOL (매일 60일 강조 점수)
    rated = [m for m in all_metrics if m.signal_count > 0]
    rated.sort(key=lambda m: -m.composite_score)

    # 단계 1: ALPHA 풀 항상 포함 (거래 0건이라도 보존)
    pool_metrics = [m for m in all_metrics if m.strategy_name in pool_names]
    non_pool_metrics_rated = [m for m in rated if m.strategy_name not in pool_names]

    # 단계 2: 풀 외 시장 적응 Top MAX_NON_POOL
    selected_metrics = list(pool_metrics) + non_pool_metrics_rated[:MAX_NON_POOL]

    # min_active 미달 시 풀 외 거래 0건 전략도 추가 (fallback)
    if len(selected_metrics) < min_active:
        unrated = [m for m in all_metrics
                   if m.signal_count == 0 and m.strategy_name not in pool_names]
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
    print(f"  오늘의 ACTIVE: ALPHA {len(pool_metrics)}개 + 시장 적응 Top {MAX_NON_POOL} = {len(selected_strategies)}개")
    for i, m in enumerate(selected_metrics, 1):
        meta = get_alpha_metadata(m.strategy_name) if alpha_pool else None
        if meta:
            tier_label = meta.get('tier', '   ')
            origin = "ALPHA-pool"
        else:
            tier_label = "MKT"
            origin = f"시장 적응 ({regime})"
        print(f"    {i:2d}. [{tier_label:<5}] {m.strategy_name:<25s} Score={m.composite_score:.3f} ({origin})")

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
