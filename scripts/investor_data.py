"""
외국인/기관 수급 데이터 수집 모듈

데이터 소스:
  Primary: 한국투자증권 KIS OpenAPI (FHKST01010900)
  Fallback: 네이버 금융 투자자별 매매동향

수집 데이터:
  - 외국인 순매수(주)
  - 기관 순매수(주)
  - 날짜별 시계열 (최근 ~30거래일)

환경변수:
  KIS_APP_KEY, KIS_APP_SECRET: 한투 앱키 (실전/모의 둘 다 가능)
  KIS_BASE_URL: 기본 https://openapi.koreainvestment.com:9443 (실전)
                모의: https://openapivts.koreainvestment.com:29443

사용법:
    from scripts.investor_data import get_investor_data, calc_supply_demand_grade
    df = get_investor_data('005930')
    grade, features = calc_supply_demand_grade('005930')
    python -m scripts.investor_data
"""

import json
import os
import pickle
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import INVESTOR_CACHE_DIR, INVESTOR_PAGES, CACHE_DIR

# ============================================================================
# 환경변수 (.env 지원)
# ============================================================================
try:
    from dotenv import load_dotenv
    # 로컬 .env 우선, 없으면 vibecoding 통합 .env 사용
    _VIBECODING_ENV = Path(__file__).resolve().parents[2] / '.env'
    load_dotenv()
    if _VIBECODING_ENV.exists():
        load_dotenv(_VIBECODING_ENV, override=False)
except ImportError:
    pass

KIS_APP_KEY = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE_URL = os.environ.get(
    'KIS_BASE_URL', 'https://openapi.koreainvestment.com:9443'
)

# ============================================================================
# 상수
# ============================================================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

NAVER_FRGN_URL = 'https://finance.naver.com/item/frgn.naver'
CACHE_MAX_HOURS = 12

KIS_TOKEN_CACHE = CACHE_DIR / '.kis_token.json'

# ============================================================================
# KIS 토큰 관리
# ============================================================================

_token = None
_token_expires_at: Optional[datetime] = None
_token_lock = threading.Lock()
_session = requests.Session()


class _RateLimiter:
    def __init__(self, max_per_sec: int):
        self.min_interval = 1.0 / max_per_sec
        self.lock = threading.Lock()
        self.last = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            gap = self.last + self.min_interval - now
            if gap > 0:
                time.sleep(gap)
            self.last = time.monotonic()


_limiter = _RateLimiter(18)


def _load_kis_token_cache() -> bool:
    global _token, _token_expires_at
    if not KIS_TOKEN_CACHE.exists():
        return False
    try:
        with open(KIS_TOKEN_CACHE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        expires = datetime.fromisoformat(data['expires_at'])
        if datetime.now() < expires - timedelta(minutes=10):
            _token = data['token']
            _token_expires_at = expires
            return True
    except Exception:
        pass
    return False


def _save_kis_token_cache(token: str, expires_at: datetime):
    try:
        with open(KIS_TOKEN_CACHE, 'w', encoding='utf-8') as f:
            json.dump({'token': token, 'expires_at': expires_at.isoformat()}, f)
    except Exception:
        pass


def _get_kis_token() -> Optional[str]:
    """KIS OAuth 토큰 발급 (파일 캐시 23시간)."""
    global _token, _token_expires_at

    if not (KIS_APP_KEY and KIS_APP_SECRET):
        return None

    with _token_lock:
        now = datetime.now()
        if _token and _token_expires_at and now < _token_expires_at - timedelta(minutes=5):
            return _token
        if _load_kis_token_cache() and _token:
            return _token

        try:
            resp = _session.post(
                f'{KIS_BASE_URL}/oauth2/tokenP',
                headers={'Content-Type': 'application/json'},
                json={
                    'grant_type': 'client_credentials',
                    'appkey': KIS_APP_KEY,
                    'appsecret': KIS_APP_SECRET,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            _token = data['access_token']
            _token_expires_at = now + timedelta(hours=23)
            _save_kis_token_cache(_token, _token_expires_at)
            return _token
        except Exception as e:
            print(f'  [KIS 토큰 발급 실패] {e}')
            return None


# ============================================================================
# 캐시
# ============================================================================

def _cache_path(ticker: str) -> Path:
    return INVESTOR_CACHE_DIR / f'{ticker}.pkl'


def _load_cache(ticker: str) -> Optional[pd.DataFrame]:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if (datetime.now() - mtime).total_seconds() > CACHE_MAX_HOURS * 3600:
            return None
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception:
        return None


def _save_cache(ticker: str, df: pd.DataFrame):
    path = _cache_path(ticker)
    with open(path, 'wb') as f:
        pickle.dump(df, f)


# ============================================================================
# KIS API 수급 수집 (Primary)
# ============================================================================

def _fetch_kis(ticker: str) -> Optional[pd.DataFrame]:
    """
    KIS OpenAPI 외국인/기관 순매수 조회

    TR_ID: FHKST01010900 (종목별 투자자 매매동향)
    필드: frgn_ntby_qty(외국인), orgn_ntby_qty(기관), stck_bsop_date(거래일)
    반환: 최근 ~30거래일
    """
    token = _get_kis_token()
    if not token:
        return None

    code6 = str(ticker).zfill(6)
    url = f'{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor'
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'authorization': f'Bearer {token}',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
        'tr_id': 'FHKST01010900',
        'custtype': 'P',
    }
    params = {
        'FID_COND_MRKT_DIV_CODE': 'J',
        'FID_INPUT_ISCD': code6,
    }

    try:
        _limiter.wait()
        resp = _session.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f'  [KIS 수급 조회 실패 {ticker}] {e}')
        return None

    if data.get('rt_cd') != '0':
        return None

    items = data.get('output', [])
    if not items:
        return None

    rows = []
    for item in items:
        date_str = item.get('stck_bsop_date', '')
        if not date_str:
            continue
        try:
            date = pd.to_datetime(date_str, format='%Y%m%d')
            foreign_net = int(item.get('frgn_ntby_qty', 0) or 0)
            inst_net = int(item.get('orgn_ntby_qty', 0) or 0)
            rows.append({
                'date': date,
                'inst_net': inst_net,
                'foreign_net': foreign_net,
            })
        except Exception:
            continue

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.sort_values('date').drop_duplicates('date').reset_index(drop=True)
    return df


# ============================================================================
# 네이버 금융 수급 수집 (Fallback)
# ============================================================================

def _parse_number(text: str) -> Optional[int]:
    if not text:
        return None
    text = text.replace(',', '').strip()
    try:
        return int(text)
    except ValueError:
        return None


def _fetch_naver(ticker: str, pages: int = INVESTOR_PAGES) -> Optional[pd.DataFrame]:
    """네이버 금융 외국인/기관 순매수 크롤링 (폴백용)."""
    all_rows = []

    for page in range(1, pages + 1):
        try:
            resp = requests.get(
                NAVER_FRGN_URL,
                params={'code': ticker, 'page': page},
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            tables = soup.select('table.type2')
            for table in tables:
                rows = table.select('tr')
                header_text = rows[0].get_text() if rows else ''
                if '날짜' not in header_text and '외국인' not in header_text:
                    continue

                for row in rows[2:]:
                    cols = row.select('td')
                    if len(cols) < 7:
                        continue

                    date_text = cols[0].get_text(strip=True)
                    if '.' not in date_text:
                        continue

                    try:
                        date = pd.to_datetime(date_text, format='%Y.%m.%d')
                        inst_net = _parse_number(cols[5].get_text(strip=True))
                        foreign_net = _parse_number(cols[6].get_text(strip=True))

                        if inst_net is not None and foreign_net is not None:
                            all_rows.append({
                                'date': date,
                                'inst_net': inst_net,
                                'foreign_net': foreign_net,
                            })
                    except Exception:
                        continue

            time.sleep(0.1)

        except Exception:
            continue

    if not all_rows:
        return None

    df = pd.DataFrame(all_rows)
    df = df.sort_values('date').drop_duplicates('date').reset_index(drop=True)
    return df


# ============================================================================
# 공개 API
# ============================================================================

def get_investor_data(ticker: str, use_cache: bool = True) -> Optional[pd.DataFrame]:
    """
    외국인/기관 수급 데이터 조회.

    시도 순서: 캐시 → KIS API → 네이버 폴백

    Returns:
        DataFrame[date, inst_net(주), foreign_net(주)]  최근 ~30거래일
    """
    if use_cache:
        cached = _load_cache(ticker)
        if cached is not None:
            return cached

    df = _fetch_kis(ticker)
    if df is None or len(df) == 0:
        df = _fetch_naver(ticker)

    if df is not None and len(df) > 0:
        _save_cache(ticker, df)
        return df

    return None


def calc_supply_demand_features(ticker: str, lookback: int = 5) -> Dict[str, float]:
    default = {
        'foreign_net_5d': 0.0,
        'inst_net_5d': 0.0,
        'foreign_trend': 0.0,
        'inst_trend': 0.0,
        'foreign_reversal': False,
        'inst_reversal': False,
        'foreign_accel': False,
        'inst_accel': False,
    }

    df = get_investor_data(ticker)
    if df is None or len(df) < lookback:
        return default

    recent = df.tail(lookback * 2)
    if len(recent) < lookback:
        return default

    last = recent.tail(lookback)

    features = {
        'foreign_net_5d': last['foreign_net'].sum() / 10000,
        'inst_net_5d': last['inst_net'].sum() / 10000,
        'foreign_trend': 0.0,
        'inst_trend': 0.0,
        'foreign_reversal': False,
        'inst_reversal': False,
        'foreign_accel': False,
        'inst_accel': False,
    }

    if len(recent) >= lookback * 2:
        prev = recent.head(lookback)
        prev_foreign = prev['foreign_net'].mean()
        prev_inst = prev['inst_net'].mean()

        if prev_foreign != 0:
            features['foreign_trend'] = max(-2, min(2,
                (last['foreign_net'].mean() - prev_foreign) / abs(prev_foreign)
            ))
        if prev_inst != 0:
            features['inst_trend'] = max(-2, min(2,
                (last['inst_net'].mean() - prev_inst) / abs(prev_inst)
            ))

    if len(last) >= 4:
        foreign_vals = last['foreign_net'].values
        inst_vals = last['inst_net'].values

        if all(v < 0 for v in foreign_vals[-4:-1]) and foreign_vals[-1] > 0:
            features['foreign_reversal'] = True
        if all(v < 0 for v in inst_vals[-4:-1]) and inst_vals[-1] > 0:
            features['inst_reversal'] = True

    if len(last) >= 2:
        foreign_vals = last['foreign_net'].values
        inst_vals = last['inst_net'].values

        if foreign_vals[-1] > 0 and foreign_vals[-1] > foreign_vals[-2]:
            features['foreign_accel'] = True
        if inst_vals[-1] > 0 and inst_vals[-1] > inst_vals[-2]:
            features['inst_accel'] = True

    return features


def calc_supply_demand_grade(ticker: str) -> Tuple[str, Dict[str, float]]:
    features = calc_supply_demand_features(ticker)

    foreign_buy = features['foreign_net_5d'] > 0
    inst_buy = features['inst_net_5d'] > 0

    has_reversal = features['foreign_reversal'] or features['inst_reversal']
    has_accel = features['foreign_accel'] or features['inst_accel']
    both_reversal = features['foreign_reversal'] and features['inst_reversal']

    if both_reversal and foreign_buy and inst_buy:
        grade = 'S'
    elif foreign_buy and inst_buy and (has_reversal or has_accel):
        grade = 'A'
    elif foreign_buy and inst_buy:
        grade = 'A-'
    elif foreign_buy or inst_buy:
        grade = 'B'
    elif features['foreign_net_5d'] < 0 and features['inst_net_5d'] < 0:
        grade = 'D'
    else:
        grade = 'C'

    return grade, features


# ============================================================================
# 모듈 테스트
# ============================================================================

if __name__ == '__main__':
    print("외국인/기관 수급 데이터 수집 테스트")
    print("=" * 50)
    if KIS_APP_KEY:
        print(f"  KIS 모드: {KIS_BASE_URL}")
    else:
        print("  KIS 키 미설정 → 네이버 폴백만 사용")
    print()

    test_tickers = [
        ('005930', '삼성전자'),
        ('000660', 'SK하이닉스'),
        ('035420', 'NAVER'),
    ]

    for ticker, name in test_tickers:
        print(f"\n{name}({ticker})")
        print("-" * 40)

        df = get_investor_data(ticker, use_cache=False)
        if df is not None:
            print(f"  데이터: {len(df)}거래일")
            print(f"  기간: {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}")
            print(f"  최근 5일:")
            for _, row in df.tail(5).iterrows():
                print(f"    {row['date'].strftime('%Y-%m-%d')}  "
                      f"기관: {row['inst_net']:>+12,}주  "
                      f"외국인: {row['foreign_net']:>+12,}주")
        else:
            print("  데이터 수집 실패")

        grade, feat = calc_supply_demand_grade(ticker)
        print(f"\n  수급 등급: {grade}")
        print(f"  외국인 5일 합계: {feat['foreign_net_5d']:+.1f}만주")
        print(f"  기관 5일 합계: {feat['inst_net_5d']:+.1f}만주")

        time.sleep(0.2)
