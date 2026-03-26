"""
HollyKR 유니버스 필터링

조건: 보통주 + 스팩/리츠 제외 + 시총 1,000억 이상
WICS 섹터 매핑 (있으면 붙임, 없어도 제외 안 함)
당일 캐시 지원.
"""

import pickle
from datetime import datetime

import pandas as pd

from scripts.krx_data import get_stock_master
from scripts.screeners.holly_kr.config import MIN_MARKET_CAP, WICS_CACHE_FILE
from config import CACHE_DIR


def _load_wics_cache() -> dict:
    """WICS 섹터 캐시 로드"""
    if WICS_CACHE_FILE.exists():
        df = pd.read_csv(WICS_CACHE_FILE, dtype=str, encoding='utf-8-sig')
        return dict(zip(df['Code'], df['WICS_Sector']))
    return {}


def get_universe(use_cache: bool = True) -> pd.DataFrame:
    """
    HollyKR 유니버스 생성.

    필터: 보통주 + 스팩/리츠 제외 + 시총 1,000억 이상

    Returns:
        DataFrame: Code, Name, MarketCap, Sector, Close
    """
    today = datetime.now().strftime('%Y-%m-%d')
    cache_file = CACHE_DIR / f'holly_universe_{today}.pkl'

    # 캐시 로드
    if use_cache and cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                cached = pickle.load(f)
            if cached is not None and len(cached) > 0:
                print(f"\n[유니버스 캐시 로드] {cache_file.name} ({len(cached)}개 종목)")
                return cached
        except Exception:
            pass

    print("\n[유니버스 필터링]")
    print("=" * 50)

    master = get_stock_master()

    # 1. 보통주만 (우선주 제외)
    df = master[master['is_common'] & ~master['is_spac'] & ~master['is_reit']].copy()
    print(f"  보통주 (스팩/리츠 제외): {len(df)}개")

    # 2. 시총 필터
    df = df[df['시가총액'] >= MIN_MARKET_CAP].copy()
    print(f"  시총 {MIN_MARKET_CAP:,}억 이상: {len(df)}개")

    # 3. WICS 섹터 매핑 (없어도 제외 안 함)
    sector_map = _load_wics_cache()
    df['Sector'] = df['종목코드'].map(sector_map).fillna('')

    mapped = (df['Sector'] != '').sum()
    print(f"  WICS 섹터 매핑: {mapped}개 / {len(df)}개")

    result = pd.DataFrame({
        'Code': df['종목코드'].values,
        'Name': df['종목명'].values,
        'MarketCap': df['시가총액'].values,
        'Sector': df['Sector'].values,
        'Close': df['종가'].values,
    }).reset_index(drop=True)

    print(f"\n  최종 유니버스: {len(result)}개 종목")

    # 캐시 저장
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(result, f)
        print(f"  캐시 저장: {cache_file.name}")
    except Exception:
        pass

    return result
