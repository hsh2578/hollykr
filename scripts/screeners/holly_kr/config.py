"""
Holly AI 스크리너 설정
"""
from config import DATA_DIR, CACHE_DIR

# ============================================================================
# 유니버스 필터 — 보통주 + 스팩/리츠 제외 + 시총 1,000억 이상만
# ============================================================================
MIN_MARKET_CAP = 1000             # 시가총액 1,000억 이상
MIN_TRADING_VALUE = 0             # 거래대금 필터 없음 (전략이 처리)
MIN_PRICE = 0                     # 주가 필터 없음 (전략이 처리)
MAX_SUSPENSION_DAYS = 5           # 거래정지 허용 일수
LOOKBACK_DAYS = 1500              # OHLCV 5년 (분기 5년 백테스트 + 듀얼 60일/180일 평가 커버)

# 테마주 필터 — 전략 레벨에서 처리, 유니버스에선 제외 안 함
THEME_TV_MCAP_RATIO = 0.05       # 거래대금/시총 > 5% → 테마 의심
THEME_5D_RETURN_LIMIT = 0.50     # 5일 +50% 이상 → 테마 의심
THEME_SECTOR_SURGE_COUNT = 5     # 동일 섹터 5개+ 동시 급등 → 테마 경보
THEME_CONFIDENCE_DISCOUNT = 0.5  # 테마 경보 시 신뢰도 할인

# 제외 섹터 — 없음 (바이오/제약도 전략이 알아서 걸러냄)
EXCLUDE_SECTORS = set()

# ============================================================================
# 거래비용
# ============================================================================
BUY_COMMISSION = 0.00015          # 0.015%
SELL_COMMISSION = 0.00015         # 0.015%
SECURITIES_TAX = 0.0018           # 0.18%
ROUND_TRIP_COST = BUY_COMMISSION + SELL_COMMISSION + SECURITIES_TAX  # 0.21%
MIN_EXPECTED_RETURN = ROUND_TRIP_COST * 3  # 0.63%

# ============================================================================
# 수급 필터
# ============================================================================
SUPPLY_DEMAND_LOOKBACK = 5        # 5거래일

# ============================================================================
# 포지션 관리
# ============================================================================
MAX_POSITION_PER_STOCK = 0.10     # 종목당 최대 10%
MAX_POSITION_PER_SECTOR = 0.25    # 섹터당 최대 25%
MAX_TOTAL_POSITION = 0.80         # 전체 최대 80% (20% 현금)
MAX_DAILY_ENTRIES = 3             # 하루 최대 신규 진입 3종목
MULTI_SIGNAL_BOOST = 1.3          # 3개+ 전략 동시 시그널 → 신뢰도 부스트

# 매매당 위험 (vol-target sizing)
RISK_PER_TRADE_PCT = 0.005        # 자본의 0.5%만 트레이드당 위험
                                   # position_size = min(RISK / |stop_loss_pct|, MAX_POSITION_PER_STOCK)

# ============================================================================
# 청산 규칙 (백테스트 ↔ 실전 일치)
# ============================================================================
TRAILING_STOP_PCT = 0.05          # 트레일링 스탑 5% (기본값, 카테고리별 override)
PARTIAL_PROFIT_PCT = 0.5          # 목표가 도달 시 50% 익절
FIRST_DAY_LOSS_PCT = -0.03        # 진입 다음날 -3% 음봉 마감 → 시가 청산 (Minervini 룰)
GAP_DOWN_EXIT_AT_OPEN = True      # 시초가 < 손절가 → 시초가 즉시 청산 (실제 한국 시장)

# ============================================================================
# Phase C: 카테고리별 청산 전략 차별화 (Build Alpha 연구 + López de Prado)
# ============================================================================
# 추세 추종/돌파: 트레일링 8% (상승 여유 확보, 노이즈 컷)
# 평균회귀: 트레일링 X (mean reversion에서 stop은 종종 해로움 — Build Alpha)
# 모멘텀/단기: 트레일링 5% (빠른 청산)

CATEGORY_TRAILING_PCT = {
    'breakout':         0.08,  # 돌파: 8% (추세 따라가기)
    'trend_following':  0.10,  # 추세: 10% (긴 호흡)
    'trend':            0.10,
    'momentum':         0.06,  # 모멘텀: 6%
    'gap_momentum':     0.05,  # 갭 모멘텀: 5% (빠른 청산)
    'accumulation':     0.08,  # 매집: 8%
    'multi_factor':     0.06,
    'pullback':         0.05,  # 눌림: 5% (단기)
    'support_bounce':   0.05,
    'mean_reversion':   0.04,  # 평균회귀: 4% (타이트, 빨리 청산)
    'reversal':         0.05,
    'legendary':        0.08,  # Darvas/Weinstein/Minervini
}

# First-day -3% 룰 적용 카테고리
# - 추세/돌파: 적용 (Minervini 정석)
# - 평균회귀/지지반등: 미적용 (작은 음봉도 정상)
FIRST_DAY_RULE_CATEGORIES = {
    'breakout', 'trend_following', 'trend', 'momentum',
    'gap_momentum', 'accumulation', 'legendary',
}

# ============================================================================
# 진입 게이트 (Risk/Reward)
# ============================================================================
RR_THRESHOLD_DEFAULT = 2.0        # 일반 전략: RR ≥ 2.0 미달 시 시그널 폐기
RR_THRESHOLD_STRONG = 2.5         # 추세/돌파 전략: RR ≥ 2.5 (Minervini 권장)

# ============================================================================
# RS Rating
# ============================================================================
RS_WEIGHTS = {
    '3month': 0.4,
    '6month': 0.2,
    '9month': 0.2,
    '12month': 0.2,
}

# ============================================================================
# 출력
# ============================================================================
OUTPUT_DIR = DATA_DIR / 'holly_kr'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WICS_CACHE_FILE = CACHE_DIR / 'wics_sectors.csv'
