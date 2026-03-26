"""
유니버스 필터링 + WICS 섹터 매핑

보통주, 시총 3000억+, 스팩/리츠/제약 제외, 거래대금 50억+ 필터.
섹터: 와이즈인덱스 WICS 중분류 API → .cache/wics_sectors.csv 캐시.
"""

import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from scripts.krx_data import get_stock_master
from scripts.ohlcv_data import get_ohlcv
from config import BASE_DIR
from scripts.screeners.pairs_trading.config import (
    MIN_MARKET_CAP,
    MIN_TRADING_VALUE,
    EXCLUDE_SECTORS,
    WICS_CACHE_FILE,
)

# WICS 중분류 섹터 코드
WICS_SUB_CODES = [
    'G1010', 'G1510',
    'G2010', 'G2020', 'G2030',
    'G2510', 'G2520', 'G2530', 'G2550', 'G2560',
    'G3010', 'G3020', 'G3030',
    'G3510', 'G3520',
    'G4010', 'G4020', 'G4030', 'G4040', 'G4050',
    'G4510', 'G4520', 'G4530', 'G4540',
    'G5010', 'G5020',
    'G5510',
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def fetch_wics_sectors() -> pd.DataFrame:
    """
    와이즈인덱스 API에서 WICS 중분류 섹터 매핑 수집 → CSV 캐시 저장.
    수동 호출 전용. 필요할 때만 실행.
    """
    print("  WICS 섹터 수집 중 (wiseindex.com)...")

    dt = datetime.now()
    target_dt = None
    for _ in range(30):
        dt_str = dt.strftime('%Y%m%d')
        url = 'https://www.wiseindex.com/Index/GetIndexComponets'
        params = {'ceil_yn': '0', 'dt': dt_str, 'sec_cd': 'G2510'}
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            items = resp.json().get('list', [])
            if items:
                target_dt = dt_str
                break
        except Exception:
            pass
        dt -= timedelta(days=1)

    if not target_dt:
        raise RuntimeError("WICS 데이터 가용 날짜를 찾을 수 없음")

    print(f"  기준일: {target_dt}")

    rows = []
    for sec_cd in WICS_SUB_CODES:
        url = 'https://www.wiseindex.com/Index/GetIndexComponets'
        params = {'ceil_yn': '0', 'dt': target_dt, 'sec_cd': sec_cd}
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            data = resp.json()
            items = data.get('list', [])
            for item in items:
                sector_name = item.get('IDX_NM_KOR', '').replace('WICS ', '')
                rows.append({
                    'Code': item.get('CMP_CD', ''),
                    'Name': item.get('CMP_KOR', ''),
                    'WICS_Sector': sector_name,
                    'WICS_Major': item.get('SEC_NM_KOR', ''),
                })
        except Exception:
            pass
        time.sleep(0.05)

    df = pd.DataFrame(rows)
    df.to_csv(WICS_CACHE_FILE, index=False, encoding='utf-8-sig')
    print(f"  WICS 캐시 저장: {WICS_CACHE_FILE}")
    print(f"  {len(df)}개 종목, {df['WICS_Sector'].nunique()}개 중분류")
    return df


def _load_wics_cache() -> dict:
    """캐시된 WICS 섹터 매핑 로드. 캐시 없으면 자동 수집."""
    if WICS_CACHE_FILE.exists():
        df = pd.read_csv(WICS_CACHE_FILE, dtype=str, encoding='utf-8-sig')
        sector_map = dict(zip(df['Code'], df['WICS_Sector']))
        print(f"  WICS 캐시 로드: {len(sector_map)}개 종목, "
              f"{df['WICS_Sector'].nunique()}개 섹터")
        return sector_map

    print("  WICS 캐시 없음 → 수집 시작")
    df = fetch_wics_sectors()
    return dict(zip(df['Code'], df['WICS_Sector']))


def _calc_avg_trading_value(tickers: list, days: int = 20) -> dict:
    """OHLCV에서 평균 거래대금(억원) 계산: Close × Volume."""
    result = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers, 1):
        df = get_ohlcv(ticker, days=days + 10, use_cache=True)
        if df is None or len(df) < 5:
            continue
        df = df.tail(days)
        trading_value = (df['Close'] * df['Volume']).mean() / 100_000_000
        result[ticker] = trading_value
        if i % 100 == 0:
            print(f"  거래대금 진행: {i}/{total}")
    print(f"  거래대금 계산 완료: {len(result)}개 종목")
    return result


def _check_trading_halt(tickers: list, days: int = 20,
                        max_halt_days: int = 5) -> set:
    """OHLCV에서 거래량 0인 날 5일+ 종목 식별."""
    halted = set()
    for ticker in tickers:
        df = get_ohlcv(ticker, days=days + 10, use_cache=True)
        if df is None:
            halted.add(ticker)
            continue
        df = df.tail(days)
        if (df['Volume'] == 0).sum() >= max_halt_days:
            halted.add(ticker)
    if halted:
        print(f"  거래정지/거래량부족 종목 제외: {len(halted)}개")
    return halted


def get_universe() -> pd.DataFrame:
    """
    페어 트레이딩 유니버스 생성.

    Returns:
        DataFrame: Code, Name, MarketCap, WICS_Sector, AvgTradingValue
    """
    print("\n[1/7] 유니버스 필터링")
    print("=" * 50)

    master = get_stock_master()

    df = master[master['is_common']].copy()
    print(f"  보통주: {len(df)}개")

    df = df[~df['is_spac'] & ~df['is_reit']].copy()
    print(f"  스팩/리츠 제외 후: {len(df)}개")

    df = df[df['시가총액'] >= MIN_MARKET_CAP].copy()
    print(f"  시총 {MIN_MARKET_CAP}억 이상: {len(df)}개")

    sector_map = _load_wics_cache()
    df['WICS_Sector'] = df['종목코드'].map(sector_map).fillna('')

    no_sector = df['WICS_Sector'] == ''
    if no_sector.sum() > 0:
        print(f"  WICS 미매핑 종목: {no_sector.sum()}개 (제외)")
        df = df[~no_sector].copy()

    excluded = df['WICS_Sector'].isin(EXCLUDE_SECTORS)
    if excluded.sum() > 0:
        print(f"  제외 섹터 제거: {excluded.sum()}개")
        df = df[~excluded].copy()

    print("  거래대금 계산 중 (Close×Volume)...")
    avg_values = _calc_avg_trading_value(df['종목코드'].tolist())
    df['AvgTradingValue'] = df['종목코드'].map(avg_values).fillna(0)
    before = len(df)
    df = df[df['AvgTradingValue'] >= MIN_TRADING_VALUE].copy()
    print(f"  거래대금 {MIN_TRADING_VALUE}억 이상: {len(df)}개 (제외: {before - len(df)}개)")

    halted = _check_trading_halt(df['종목코드'].tolist())
    if halted:
        df = df[~df['종목코드'].isin(halted)].copy()

    sector_counts = df['WICS_Sector'].value_counts()
    single_sectors = sector_counts[sector_counts < 2].index
    if len(single_sectors) > 0:
        df = df[~df['WICS_Sector'].isin(single_sectors)].copy()
        print(f"  단일 종목 섹터 제외: {len(single_sectors)}개 섹터")

    result = pd.DataFrame({
        'Code': df['종목코드'].values,
        'Name': df['종목명'].values,
        'MarketCap': df['시가총액'].values,
        'WICS_Sector': df['WICS_Sector'].values,
        'AvgTradingValue': df['AvgTradingValue'].values,
    }).reset_index(drop=True)

    print(f"\n  최종 유니버스: {len(result)}개 종목, "
          f"{result['WICS_Sector'].nunique()}개 섹터")
    return result
