"""
KIS OpenAPI 기반 KRX 업종 분류 수집 모듈

WICS 대체용. KIS `inquire-price` 엔드포인트의 `bstp_kor_isnm` 필드(KRX 업종)를
종목별로 수집하여 CSV 캐시에 저장한다.

사용법:
    # 단일 종목
    sector = get_sector('005930')           # '전기·전자'

    # 전종목 배치 수집 → 캐시 저장
    python -m scripts.kis_sector_data --collect

    # 캐시된 전체 맵 로드
    from scripts.kis_sector_data import load_sector_map
    sector_map = load_sector_map()
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import requests

from config import CACHE_DIR
from scripts.investor_data import _get_kis_token, _limiter, KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL

SECTOR_CACHE_FILE = CACHE_DIR / 'kis_sectors.csv'
CACHE_MAX_DAYS = 30  # 업종은 자주 안 변함


# ============================================================================
# 단일 종목 조회
# ============================================================================

def _fetch_sector(ticker: str) -> Optional[str]:
    """KIS inquire-price로 업종명(bstp_kor_isnm) 추출."""
    token = _get_kis_token()
    if not token:
        return None

    code6 = str(ticker).zfill(6)
    url = f'{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price'
    headers = {
        'authorization': f'Bearer {token}',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
        'tr_id': 'FHKST01010100',
        'custtype': 'P',
    }
    params = {
        'FID_COND_MRKT_DIV_CODE': 'J',
        'FID_INPUT_ISCD': code6,
    }

    try:
        _limiter.wait()
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get('rt_cd') != '0':
            return None
        out = data.get('output', {})
        sector = out.get('bstp_kor_isnm', '').strip()
        return sector if sector else None
    except Exception:
        return None


# ============================================================================
# 캐시 로드/저장
# ============================================================================

def load_sector_map() -> Dict[str, str]:
    """
    캐시된 종목→업종 매핑 로드.

    Returns:
        {'005930': '전기·전자', ...}  캐시 없으면 빈 dict
    """
    if not SECTOR_CACHE_FILE.exists():
        return {}
    try:
        df = pd.read_csv(SECTOR_CACHE_FILE, dtype=str, encoding='utf-8-sig')
        return dict(zip(df['Code'], df['Sector']))
    except Exception:
        return {}


def _save_sector_map(sector_map: Dict[str, str]):
    rows = [{'Code': code, 'Sector': sector} for code, sector in sector_map.items()]
    df = pd.DataFrame(rows)
    df.to_csv(SECTOR_CACHE_FILE, index=False, encoding='utf-8-sig')


# ============================================================================
# 공개 API
# ============================================================================

def get_sector(ticker: str, use_cache: bool = True) -> Optional[str]:
    """
    단일 종목 업종 조회 (캐시 우선).
    """
    if use_cache:
        m = load_sector_map()
        if ticker in m:
            return m[ticker]
    return _fetch_sector(ticker)


def collect_all_sectors(tickers: list, verbose: bool = True) -> Dict[str, str]:
    """
    전종목 업종 배치 수집 → CSV 캐시 저장.
    기존 캐시와 병합 (누락 종목만 신규 수집).
    """
    existing = load_sector_map()
    result = dict(existing)

    missing = [t for t in tickers if t not in existing]
    total = len(missing)

    if total == 0:
        if verbose:
            print(f"  캐시 완전함: {len(existing)}개 종목")
        return result

    if verbose:
        print(f"  전체 {len(tickers)}개 중 신규 {total}개 수집 시작...")

    success = 0
    failed = 0
    start = time.time()

    for i, ticker in enumerate(missing, 1):
        sector = _fetch_sector(ticker)
        if sector:
            result[ticker] = sector
            success += 1
        else:
            failed += 1

        if verbose and i % 100 == 0:
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            print(f"  진행: {i}/{total} (성공 {success}, 실패 {failed}) "
                  f"[{rate:.1f}/s, ETA {eta:.0f}초]")

    # 주기적 저장 (마지막)
    _save_sector_map(result)
    elapsed = time.time() - start
    if verbose:
        print(f"  완료: {success}개 성공, {failed}개 실패 ({elapsed:.1f}초)")
        print(f"  캐시 저장: {SECTOR_CACHE_FILE}")

    return result


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='KIS 업종 데이터 수집')
    parser.add_argument('--collect', action='store_true',
                        help='전종목 업종 수집 (유니버스 기반)')
    parser.add_argument('--test', action='store_true',
                        help='10종목 테스트')
    args = parser.parse_args()

    if args.test:
        test_tickers = [
            ('005930', '삼성전자'),
            ('000660', 'SK하이닉스'),
            ('035420', 'NAVER'),
            ('035720', '카카오'),
            ('005380', '현대차'),
            ('000270', '기아'),
            ('068270', '셀트리온'),
            ('207940', '삼성바이오로직스'),
            ('028260', '삼성물산'),
            ('012450', '한화에어로스페이스'),
        ]
        print("KIS 업종 분류 테스트")
        print("=" * 50)
        for ticker, name in test_tickers:
            sector = _fetch_sector(ticker)
            print(f"  {name}({ticker}): {sector}")
        return

    if args.collect:
        from scripts.krx_data import get_filtered_stocks
        print("전종목 업종 수집")
        print("=" * 50)
        stocks = get_filtered_stocks(min_market_cap=1000)
        tickers = stocks['Code'].tolist()
        print(f"  대상: {len(tickers)}개 종목")
        collect_all_sectors(tickers, verbose=True)
        return

    parser.print_help()


if __name__ == '__main__':
    main()
