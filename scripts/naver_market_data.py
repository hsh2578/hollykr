"""네이버 금융 시가총액 순위 스크래핑 — KRX 차단 fallback.

KRX (data.krx.co.kr) 글로벌 IP 차단 시 동일 데이터를 네이버 금융에서 수집.
출처: https://finance.naver.com/sise/sise_market_sum.naver?sosok={0,1}&page={N}
- sosok=0: KOSPI
- sosok=1: KOSDAQ
- 페이지당 50종목, 시가총액 순 정렬

Returns:
    DataFrame: ['Code', 'Name', 'MarketCap', 'Close', 'Market', 'PER', 'ROE',
                'Volume', 'ForeignRatio', 'Shares']
    - MarketCap: 억원 단위
    - Close: 원

CLAUDE.md (Phase G-9 fallback): KRX 403 → 자동 호출.
"""
import io
import re
import time
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

NAVER_SISE_URL = "https://finance.naver.com/sise/sise_market_sum.naver"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

CACHE_DIR = Path(__file__).resolve().parent.parent / '.cache'
CACHE_DIR.mkdir(exist_ok=True, parents=True)


def _fetch_page(market: str, page: int, timeout: int = 15) -> Optional[str]:
    """단일 페이지 HTML 다운로드. 실패 시 None."""
    sosok = 0 if market.upper() == 'KOSPI' else 1
    params = {'sosok': sosok, 'page': page}
    try:
        resp = requests.get(NAVER_SISE_URL, params=params,
                            headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        # 네이버 금융은 euc-kr 인코딩
        resp.encoding = 'euc-kr'
        return resp.text
    except Exception as e:
        print(f"    [네이버 페이지 {market} p{page} 실패] {type(e).__name__}: {str(e)[:60]}")
        return None


def _parse_page(html: str) -> tuple[pd.DataFrame, int]:
    """HTML → (종목 DataFrame, 마지막 페이지 번호)."""
    # 1. 종목코드 추출 (순서대로)
    codes = re.findall(r'/item/main\.naver\?code=(\d{6})', html)
    # 같은 종목이 두 번 나오는 경우 있음 (이름 + 차트 링크) → 순서 유지 + 중복 제거
    seen = set()
    unique_codes = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique_codes.append(c)

    # 2. 테이블 파싱 (T1이 시총 테이블)
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return pd.DataFrame(), 0

    target = None
    for t in tables:
        # 시총 테이블 식별: '종목명' + '시가총액' 컬럼
        cols = [str(c) for c in t.columns]
        if '종목명' in cols and '시가총액' in cols:
            target = t
            break

    if target is None or len(target) == 0:
        return pd.DataFrame(), 0

    # 3. 빈 행 제거 (N이 NaN인 행)
    df = target.dropna(subset=['N']).copy()
    df = df.reset_index(drop=True)

    # 4. 종목코드 매핑 (행 순서 = 종목코드 순서)
    if len(unique_codes) >= len(df):
        df['Code'] = unique_codes[:len(df)]
    else:
        # 코드 부족 시 빈 문자열
        df['Code'] = unique_codes + [''] * (len(df) - len(unique_codes))

    # 5. 마지막 페이지 추출
    last_page_match = re.search(r'page=(\d+)[^>]*>\s*맨뒤', html)
    last_page = int(last_page_match.group(1)) if last_page_match else 0

    return df, last_page


def fetch_naver_market_cap(market: str = 'KOSPI',
                           max_pages: int = 50,
                           min_market_cap_eok: int = 1000,
                           sleep_sec: float = 0.3,
                           verbose: bool = True) -> pd.DataFrame:
    """네이버 금융에서 시가총액 순위 전체 수집.

    Args:
        market: 'KOSPI' | 'KOSDAQ'
        max_pages: 최대 페이지 (50 = 2500종목, 충분)
        min_market_cap_eok: 시가총액 최소 (억원). 미달 종목 발견 시 조기 종료.
        sleep_sec: 페이지간 대기 (네이버 차단 방지)

    Returns:
        DataFrame: [Code, Name, MarketCap(억), Close, Market, ...]
    """
    if verbose:
        print(f"\n[네이버 금융 {market}] 시총 {min_market_cap_eok}억+ 수집 중...")

    all_rows = []
    last_known_page = max_pages

    for page in range(1, max_pages + 1):
        if page > last_known_page:
            break

        html = _fetch_page(market, page)
        if html is None:
            time.sleep(sleep_sec * 2)  # 실패 시 대기 길게
            continue

        df, last_page = _parse_page(html)
        if last_page > 0:
            last_known_page = min(last_known_page, last_page)

        if df.empty:
            if verbose:
                print(f"    [{market} p{page}] 데이터 없음")
            break

        # 시가총액 필터 (억원, 종가 N/A 제거)
        df['MarketCap'] = pd.to_numeric(df['시가총액'], errors='coerce')
        df['Close'] = pd.to_numeric(df['현재가'], errors='coerce')
        df = df.dropna(subset=['MarketCap', 'Close'])

        if df.empty:
            continue

        # min_market_cap 미달 발견 시 조기 종료 (시총 순 정렬이라)
        if df['MarketCap'].min() < min_market_cap_eok:
            df = df[df['MarketCap'] >= min_market_cap_eok]
            all_rows.append(df)
            if verbose:
                print(f"    [{market} p{page}] {len(df)}개 (시총 {min_market_cap_eok}억 컷 도달)")
            break

        all_rows.append(df)
        if verbose and page % 10 == 0:
            print(f"    [{market} p{page}/{last_known_page}] 누적 {sum(len(d) for d in all_rows)}개")

        time.sleep(sleep_sec)

    if not all_rows:
        return pd.DataFrame()

    result = pd.concat(all_rows, ignore_index=True)

    # 표준 컬럼 정리
    out = pd.DataFrame({
        'Code': result['Code'].values,
        'Name': result['종목명'].values,
        'MarketCap': result['MarketCap'].values.astype(int),  # 억원
        'Close': result['Close'].values.astype(int),          # 원
        'Market': market,
        'PER': pd.to_numeric(result['PER'], errors='coerce'),
        'ROE': pd.to_numeric(result['ROE'], errors='coerce'),
        'Volume': pd.to_numeric(result['거래량'], errors='coerce'),
        'ForeignRatio': pd.to_numeric(result['외국인비율'], errors='coerce'),
        'Shares': pd.to_numeric(result['상장주식수'], errors='coerce'),
    })

    # 빈 종목코드 + 중복 제거
    out = out[out['Code'].astype(str).str.len() == 6].copy()
    out = out.drop_duplicates(subset=['Code']).reset_index(drop=True)

    if verbose:
        print(f"  [{market} 완료] {len(out)}개 종목 (시총 {min_market_cap_eok}억+)")

    return out


def fetch_all_markets(min_market_cap_eok: int = 1000,
                      save_csv: bool = True,
                      verbose: bool = True) -> pd.DataFrame:
    """KOSPI + KOSDAQ 통합 수집 + CSV 자동 저장.

    Returns:
        DataFrame: 시총 순 정렬, 양 시장 통합
    """
    kospi = fetch_naver_market_cap('KOSPI', min_market_cap_eok=min_market_cap_eok,
                                    verbose=verbose)
    kosdaq = fetch_naver_market_cap('KOSDAQ', min_market_cap_eok=min_market_cap_eok,
                                     verbose=verbose)

    if kospi.empty and kosdaq.empty:
        if verbose:
            print("  [네이버 fallback 실패] 양 시장 모두 데이터 없음")
        return pd.DataFrame()

    combined = pd.concat([kospi, kosdaq], ignore_index=True)
    combined = combined.sort_values('MarketCap', ascending=False).reset_index(drop=True)

    if save_csv:
        today = datetime.now().strftime('%Y-%m-%d')
        csv_path = CACHE_DIR / f'naver_market_{today}.csv'
        combined.to_csv(csv_path, index=False, encoding='utf-8-sig')
        if verbose:
            print(f"\n  [CSV 저장] {csv_path.name} ({len(combined)}개)")

    return combined


if __name__ == '__main__':
    # 단독 실행 테스트
    df = fetch_all_markets(min_market_cap_eok=1000, save_csv=True, verbose=True)
    print(f"\n[최종] 총 {len(df)}개 종목")
    print("\n[Top 10 시총]")
    print(df[['Code', 'Name', 'MarketCap', 'Close', 'Market']].head(10).to_string())
