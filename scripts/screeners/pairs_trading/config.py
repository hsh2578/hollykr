"""
페어 트레이딩 스크리너 설정
"""
from config import DATA_DIR, CACHE_DIR

# 유니버스 필터
MIN_MARKET_CAP = 3000             # 시가총액 3,000억 이상
MIN_TRADING_VALUE = 50            # 평균 거래대금 50억 이상
LOOKBACK_DAYS = 250               # 가격 데이터 조회 기간 (약 1년)
MAX_MISSING_DAYS = 5              # 연속 결측 허용 일수

# 공적분 검정
ADF_PVALUE = 0.05                 # ADF p-value 임계값
BETA_MIN = 0.3                    # 헤지비율 하한
BETA_MAX = 3.0                    # 헤지비율 상한

# 안정성 검증
ROLLING_WINDOW = 120              # 롤링 ADF 윈도우 (거래일)
STABILITY_MIN_PCT = 80            # 안정성 등급 B 이상 기준(%)
HALF_LIFE_MIN = 5                 # 반감기 하한 (거래일)
HALF_LIFE_MAX = 30                # 반감기 상한 (거래일)

# Z-Score
ZSCORE_FAST = 20                  # 단기 윈도우
ZSCORE_MAIN = 60                  # 주 윈도우
ZSCORE_SLOW = 120                 # 장기 윈도우

# 시그널 임계값
ENTRY_STRONG_Z = 2.0              # 강한 진입 시그널
WATCH_Z = 1.5                     # 관찰 시그널
EXIT_Z = 0.5                      # 청산 시그널
STOP_Z = 4.0                      # 손절 시그널

# 비용
ROUND_TRIP_COST = 0.0042          # 왕복 거래비용 (0.42% = 수수료+슬리피지)

# 제외 섹터 (WICS 중분류 기준)
EXCLUDE_SECTORS = {'건강관리장비와서비스', '제약과생물공학'}

# 출력 디렉토리
OUTPUT_DIR = DATA_DIR / 'pairs'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# WICS 캐시
WICS_CACHE_FILE = CACHE_DIR / 'wics_sectors.csv'
