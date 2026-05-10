"""
HollyKR 유니버스 필터링

조건: 보통주 + 스팩/리츠 제외 + 시총 1,000억 이상
섹터: KIS 업종 (primary) + WICS (fallback)
당일 캐시 지원.
"""

import pickle
from datetime import datetime

import pandas as pd

from scripts.krx_data import get_stock_master
from scripts.kis_sector_data import load_sector_map as load_kis_sectors
from scripts.screeners.holly_kr.config import MIN_MARKET_CAP, WICS_CACHE_FILE
from config import CACHE_DIR


def _load_wics_cache() -> dict:
    """WICS 섹터 캐시 로드 (폴백용)"""
    if WICS_CACHE_FILE.exists():
        df = pd.read_csv(WICS_CACHE_FILE, dtype=str, encoding='utf-8-sig')
        return dict(zip(df['Code'], df['WICS_Sector']))
    return {}


def _load_sector_map() -> dict:
    """KIS 우선, WICS 폴백으로 종목→섹터 매핑 병합"""
    kis = load_kis_sectors()
    wics = _load_wics_cache()
    # KIS가 없는 종목만 WICS로 보완
    merged = {**wics, **kis}
    return merged


def get_universe(use_cache: bool = True) -> pd.DataFrame:
    """
    HollyKR 유니버스 생성.

    필터: 보통주 + 스팩/리츠 제외 + 시총 1,000억 이상

    Returns:
        DataFrame: Code, Name, MarketCap, Sector, Close
    """
    today = datetime.now().strftime('%Y-%m-%d')
    cache_file = CACHE_DIR / f'holly_universe_{today}.pkl'

    # 캐시 로드 (당일)
    if use_cache and cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                cached = pickle.load(f)
            if cached is not None and len(cached) > 0:
                # Phase G-9: KRX 공식 마스터 CSV로 종목코드 100% 정확 검증
                # ETF/ETN/우선주/REIT/SPAC 모두 자동 제외 (CSV에 보통주만)
                try:
                    from scripts.krx_master_csv import filter_to_krx_master, get_code_to_name
                    before = len(cached)
                    if 'Code' in cached.columns:
                        # 1. KRX 공식 보통주만 필터 (ETF/우선주/SPAC/REIT 자동 제외)
                        cached = filter_to_krx_master(cached, code_col='Code')
                        # 2. 종목코드 ↔ 종목명 매핑 정확화 (네이버 데이터 종목명 잘못된 경우)
                        if 'Name' in cached.columns:
                            code_to_name = get_code_to_name()
                            cached['Name'] = cached['Code'].astype(str).str.zfill(6).map(code_to_name).fillna(cached['Name'])
                    if before > len(cached):
                        print(f"\n[유니버스 캐시 로드 + KRX CSV 검증] {cache_file.name}")
                        print(f"  원본 {before}개 → KRX 보통주만 {len(cached)}개 (ETF/우선주/특수 제외)")
                    else:
                        print(f"\n[유니버스 캐시 로드 + KRX 검증] {cache_file.name} ({len(cached)}개)")
                except Exception as e:
                    # KRX CSV 없으면 기존 fallback (정규식)
                    from scripts.krx_data import ETF_PATTERN
                    before = len(cached)
                    if 'Name' in cached.columns:
                        is_etf = cached['Name'].apply(lambda x: bool(ETF_PATTERN.search(str(x))))
                        cached = cached[~is_etf].copy()
                    if 'Code' in cached.columns:
                        cached = cached[cached['Code'].astype(str).str.endswith('0')].copy()
                    print(f"\n[유니버스 캐시 + 정규식 필터 fallback] {cache_file.name} ({len(cached)}개) [KRX CSV: {e}]")
                return cached.reset_index(drop=True)
        except Exception as e:
            print(f"  캐시 로드 오류: {e}")
            pass

    print("\n[유니버스 필터링]")
    print("=" * 50)

    # KRX/FDR 차단 시 가장 최근 캐시 fallback (글로벌 IP/주말 안정성)
    try:
        master = get_stock_master()
    except Exception as e:
        print(f"  [KRX/FDR 차단] {type(e).__name__}: {str(e)[:100]}")
        # 가장 최근 캐시 검색
        recent_caches = sorted(CACHE_DIR.glob('holly_universe_*.pkl'), reverse=True)
        if recent_caches:
            latest = recent_caches[0]
            try:
                with open(latest, 'rb') as f:
                    cached = pickle.load(f)
                if cached is not None and len(cached) > 0:
                    print(f"  [Fallback] 최근 캐시 사용: {latest.name} ({len(cached)}개)")
                    return cached
            except Exception:
                pass
        raise RuntimeError("KRX/FDR 차단 + 캐시 없음 — 데이터 소스 복구 필요")

    # 1. 보통주만 (우선주 + 스팩 + 리츠 + ETF 모두 제외)
    # is_common = 종목코드 끝자리 0 (우선주는 5/7/9 — 자동 제외됨)
    # 캐시 데이터에 is_etf 컬럼 없으면 런타임 생성
    if 'is_etf' not in master.columns:
        from scripts.krx_data import ETF_PATTERN
        master = master.copy()
        master['is_etf'] = master['종목명'].apply(
            lambda x: bool(ETF_PATTERN.search(str(x))))
    total = len(master)
    pref_count = (~master['is_common']).sum()  # 우선주
    spac_count = master['is_spac'].sum()
    reit_count = master['is_reit'].sum()
    etf_count = master['is_etf'].sum()
    df = master[
        master['is_common'] & ~master['is_spac'] & ~master['is_reit'] & ~master['is_etf']
    ].copy()
    print(f"  필터 — 우선주 {pref_count}개 / 스팩 {spac_count}개 / 리츠 {reit_count}개 / ETF {etf_count}개 제외")
    print(f"  보통주 only: {len(df)}개 (전체 {total}개 중)")

    # 2. 시총 필터
    df = df[df['시가총액'] >= MIN_MARKET_CAP].copy()
    print(f"  시총 {MIN_MARKET_CAP:,}억 이상: {len(df)}개")

    # 3. 섹터 매핑 (KIS 우선, WICS 폴백 — 없어도 제외 안 함)
    sector_map = _load_sector_map()
    df['Sector'] = df['종목코드'].map(sector_map).fillna('')

    mapped = (df['Sector'] != '').sum()
    print(f"  섹터 매핑 (KIS+WICS): {mapped}개 / {len(df)}개")

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
