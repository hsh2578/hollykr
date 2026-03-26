"""
KRX 종목 마스터 수집 모듈

수집 순서: KRX OTP CSV → finder_stkisu + MDCSTAT01501 → 네이버 모바일 API → FDR 폴백

사용법:
    from scripts.krx_data import get_stock_master, get_filtered_stocks
    stocks = get_stock_master()
    filtered = get_filtered_stocks(min_market_cap=1000)
"""

import io
import re
import time
import datetime

import pandas as pd
import requests

# ============================================================================
# 상수
# ============================================================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

KRX_GENERATE_URL = 'http://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd'
KRX_DOWNLOAD_URL = 'http://data.krx.co.kr/comm/fileDn/download_csv/download.cmd'
KRX_REFERER = 'http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd'

_KRX_JSON_URL = 'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
_KRX_JSON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'http://data.krx.co.kr/',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
}

# 금융 업종 키워드
FINANCIAL_SECTORS = {'금융'}
FINANCIAL_KEYWORDS = ['은행', '보험', '증권', '캐피탈', '저축은행', '카드']

# 스팩/리츠 패턴
SPAC_PATTERN = re.compile(r'스팩|SPAC|기업인수목적', re.IGNORECASE)
REIT_PATTERN = re.compile(r'리츠|REIT|부동산투자', re.IGNORECASE)


# ============================================================================
# KRX OTP 방식
# ============================================================================

def _get_otp(params: dict) -> str:
    """KRX OTP 발급"""
    headers = {**HEADERS, 'Referer': KRX_REFERER}
    resp = requests.post(KRX_GENERATE_URL, data=params, headers=headers, timeout=15)
    resp.raise_for_status()
    otp = resp.text.strip()
    if not otp or otp == 'LOGOUT':
        raise ValueError(f"OTP 발급 실패: {otp!r}")
    return otp


def _download_csv(otp: str) -> pd.DataFrame:
    """KRX CSV 다운로드"""
    resp = requests.post(
        KRX_DOWNLOAD_URL,
        data={'code': otp},
        headers={**HEADERS, 'Referer': KRX_REFERER},
        timeout=30
    )
    resp.raise_for_status()
    return pd.read_csv(io.BytesIO(resp.content), encoding='euc-kr')


# ============================================================================
# KRX JSON 방식 (finder_stkisu)
# ============================================================================

def _fetch_krx_listing(trd_dd: str) -> list:
    """KRX finder_stkisu 엔드포인트에서 전 종목 리스트 수집"""
    params = {
        'bld': 'dbms/comm/finder/finder_stkisu',
        'mktsel': 'ALL',
        'searchText': '',
    }
    resp = requests.post(_KRX_JSON_URL, data=params, headers=_KRX_JSON_HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get('block1', [])


def _fetch_market_cap_krx(trd_dd: str) -> dict:
    """KRX MDCSTAT01501에서 시가총액+종가 수집. 최근 3거래일 소급."""
    dates_to_try = [trd_dd]
    dt = datetime.datetime.strptime(trd_dd, '%Y%m%d')
    for _ in range(3):
        dt -= datetime.timedelta(days=1)
        while dt.weekday() >= 5:
            dt -= datetime.timedelta(days=1)
        dates_to_try.append(dt.strftime('%Y%m%d'))

    for date in dates_to_try:
        result = {}
        for mkt_id in ['STK', 'KSQ']:
            params = {
                'bld': 'dbms/MDC/STAT/standard/MDCSTAT01501',
                'mktId': mkt_id,
                'trdDd': date,
                'share': '1',
                'money': '1',
                'csvxls_isNo': 'false',
            }
            try:
                resp = requests.post(_KRX_JSON_URL, data=params, headers=_KRX_JSON_HEADERS, timeout=30)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get('OutBlock_1', []):
                    code = str(item.get('ISU_SRT_CD', '')).strip().zfill(6)
                    if code and len(code) == 6:
                        result[code] = {
                            'cap': _parse_number(item.get('MKTCAP', '0')) / 100_000_000,
                            'close': _parse_number(item.get('TDD_CLSPRC', '0')),
                        }
            except Exception:
                continue
        if result:
            print(f"  MDCSTAT01501 성공 ({date}, {len(result)}개)")
            return result

    return {}


# ============================================================================
# 네이버 모바일 API 폴백
# ============================================================================

def _fetch_market_cap_naver() -> dict:
    """네이버 증권 모바일 API에서 전종목 시가총액+종가 수집"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    result = {}

    for market in ['KOSPI', 'KOSDAQ']:
        page = 1
        while True:
            url = (f'https://m.stock.naver.com/api/stocks/marketValue/{market}'
                   f'?page={page}&pageSize=100')
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  네이버 API 오류 ({market} p{page}): {e}")
                break

            stocks = data.get('stocks', [])
            if not stocks:
                break

            for s in stocks:
                code = str(s.get('itemCode', '')).strip().zfill(6)
                if not code or len(code) != 6:
                    continue
                cap_raw = str(s.get('marketValue', '0')).replace(',', '')
                close_raw = str(s.get('closePrice', '0')).replace(',', '')
                try:
                    cap = float(cap_raw)
                except ValueError:
                    cap = 0.0
                try:
                    close = float(close_raw)
                except ValueError:
                    close = 0.0
                result[code] = {'cap': cap, 'close': close}

            total = data.get('totalCount', 0)
            if page * 100 >= total:
                break
            page += 1
            time.sleep(0.3)

    if result:
        print(f"  네이버 모바일 API 성공: {len(result)}개 종목")
    return result


# ============================================================================
# 유틸리티
# ============================================================================

def _parse_number(val) -> float:
    try:
        return float(str(val).replace(',', ''))
    except (ValueError, TypeError):
        return 0.0


def _is_common_stock(code: str) -> bool:
    """보통주 여부 (끝자리 0이 보통주, 5가 우선주)"""
    if not code or len(code) < 6:
        return False
    return code[-1] == '0'


def is_financial_stock(sector: str, name: str = '') -> bool:
    """금융주 여부 판별"""
    if not sector:
        return False
    if sector in FINANCIAL_SECTORS:
        return True
    for keyword in FINANCIAL_KEYWORDS:
        if keyword in str(sector) or keyword in str(name):
            return True
    return False


# ============================================================================
# 메인 수집 함수
# ============================================================================

def get_stock_master(market: str = 'ALL', use_cache: bool = True) -> pd.DataFrame:
    """
    전 종목 마스터 데이터 수집.
    수집 순서: 캐시 → OTP CSV → finder_stkisu+MDCSTAT01501 → 네이버 → FDR

    Returns:
        DataFrame: 종목코드, 종목명, 시장구분, 시가총액(억원), 종가, is_common, is_spac, is_reit
    """
    import pickle
    from pathlib import Path
    cache_dir = Path(__file__).parent.parent / '.cache'
    today = datetime.datetime.now().strftime('%Y%m%d')
    today_dash = datetime.datetime.now().strftime('%Y-%m-%d')

    # 캐시 로드 (당일)
    if use_cache:
        cache_file = cache_dir / f'krx_master_{today_dash}.pkl'
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    cached = pickle.load(f)
                if cached is not None and len(cached) > 100:
                    print(f"종목 마스터 캐시 로드: {cache_file.name} ({len(cached)}개 종목)")
                    return cached
            except Exception:
                pass
    df = None

    # 1차: KRX OTP CSV
    print("종목 마스터 수집 중... (KRX OTP)")
    try:
        rows = []
        for mkt_id, market_name in [('STK', 'KOSPI'), ('KSQ', 'KOSDAQ')]:
            otp = _get_otp({
                'mktId': mkt_id,
                'trdDd': today,
                'money': '1',
                'csvxls_isNo': 'false',
                'name': 'fileDown',
                'url': 'dbms/MDC/STAT/standard/MDCSTAT01501',
            })
            mkt_df = _download_csv(otp)

            cols = mkt_df.columns.tolist()
            code_col = next((c for c in cols if '코드' in str(c)), cols[0])
            name_col = next((c for c in cols if '종목명' in str(c)), None)
            cap_col = next((c for c in cols if '시가총액' in str(c)), None)
            close_col = next((c for c in cols if '현재가' in str(c) or '종가' in str(c)), None)

            for _, row in mkt_df.iterrows():
                code = str(row[code_col]).strip().zfill(6)
                if not code or len(code) != 6:
                    continue
                rows.append({
                    '종목코드': code,
                    '종목명': str(row[name_col]).strip() if name_col else '',
                    '시장구분': market_name,
                    '시가총액': _parse_number(row[cap_col]) / 100_000_000 if cap_col else 0.0,
                    '종가': _parse_number(row[close_col]) if close_col else 0.0,
                })

        if rows:
            df = pd.DataFrame(rows)
            print(f"  KRX OTP 성공: {len(df)}개 종목")
    except Exception as e:
        print(f"  KRX OTP 실패: {e}")

    # 2차: finder_stkisu + 시가총액 보충
    if df is None or len(df) == 0:
        print("  finder_stkisu 방식으로 재시도...")
        try:
            items = _fetch_krx_listing(today)
            if not items:
                raise ValueError("finder_stkisu 빈 응답")

            rows = []
            for item in items:
                code = str(item.get('short_code', '')).strip().zfill(6)
                if not code or len(code) != 6:
                    continue
                mkt_code = str(item.get('marketCode', '')).strip()
                market_name = 'KOSPI' if mkt_code == 'STK' else 'KOSDAQ' if mkt_code == 'KSQ' else mkt_code
                rows.append({
                    '종목코드': code,
                    '종목명': str(item.get('codeName', '')).strip(),
                    '시장구분': market_name,
                    '시가총액': 0.0,
                    '종가': 0.0,
                })

            if rows:
                df = pd.DataFrame(rows)
                print(f"  finder_stkisu 성공: {len(df)}개 종목")

                # 시가총액 보충: KRX → 네이버
                try:
                    cap_data = _fetch_market_cap_krx(today)
                    if not cap_data:
                        print("  MDCSTAT01501 실패 → 네이버 모바일 API 시도...")
                        cap_data = _fetch_market_cap_naver()
                    if cap_data:
                        df['시가총액'] = df['종목코드'].map(
                            lambda c: cap_data.get(c, {}).get('cap', 0.0))
                        df['종가'] = df['종목코드'].map(
                            lambda c: cap_data.get(c, {}).get('close', 0.0))
                except Exception as e:
                    print(f"  시가총액 보충 실패: {e}")

        except Exception as e:
            print(f"  finder_stkisu 실패: {e}")

    # 3차: FDR 폴백
    if df is None or len(df) == 0:
        import FinanceDataReader as fdr
        print("  FDR 폴백으로 재시도...")

        def _fetch_fdr(mkt, retries=3, delay=10):
            for attempt in range(retries):
                try:
                    result = fdr.StockListing(mkt)
                    if result is not None and len(result) > 0:
                        return result
                except Exception as ex:
                    print(f"    [{mkt}] 오류: {ex} ({attempt+1}/{retries})")
                time.sleep(delay)
            raise RuntimeError(f"fdr.StockListing('{mkt}') 실패")

        kospi = _fetch_fdr('KOSPI')
        kospi['시장구분'] = 'KOSPI'
        kosdaq = _fetch_fdr('KOSDAQ')
        kosdaq['시장구분'] = 'KOSDAQ'
        fdr_df = pd.concat([kospi, kosdaq], ignore_index=True)
        fdr_df = fdr_df.rename(columns={'Code': '종목코드', 'Name': '종목명', 'Close': '종가'})
        if 'Marcap' in fdr_df.columns:
            fdr_df['시가총액'] = fdr_df['Marcap'] / 100_000_000
        elif 'MarketCap' in fdr_df.columns:
            fdr_df['시가총액'] = fdr_df['MarketCap'] / 100_000_000
        else:
            fdr_df['시가총액'] = 0
        df = fdr_df

        # FDR 시가총액 없으면 네이버 보충
        if df['시가총액'].sum() == 0:
            try:
                cap_data = _fetch_market_cap_naver()
                if cap_data:
                    df['시가총액'] = df['종목코드'].map(
                        lambda c: cap_data.get(c, {}).get('cap', 0.0))
                    df['종가'] = df['종목코드'].map(
                        lambda c: cap_data.get(c, {}).get('close', 0.0))
            except Exception:
                pass

    # 공통 후처리
    df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
    df['is_common'] = df['종목코드'].apply(_is_common_stock)
    df['is_spac'] = df['종목명'].apply(lambda x: bool(SPAC_PATTERN.search(str(x))))
    df['is_reit'] = df['종목명'].apply(lambda x: bool(REIT_PATTERN.search(str(x))))

    if 'Dept' in df.columns:
        df['업종'] = df['Dept'].replace('', '기타').fillna('기타')
    else:
        df['업종'] = '기타'

    # 시가총액 sentinel
    if '시가총액' not in df.columns or df['시가총액'].sum() == 0:
        df['시가총액'] = 1001.0
        print("  주의: 시가총액 데이터 없음 — sentinel(1001억) 설정")

    print(f"  전체 종목: {len(df)}개, 보통주: {df['is_common'].sum()}개")

    # 캐시 저장
    try:
        cache_file = cache_dir / f'krx_master_{today_dash}.pkl'
        with open(cache_file, 'wb') as f:
            pickle.dump(df, f)
    except Exception:
        pass

    return df


def get_filtered_stocks(min_market_cap: int = 1000) -> pd.DataFrame:
    """
    필터링된 종목 리스트 (시총 기준, 보통주, 스팩/리츠 제외)

    Returns:
        DataFrame: Code, Name, MarketCap, Market, Close, is_common, is_spac, is_reit
    """
    df = get_stock_master()

    if '시가총액' in df.columns and df['시가총액'].sum() > 0:
        df = df[df['시가총액'] >= min_market_cap].copy()

    result = pd.DataFrame({
        'Code': df['종목코드'],
        'Name': df['종목명'],
        'MarketCap': df.get('시가총액', pd.Series(dtype=float)),
        'Market': df.get('시장구분', 'KOSPI'),
        'Close': df.get('종가', pd.Series(dtype=float)),
        'Sector': df.get('업종', ''),
        'is_common': df['is_common'],
        'is_spac': df['is_spac'],
        'is_reit': df['is_reit'],
    })

    print(f"  시가총액 {min_market_cap}억 이상: {len(result)}개 종목")
    return result.reset_index(drop=True)


if __name__ == '__main__':
    print("=" * 60)
    print("KRX 종목 마스터 테스트")
    print("=" * 60)
    stocks = get_stock_master()
    print(f"\n전체 종목 수: {len(stocks)}")
    print(stocks[['종목코드', '종목명', '시가총액', '시장구분']].head(10))
