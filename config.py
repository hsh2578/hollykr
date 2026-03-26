"""
프로젝트 공통 설정
"""
import os
import socket
from pathlib import Path

# 프로젝트 루트
BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / '.cache'
DATA_DIR = BASE_DIR / 'data'

# 디렉토리 자동 생성
CACHE_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# 네트워크 설정
socket.setdefaulttimeout(30)

# 종목 필터
MIN_MARKET_CAP = 1000  # 시가총액 1,000억 이상

# FnGuide 수집 설정
FNGUIDE_MAX_WORKERS = 5  # 병렬 요청 수 (각 종목당 2페이지 → 실제 최대 10 concurrent)
FNGUIDE_DELAY = 0.3  # 순차 수집 시 요청 간 대기시간
MAX_CACHE_DAYS = 2  # 최근 N일 캐시만 유지
CACHE_REFRESH_DAYS = 7  # N일 이내 캐시 데이터는 증분 수집 시 재사용

# OHLCV 설정
DEFAULT_OHLCV_DAYS = 300

# 수급 데이터 설정
INVESTOR_CACHE_DIR = CACHE_DIR / 'investor'
INVESTOR_CACHE_DIR.mkdir(exist_ok=True)
INVESTOR_PAGES = 3  # 네이버 금융 크롤링 페이지 수 (1페이지 ≈ 20거래일)
