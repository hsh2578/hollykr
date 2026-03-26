"""
외국인/기관 수급 데이터 수집 모듈

데이터 소스:
  Primary: 네이버 금융 투자자별 매매동향 (finance.naver.com/item/frgn.naver)
  Fallback: 키움증권 REST API (KIWOOM_APP_KEY 설정 시)

수집 데이터:
  - 외국인 순매수(주)
  - 기관 순매수(주)
  - 날짜별 시계열

사용법:
    from scripts.investor_data import get_investor_data, calc_supply_demand_grade

    # 단일 종목
    df = get_investor_data('005930')

    # 수급 등급
    grade, features = calc_supply_demand_grade('005930')

    # 모듈 테스트
    python -m scripts.investor_data
"""

import pickle
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import INVESTOR_CACHE_DIR, INVESTOR_PAGES

# ============================================================================
# 상수
# ============================================================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

NAVER_FRGN_URL = 'https://finance.naver.com/item/frgn.naver'

# 캐시 유효기간 (시간 단위)
CACHE_MAX_HOURS = 12


# ============================================================================
# 캐시
# ============================================================================

def _cache_path(ticker: str) -> Path:
    return INVESTOR_CACHE_DIR / f'{ticker}.pkl'


def _load_cache(ticker: str) -> Optional[pd.DataFrame]:
    """캐시 로드 (CACHE_MAX_HOURS 이내만 유효)"""
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
# 네이버 금융 수급 수집 (Primary)
# ============================================================================

def _parse_number(text: str) -> Optional[int]:
    """숫자 파싱: '+1,234' → 1234, '-567' → -567"""
    if not text:
        return None
    text = text.replace(',', '').strip()
    # 부호 유지
    try:
        return int(text)
    except ValueError:
        return None


def _fetch_naver(ticker: str, pages: int = INVESTOR_PAGES) -> Optional[pd.DataFrame]:
    """
    네이버 금융 외국인/기관 순매수 크롤링

    URL: https://finance.naver.com/item/frgn.naver?code={ticker}&page={page}
    테이블 구조: 날짜 | 종가 | 전일비 | 등락률 | 거래량 | 기관순매수 | 외국인순매수 | ...
    """
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

                for row in rows[2:]:  # 헤더 2줄 스킵
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
    외국인/기관 수급 데이터 조회

    Returns:
        DataFrame with columns: date, inst_net(주), foreign_net(주)
        최근 ~60거래일 데이터 (3페이지)
    """
    if use_cache:
        cached = _load_cache(ticker)
        if cached is not None:
            return cached

    # Primary: 네이버 금융
    df = _fetch_naver(ticker)

    if df is not None and len(df) > 0:
        _save_cache(ticker, df)
        return df

    return None


def calc_supply_demand_features(ticker: str, lookback: int = 5) -> Dict[str, float]:
    """
    수급 피처 계산

    Returns:
        {
            'foreign_net_5d': 5일 외국인 순매수 합계 (만주),
            'inst_net_5d': 5일 기관 순매수 합계 (만주),
            'foreign_trend': 외국인 추세 (최근5일 vs 이전5일, -2~2 클리핑),
            'inst_trend': 기관 추세,
            'foreign_reversal': 매도→매수 전환 여부,
            'inst_reversal': 매도→매수 전환 여부,
            'foreign_accel': 순매수 가속 여부,
            'inst_accel': 순매수 가속 여부,
        }
    """
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

    # 최근 N일
    recent = df.tail(lookback * 2)
    if len(recent) < lookback:
        return default

    last = recent.tail(lookback)

    features = {
        'foreign_net_5d': last['foreign_net'].sum() / 10000,  # 만주 단위
        'inst_net_5d': last['inst_net'].sum() / 10000,
        'foreign_trend': 0.0,
        'inst_trend': 0.0,
        'foreign_reversal': False,
        'inst_reversal': False,
        'foreign_accel': False,
        'inst_accel': False,
    }

    # 추세: 최근 5일 vs 이전 5일
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

    # --- 방향 전환 감지 (reversal) ---
    # 최근 4일 이상 데이터 필요 (이전 3일 매도 + 오늘 매수)
    if len(last) >= 4:
        foreign_vals = last['foreign_net'].values
        inst_vals = last['inst_net'].values

        # 외국인: 이전 3일 연속 순매도 → 오늘 순매수 전환
        if all(v < 0 for v in foreign_vals[-4:-1]) and foreign_vals[-1] > 0:
            features['foreign_reversal'] = True

        # 기관: 이전 3일 연속 순매도 → 오늘 순매수 전환
        if all(v < 0 for v in inst_vals[-4:-1]) and inst_vals[-1] > 0:
            features['inst_reversal'] = True

    # --- 가속 감지 (acceleration) ---
    # 오늘의 순매수 > 어제의 순매수 (양수일 때)
    if len(last) >= 2:
        foreign_vals = last['foreign_net'].values
        inst_vals = last['inst_net'].values

        if foreign_vals[-1] > 0 and foreign_vals[-1] > foreign_vals[-2]:
            features['foreign_accel'] = True

        if inst_vals[-1] > 0 and inst_vals[-1] > inst_vals[-2]:
            features['inst_accel'] = True

    return features


def calc_supply_demand_grade(ticker: str) -> Tuple[str, Dict[str, float]]:
    """
    수급 등급 산출

    등급 기준:
      S: 동반매도 → 동반매수 전환 (가장 강한 시그널) → confidence × 1.3
      A: 동반매수 + (전환 또는 가속) → confidence × 1.2
      A-: 동반매수 (전환/가속 없음) → confidence × 1.1
      B: 외국인 또는 기관 순매수 → confidence × 1.0
      C: 수급 데이터 없거나 중립 → confidence × 0.9
      D: 외국인 + 기관 동시 순매도 → confidence × 0.7

    Returns:
        (grade, features)
    """
    features = calc_supply_demand_features(ticker)

    foreign_buy = features['foreign_net_5d'] > 0
    inst_buy = features['inst_net_5d'] > 0
    foreign_trend_up = features['foreign_trend'] > 0
    inst_trend_up = features['inst_trend'] > 0

    has_reversal = features['foreign_reversal'] or features['inst_reversal']
    has_accel = features['foreign_accel'] or features['inst_accel']
    both_reversal = features['foreign_reversal'] and features['inst_reversal']

    if both_reversal and foreign_buy and inst_buy:
        # S등급: 동반매도→동반매수 전환 (양쪽 모두 전환)
        grade = 'S'
    elif foreign_buy and inst_buy and (has_reversal or has_accel):
        # A등급: 동반매수 + 전환 또는 가속
        grade = 'A'
    elif foreign_buy and inst_buy:
        # A-등급: 동반매수 (추세 무관, 전환/가속 없음)
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
                      f"기관: {row['inst_net']:>+10,}주  "
                      f"외국인: {row['foreign_net']:>+10,}주")
        else:
            print("  데이터 수집 실패")

        grade, feat = calc_supply_demand_grade(ticker)
        print(f"\n  수급 등급: {grade}")
        print(f"  외국인 5일 합계: {feat['foreign_net_5d']:+.1f}만주")
        print(f"  기관 5일 합계: {feat['inst_net_5d']:+.1f}만주")
        print(f"  외국인 추세: {feat['foreign_trend']:+.2f}")
        print(f"  기관 추세: {feat['inst_trend']:+.2f}")
        print(f"  외국인 전환: {feat['foreign_reversal']}  가속: {feat['foreign_accel']}")
        print(f"  기관 전환: {feat['inst_reversal']}  가속: {feat['inst_accel']}")

        time.sleep(0.5)
