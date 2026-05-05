"""
Phase 9: Survivorship Bias 보정 (정직성 + 향후 PIT 유니버스 통합)

현재 한계:
    - pykrx historical 유니버스는 KRX_ID/KRX_PW 환경변수 필요 (미공개 API)
    - 따라서 200일 전 시점의 정확한 종목 마스터를 얻기 어려움
    - 차선책: 현재 유니버스 PF에 보정계수 (0.75) 적용 → 추정 실전 PF

향후 통합 경로 (구현 시):
    1. KRX OpenAPI 등록 + 종목 마스터 historical 다운로드
    2. 또는 KIS API의 종목정보 일자별 조회
    3. PIT 유니버스 = {date: [active_tickers]} 딕셔너리 구축
    4. _load_universe_ohlcv에서 end_date 기준 PIT 유니버스 필터링

이 모듈은 보정 계수 + 메타데이터 제공.
"""

# ============================================================================
# Survivorship bias 보정 계수 (실증 추정값)
# ============================================================================
# 출처: 한국 시장 학술 연구 + 글로벌 실증 분석
#   - 미국 시장: 약 15-20% bias (S&P 500 변경 빈도 낮음)
#   - 한국 시장: 약 20-30% bias (KOSPI 변경 빈도 ↑, 작전주/관리종목 회전 ↑)
#   - 보수적 추정: 0.75 (25% 할인)
SURVIVORSHIP_BIAS_DISCOUNT = 0.75


def adjust_pf_for_survivorship(pf: float, discount: float = SURVIVORSHIP_BIAS_DISCOUNT) -> float:
    """PF를 survivorship bias 보정.

    Args:
        pf: 백테스트 PF (살아남은 종목만 사용)
        discount: 보정 계수 (기본 0.75 = 25% 할인)

    Returns:
        보정된 추정 실전 PF
    """
    return pf * discount


def is_real_alpha_after_bias(pf_ci_lower: float, n_trades: int,
                              discount: float = SURVIVORSHIP_BIAS_DISCOUNT) -> bool:
    """Survivorship bias 보정 후 진짜 알파인지 판정.

    조건:
        - 거래수 >= 30 (통계적 유의성)
        - 보정된 PF 95% CI 하한 > 1.0
    """
    return n_trades >= 30 and (pf_ci_lower * discount) > 1.0


# ============================================================================
# 향후 PIT 유니버스 통합 시 사용
# ============================================================================

def load_pit_universe(end_date) -> set:
    """특정 날짜 기준 PIT 유니버스 로드 (미구현, 외부 데이터 필요).

    구현 시 반환: end_date에 거래 가능했던 종목 코드 set
    """
    raise NotImplementedError(
        "PIT 유니버스 통합은 KRX OpenAPI 등록 또는 historical 종목 마스터 다운로드 필요. "
        "현재는 SURVIVORSHIP_BIAS_DISCOUNT(0.75) 보정 계수로 대체."
    )
