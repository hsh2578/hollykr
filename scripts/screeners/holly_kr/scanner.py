"""
HollyKR 스캐너 — Phase 1+2 전략 오케스트레이터 (32개 전략)

파이프라인:
1. 야간 전략 선정: 32개 중 최근 성과 기반 상위 N개 선별
2. 유니버스 → OHLCV → 선별된 전략으로 스캔
3. 수급 등급 → 중복 제거 → 시그널 출력
"""

from typing import List, Optional, Dict

import pandas as pd

from scripts.ohlcv_data import get_ohlcv
from scripts.investor_data import calc_supply_demand_grade
from scripts.screeners.holly_kr.universe import get_universe
from scripts.screeners.holly_kr.config import LOOKBACK_DAYS, MIN_EXPECTED_RETURN
from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.filters.dedup import dedup_signals
from scripts.screeners.holly_kr.filters.theme_filter import is_theme_stock
from scripts.screeners.holly_kr.filters.market_filter import get_market_regime

# ============================================================================
# Phase 1: EOD 12개 전략
# ============================================================================
from scripts.screeners.holly_kr.strategies.pushing_the_spring import PushingTheSpring
from scripts.screeners.holly_kr.strategies.engulfing import Engulfing
from scripts.screeners.holly_kr.strategies.yesterday_hammer import YesterdayHammer
from scripts.screeners.holly_kr.strategies.snap_back_long import SnapBackLong
from scripts.screeners.holly_kr.strategies.horseshoe_up import HorseshoeUp
from scripts.screeners.holly_kr.strategies.volume_doesnt_lie import VolumeDoesntLie
from scripts.screeners.holly_kr.strategies.minervini_trend import MinerviniTrend
from scripts.screeners.holly_kr.strategies.darvas_box import DarvasBox
from scripts.screeners.holly_kr.strategies.weinstein_stage import WeinsteinStage
from scripts.screeners.holly_kr.strategies.livermore_pivot import LivermorePivot
from scripts.screeners.holly_kr.strategies.magic_formula import MagicFormula
from scripts.screeners.holly_kr.strategies.piotroski_fscore import PiotroskiFScore

# ============================================================================
# Phase 2: HYBRID 20개 전략
# ============================================================================
from scripts.screeners.holly_kr.strategies.bullish_trend_change import BullishTrendChange
from scripts.screeners.holly_kr.strategies.float_on import FloatOn
from scripts.screeners.holly_kr.strategies.wake_up_call import WakeUpCall
from scripts.screeners.holly_kr.strategies.staggering_volume import StaggeringVolume
from scripts.screeners.holly_kr.strategies.close_to_a_cross import CloseToACross
from scripts.screeners.holly_kr.strategies.alpha_predators import AlphaPredators
from scripts.screeners.holly_kr.strategies.bullish_pullback import BullishPullback
from scripts.screeners.holly_kr.strategies.strong_stock_pulling_back import StrongStockPullingBack
from scripts.screeners.holly_kr.strategies.quarterback import Quarterback
from scripts.screeners.holly_kr.strategies.tailwind import Tailwind
from scripts.screeners.holly_kr.strategies.trend_play import TrendPlay
from scripts.screeners.holly_kr.strategies.the_continuation import TheContinuation
from scripts.screeners.holly_kr.strategies.got_dough import GotDough
from scripts.screeners.holly_kr.strategies.guiding_hand import GuidingHand
from scripts.screeners.holly_kr.strategies.nice_chart import NiceChart
from scripts.screeners.holly_kr.strategies.the_vault import TheVault
from scripts.screeners.holly_kr.strategies.pulling_the_arrow import PullingTheArrow
from scripts.screeners.holly_kr.strategies.balloon_under_water import BalloonUnderWater
from scripts.screeners.holly_kr.strategies.neo_breakout import NeoBreakout
from scripts.screeners.holly_kr.strategies.neo_pullback import NeoPullback

# ============================================================================
# Phase 7 신규 5개 (사이트 stock-screener-kr 한국화)
# ============================================================================
from scripts.screeners.holly_kr.strategies.ma_convergence import MAConvergence
from scripts.screeners.holly_kr.strategies.new_high_52w_approach import NewHigh52wApproach
# Phase G-9: new_high_52w_breakout 5년 strict 부진 (PF<1) → 비활성화
# (파일 보존, scanner 제외)
from scripts.screeners.holly_kr.strategies.bottom_breakout import BottomBreakout
from scripts.screeners.holly_kr.strategies.volume_dry_up import VolumeDryUp
from scripts.screeners.holly_kr.strategies.box_range_watch import BoxRangeWatch

# ============================================================================
# Phase H 시스템 트레이딩 거장 정통 구현 (학술/실무 검증)
# ============================================================================
from scripts.screeners.holly_kr.strategies.clenow_momentum import ClenowMomentum
from scripts.screeners.holly_kr.strategies.donchian_breakout import DonchianBreakout
from scripts.screeners.holly_kr.strategies.aqr_tsmom import AQRTSMomentum
from scripts.screeners.holly_kr.strategies.bollinger_squeeze import BollingerSqueeze
from scripts.screeners.holly_kr.strategies.elder_triple_screen import ElderTripleScreen
from scripts.screeners.holly_kr.strategies.turn_of_month import TurnOfMonth
from scripts.screeners.holly_kr.strategies.adx_trend import ADXTrend

# Phase G-6: 5년 strict에서 거래 0건인 14개 자체 패턴 비활성화
# (Phase 1+2 자체 한국화 패턴 중 학술 검증 X). Strategy 파일은 보존 (향후 활성화 가능).
# 비활성화: pushing_the_spring, float_on, staggering_volume, alpha_predators,
#   strong_stock_pulling_back, the_continuation, got_dough, guiding_hand,
#   nice_chart, the_vault, pulling_the_arrow, balloon_under_water,
#   neo_breakout, neo_pullback
# 보존 (학술 검증 + 분기 자연 0): minervini_trend_template, livermore_pivot,
#   magic_formula, piotroski_fscore

# Phase 1: EOD (학술 검증 8개)
PHASE1_STRATEGIES = [
    Engulfing(), YesterdayHammer(), SnapBackLong(),
    HorseshoeUp(), VolumeDoesntLie(), MinerviniTrend(), DarvasBox(),
    WeinsteinStage(), LivermorePivot(), MagicFormula(), PiotroskiFScore(),
]

# Phase 2: HYBRID (시그널 발생 7개)
PHASE2_STRATEGIES = [
    BullishTrendChange(), WakeUpCall(),
    CloseToACross(), BullishPullback(),
    Quarterback(), Tailwind(), TrendPlay(),
]

# Phase 7 신규 5개
PHASE7_STRATEGIES = [
    MAConvergence(), NewHigh52wApproach(), BottomBreakout(),
    VolumeDryUp(), BoxRangeWatch(),
]

# Phase H: 시스템 트레이딩 거장 정통 (Clenow / Donchian-Seykota / AQR + Bollinger / Elder + Calendar / Wilder ADX)
PHASE_H_STRATEGIES = [
    ClenowMomentum(), DonchianBreakout(), AQRTSMomentum(),
    BollingerSqueeze(), ElderTripleScreen(),
    TurnOfMonth(), ADXTrend(),
]

# 전체 전략 (총 30개 — 5년 strict 거래 발생 + 학술 검증)
ALL_STRATEGIES = PHASE1_STRATEGIES + PHASE2_STRATEGIES + PHASE7_STRATEGIES + PHASE_H_STRATEGIES


_regime_info = None  # run_scanner에서 설정

def _scan_single_stock(ticker: str, name: str, sector: str,
                        market_cap: float,
                        strategies: list,
                        entry_mode: str = 'open') -> List[Signal]:
    """단일 종목에 전략 적용."""
    df = get_ohlcv(ticker, days=LOOKBACK_DAYS, use_cache=True)
    if df is None or len(df) < 20:
        return []

    if is_theme_stock(df, market_cap):
        return []

    # 진입가: 종가 매수면 당일 종가, 시가 매수면 당일 종가(=내일 시가 추정)
    entry_price = df['Close'].iloc[-1]
    signals = []

    for strategy in strategies:
        try:
            if hasattr(strategy, 'name') and strategy.name == 'got_dough':
                sig = strategy.scan(df, ticker, name,
                                    sector=sector, entry_price=entry_price,
                                    market_cap=market_cap)
            else:
                sig = strategy.scan(df, ticker, name,
                                    sector=sector, entry_price=entry_price)
            if sig is not None:
                # 진입 모드 태그
                sig.entry_mode = entry_mode
                signals.append(sig)
        except Exception as e:
            import logging
            logging.warning(f"[{strategy.name}] {ticker} scan error: {e}")
            continue

    # Phase G-9: 거래대금 60일 평균 자동 계산 (억원, 슬리피지 위험 평가)
    if signals and len(df) >= 20:
        try:
            recent_value_eok = float((df['Close'] * df['Volume']).iloc[-60:].mean() / 1e8)
            for sig in signals:
                sig.daily_value_eok = round(recent_value_eok, 1)
        except Exception:
            pass

    # 수급 등급 + 종합 신뢰도 계산 (confidence.py 연동)
    if signals:
        try:
            sd_grade, _ = calc_supply_demand_grade(ticker)
            for sig in signals:
                sig.supply_demand_grade = sd_grade
                if sd_grade == 'D':
                    sig.risk_warnings.append('외국인+기관 동반매도')
        except Exception:
            pass

        # confidence.py로 종합 신뢰도 계산 (수급 + 레짐 + 시장필터)
        try:
            from scripts.screeners.holly_kr.confidence import adjust_signal_confidence
            for sig in signals:
                sig.confidence = min(0.95, adjust_signal_confidence(sig, regime_info=_regime_info))
        except Exception:
            pass

    return signals


def _run_nightly_selection(universe: pd.DataFrame,
                            strategies: list) -> list:
    """야간 전략 선정 — 최근 20일 미니 백테스트로 활성 전략 선별."""
    from scripts.screeners.holly_kr.nightly_selector import select_strategies

    # 유니버스 중 시총 상위 100개로 빠르게 평가
    sample = universe.nlargest(100, 'MarketCap').reset_index(drop=True)

    # OHLCV 딕셔너리 구성
    ohlcv_dict = {}
    for _, row in sample.iterrows():
        df = get_ohlcv(row['Code'], days=LOOKBACK_DAYS, use_cache=True)
        if df is not None and len(df) > 50:
            ohlcv_dict[row['Code']] = df

    selected, metrics = select_strategies(
        strategies=strategies,
        universe_ohlcv=ohlcv_dict,
        universe_info=sample,
    )

    return selected, metrics


def run_scanner(phase: str = 'all',
                entry_mode: str = 'open',
                use_nightly_selection: bool = False) -> List[Signal]:
    """
    HollyKR 전체 스캔 실행.

    Args:
        phase: 'all' | 'phase1' | 'phase2'
        entry_mode: 'open' (다음날 시가) | 'close' (당일 종가)
        use_nightly_selection: True면 야간 전략 선정 후 상위 전략만 사용

    Returns:
        중복 제거된 최종 시그널 리스트
    """
    global _regime_info
    # 0. 시장 레짐 판별
    try:
        _regime_info = get_market_regime()
        regime = _regime_info.get('regime', '횡보장')
    except Exception:
        _regime_info = {}
        regime = '횡보장'

    print(f"\n[시장 레짐: {regime}]")
    if regime == '하락장':
        print("  → 하락장 감지 — 시그널 생성 최소화, 신뢰도 50% 할인 적용")

    # 1. 전략 목록 결정 (Phase 7 신규 5개 포함, 총 37개)
    if phase == 'phase1':
        strategies = list(PHASE1_STRATEGIES)
    elif phase == 'phase2':
        strategies = list(PHASE2_STRATEGIES)
    else:
        strategies = list(ALL_STRATEGIES)

    # 2. 유니버스
    universe = get_universe()
    if len(universe) == 0:
        print("유니버스 비어있음")
        return []

    # 3. 야간 전략 선정 (옵션)
    if use_nightly_selection:
        print("\n[야간 전략 선정] 최근 20거래일 미니 백테스트...")
        selected, metrics = _run_nightly_selection(universe, strategies)
        if selected:
            strategies = selected
            print(f"  → {len(strategies)}개 전략 활성화")
        else:
            print(f"  → 선정 실패, 전체 {len(strategies)}개 전략 사용")

    # 4. 전종목 스캔
    entry_desc = '당일 종가' if entry_mode == 'close' else '다음날 시가'
    print(f"\n[전략 스캔] {len(universe)}개 종목 × {len(strategies)}개 전략")
    print(f"  진입 시점: {entry_desc}")
    print("=" * 50)

    all_signals = []
    total = len(universe)

    for i, (_, row) in enumerate(universe.iterrows(), 1):
        sigs = _scan_single_stock(
            row['Code'], row['Name'], row['Sector'], row['MarketCap'],
            strategies=strategies, entry_mode=entry_mode,
        )
        all_signals.extend(sigs)

        if i % 50 == 0:
            print(f"  진행: {i}/{total} ({len(all_signals)}개 시그널)")

    print(f"\n  원시 시그널: {len(all_signals)}개")

    # 5. 기대수익 필터
    before = len(all_signals)
    all_signals = [s for s in all_signals if s.target_pct >= MIN_EXPECTED_RETURN]
    if before != len(all_signals):
        print(f"  기대수익 필터: {before} → {len(all_signals)}개")

    # 5.5. 하락장 경고 태그 (신뢰도 할인은 confidence.py에서 처리)
    if regime == '하락장':
        for sig in all_signals:
            if '하락장' not in sig.risk_warnings:
                sig.risk_warnings.append('하락장')
        print(f"  하락장 감지: {len(all_signals)}개 시그널에 경고 태그")

    # 6. 중복 제거
    final = dedup_signals(all_signals)
    print(f"  중복 제거 후: {len(final)}개")

    # 7. 정렬
    final.sort(key=lambda s: -s.confidence)

    # 통계
    by_strategy = {}
    by_phase = {'EOD': 0, 'HYBRID': 0, 'INTRADAY': 0}
    for s in final:
        by_strategy[s.strategy_name] = by_strategy.get(s.strategy_name, 0) + 1
        by_phase[s.exec_timing] = by_phase.get(s.exec_timing, 0) + 1

    print(f"\n  Phase별: EOD {by_phase['EOD']}개, HYBRID {by_phase['HYBRID']}개")
    print(f"  전략별 시그널:")
    for name, count in sorted(by_strategy.items(), key=lambda x: -x[1]):
        print(f"    {name}: {count}개")

    return final
