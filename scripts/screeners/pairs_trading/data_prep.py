"""
가격 데이터 준비

유니버스 전체 OHLCV 배치 수집, 종가 매트릭스, 로그수익률 계산.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from scripts.ohlcv_data import get_ohlcv
from scripts.screeners.pairs_trading.config import LOOKBACK_DAYS, MAX_MISSING_DAYS


def _fetch_single(ticker: str, days: int) -> tuple:
    """단일 종목 OHLCV 수집 (스레드용)"""
    df = get_ohlcv(ticker, days=days, use_cache=True)
    if df is not None and 'Close' in df.columns and len(df) > 0:
        return ticker, df['Close']
    return ticker, None


def build_price_matrix(universe: pd.DataFrame,
                       days: int = LOOKBACK_DAYS,
                       max_workers: int = 10) -> pd.DataFrame:
    """
    유니버스 전체 종목의 종가 매트릭스 생성.

    Returns:
        DataFrame: index=날짜, columns=종목코드, values=종가
    """
    print("\n[2/7] 가격 데이터 수집")
    print("=" * 50)

    tickers = universe['Code'].tolist()
    print(f"  {len(tickers)}개 종목 OHLCV 수집 중...")

    price_dict = {}
    failed = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_single, t, days): t
            for t in tickers
        }
        for i, future in enumerate(as_completed(futures), 1):
            ticker = futures[future]
            try:
                _, close_series = future.result()
                if close_series is not None:
                    price_dict[ticker] = close_series
                else:
                    failed.append(ticker)
            except Exception:
                failed.append(ticker)

            if i % 50 == 0:
                print(f"  진행: {i}/{len(tickers)}")

    print(f"  수집 완료: {len(price_dict)}개 성공, {len(failed)}개 실패")

    if not price_dict:
        raise RuntimeError("가격 데이터 수집 실패: 유효한 종목 없음")

    price_matrix = pd.DataFrame(price_dict)
    price_matrix = price_matrix.sort_index()
    price_matrix = price_matrix.ffill(limit=MAX_MISSING_DAYS)

    still_missing = price_matrix.isnull().sum()
    drop_cols = still_missing[still_missing > MAX_MISSING_DAYS].index.tolist()
    if drop_cols:
        price_matrix = price_matrix.drop(columns=drop_cols)
        print(f"  결측 과다 종목 제거: {len(drop_cols)}개")

    price_matrix = price_matrix.dropna()

    print(f"  가격 매트릭스: {price_matrix.shape[0]}일 × {price_matrix.shape[1]}종목")
    return price_matrix


def calc_log_returns(price_matrix: pd.DataFrame) -> pd.DataFrame:
    """로그수익률 매트릭스 계산"""
    return np.log(price_matrix / price_matrix.shift(1)).dropna()
