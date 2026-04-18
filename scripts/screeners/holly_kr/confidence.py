"""
종합 신뢰도 계산 (v4.0 Section 7)

신뢰도 = base_confidence
         x time_weight
         x supply_demand_multiplier
         x market_filter_multiplier
         x fx_trend_multiplier

각 요소:
  - base_confidence: 전략 자체에서 산출 (0.0~1.0)
  - time_weight: EOD=1.0, INTRADAY/HYBRID는 시간대별 조정
  - supply_demand_grade: A=x1.2, B=x1.0, C=x0.7
  - market_filter_pass: True=x1.0, False=x0.5
  - fx_trend: weakening=x0.85, neutral/strengthening=x1.0
"""

from typing import Optional


# ============================================================================
# 수급 등급별 배수
# ============================================================================
SD_MULTIPLIER = {
    'S': 1.15,  # 동반 전환 (매도→매수)
    'A': 1.1,   # 외국인+기관 동반매수 (1.2→1.1로 축소, 다중전략과 균형)
    'A-': 1.05, # 동반매수 (전환/가속 없음)
    'B': 1.0,   # 일부 매수 또는 중립
    'C': 0.9,   # 중립~경계
    'D': 0.7,   # 동반 매도
}

# ============================================================================
# 시간대별 가중치 (Phase 2+ 대비)
# ============================================================================
TIME_WEIGHTS = {
    'EOD': 1.0,
    'INTRADAY': 1.0,   # 장중은 별도 조정 가능
    'HYBRID': 1.0,
}


def calculate_confidence(
    base_confidence: float,
    time_weight: float = 1.0,
    supply_demand_grade: str = 'B',
    market_filter_pass: bool = True,
    fx_trend: str = 'neutral',
    regime_category_weight: float = 1.0,
) -> float:
    """
    종합 신뢰도 계산.

    Args:
        base_confidence: 전략에서 산출한 기본 신뢰도 (0.0~1.0)
        time_weight: 실행 타이밍 가중치 (EOD=1.0)
        supply_demand_grade: 수급 등급 (A/B/C/D)
        market_filter_pass: 시장 필터 통과 여부
        fx_trend: 원화 추세 ('weakening', 'neutral', 'strengthening')
        regime_category_weight: 시장 레짐 기반 카테고리 가중치

    Returns:
        최종 신뢰도 (0.0~1.0)
    """
    confidence = base_confidence

    # 1. 시간대 가중치
    confidence *= time_weight

    # 2. 수급 등급
    sd_mult = SD_MULTIPLIER.get(supply_demand_grade, 1.0)
    confidence *= sd_mult

    # 3. 시장 필터
    if not market_filter_pass:
        confidence *= 0.5

    # 4. 환율 추세
    if fx_trend == 'weakening':
        confidence *= 0.85

    # 5. 시장 레짐 카테고리 가중치
    confidence *= regime_category_weight

    return min(max(confidence, 0.0), 1.0)


def adjust_signal_confidence(
    signal,
    regime_info: Optional[dict] = None,
    fx_trend: str = 'neutral',
) -> float:
    """
    Signal 객체의 신뢰도를 종합 재계산.

    기존 scanner.py의 수급 조정과 호환되면서,
    market_filter + fx_trend + regime_weight까지 반영.

    Args:
        signal: Signal 데이터클래스 인스턴스
        regime_info: get_market_regime() 결과 (None이면 레짐 가중치 1.0)
        fx_trend: 원화 추세

    Returns:
        조정된 신뢰도 값
    """
    from scripts.screeners.holly_kr.filters.market_filter import get_category_weight

    # 기본값
    base = signal.confidence
    time_w = TIME_WEIGHTS.get(signal.exec_timing, 1.0)
    sd_grade = signal.supply_demand_grade

    # 시장 필터 통과 여부
    market_pass = True
    regime_w = 1.0
    if regime_info is not None:
        regime = regime_info.get('regime', '횡보장')
        # 하락장에서 롱 전략은 시장 필터 실패
        if regime == '하락장':
            market_pass = False
        regime_w = get_category_weight(regime_info, signal.category)

    return calculate_confidence(
        base_confidence=base,
        time_weight=time_w,
        supply_demand_grade=sd_grade,
        market_filter_pass=market_pass,
        fx_trend=fx_trend,
        regime_category_weight=regime_w,
    )
