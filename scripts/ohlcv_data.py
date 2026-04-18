"""
OHLCV (가격/거래량) 데이터 수집 모듈

FinanceDataReader를 사용하여 일봉 데이터를 수집합니다.
당일 파일 캐시 지원 — 같은 날 재실행 시 FDR 요청 없이 즉시 반환.

사용법:
    from scripts.ohlcv_data import get_ohlcv, get_ohlcv_batch
    df = get_ohlcv('005930', days=300)
"""

import json
import os
import pickle
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import FinanceDataReader as fdr

from config import CACHE_DIR

# FDR에 타임아웃 옵션이 없으므로 소켓 타임아웃 설정
socket.setdefaulttimeout(30)

# 메모리 캐시
_DATA_CACHE: Dict[str, pd.DataFrame] = {}

# 영구 파일 캐시 (증분 업데이트)
_OHLCV_CACHE_DIR = CACHE_DIR / 'ohlcv'
_OHLCV_CACHE_DIR.mkdir(exist_ok=True)
_CACHE_FILE = _OHLCV_CACHE_DIR / 'ohlcv_cache.pkl'


def _load_file_cache() -> Dict[str, pd.DataFrame]:
    """영구 캐시 로드"""
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except Exception:
            pass
    return {}


def _save_file_cache(cache: Dict[str, pd.DataFrame]):
    """영구 캐시 저장"""
    try:
        with open(_CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception:
        pass


def _needs_update(df: pd.DataFrame) -> bool:
    """캐시된 데이터가 가장 최근 거래일을 포함하는지 확인"""
    if df is None or len(df) == 0:
        return True
    last_date = df.index[-1].date()
    today = datetime.now().date()
    weekday = today.weekday()

    # 예상되는 최신 거래일 계산 (토=5, 일=6)
    if weekday == 5:      # 토
        expected = today - timedelta(days=1)  # 금
    elif weekday == 6:    # 일
        expected = today - timedelta(days=2)  # 금
    elif weekday == 0 and datetime.now().hour < 9:  # 월요일 장 시작 전
        expected = today - timedelta(days=3)  # 금
    elif datetime.now().hour < 9:  # 평일 장 시작 전
        expected = today - timedelta(days=1)
    else:
        expected = today

    # 캐시가 예상 거래일보다 오래됐으면 업데이트 필요
    return last_date < expected


# 시작 시 파일 캐시를 메모리에 로드
_file_cache = _load_file_cache()
if _file_cache:
    _DATA_CACHE.update(_file_cache)

# 저장 카운터
_save_counter = 0


def get_ohlcv(ticker: str, days: int = 300, use_cache: bool = True) -> Optional[pd.DataFrame]:
    """
    종목의 OHLCV 데이터 수집 (FinanceDataReader)

    Args:
        ticker: 종목코드 (6자리)
        days: 조회 일수
        use_cache: 캐시 사용 여부

    Returns:
        DataFrame: Open, High, Low, Close, Volume, Change
    """
    global _save_counter

    cache_key = f"{ticker}_{days}"

    # 1. 캐시에 있고 업데이트 불필요하면 바로 반환
    if use_cache and cache_key in _DATA_CACHE:
        cached = _DATA_CACHE[cache_key]
        if not _needs_update(cached):
            return cached

    try:
        # 2. 캐시에 있지만 오늘 데이터 필요 → 최근 5일만 가져와서 병합 (증분)
        if cache_key in _DATA_CACHE and _DATA_CACHE[cache_key] is not None and len(_DATA_CACHE[cache_key]) > 0:
            old_df = _DATA_CACHE[cache_key]
            last_date = old_df.index[-1].strftime('%Y-%m-%d')
            new_df = fdr.DataReader(ticker, last_date)

            if new_df is not None and len(new_df) > 0:
                col_map = {'시가': 'Open', '고가': 'High', '저가': 'Low',
                           '종가': 'Close', '거래량': 'Volume', '등락률': 'Change'}
                new_df = new_df.rename(columns=col_map)
                # 기존 + 신규 병합 (중복 제거)
                df = pd.concat([old_df, new_df])
                df = df[~df.index.duplicated(keep='last')]
                df = df.sort_index().tail(days)
            else:
                df = old_df
        else:
            # 3. 캐시 없음 → 전체 수집
            end = datetime.now()
            start = end - timedelta(days=int(days * 1.5))
            df = fdr.DataReader(ticker, start.strftime('%Y-%m-%d'))

            if df is None or len(df) == 0:
                return None

            col_map = {'시가': 'Open', '고가': 'High', '저가': 'Low',
                       '종가': 'Close', '거래량': 'Volume', '등락률': 'Change'}
            df = df.rename(columns=col_map)
            df = df.tail(days)

        if use_cache:
            _DATA_CACHE[cache_key] = df
            _save_counter += 1
            if _save_counter % 100 == 0:
                _save_file_cache(_DATA_CACHE)

        return df

    except Exception as e:
        # 에러 시 기존 캐시라도 반환
        if cache_key in _DATA_CACHE:
            return _DATA_CACHE[cache_key]
        print(f"  OHLCV 수집 실패 ({ticker}): {e}")
        return None


def get_ohlcv_korean(ticker: str, days: int = 300) -> Optional[pd.DataFrame]:
    """
    한글 컬럼명으로 OHLCV 반환 (기술적 지표 모듈과 호환)

    Returns:
        DataFrame: 시가, 고가, 저가, 종가, 거래량
    """
    df = get_ohlcv(ticker, days, use_cache=True)
    if df is None:
        return None

    df = df.copy()
    col_map = {
        'Open': '시가', 'High': '고가', 'Low': '저가',
        'Close': '종가', 'Volume': '거래량', 'Change': '등락률'
    }
    df = df.rename(columns=col_map)
    return df


def get_ohlcv_batch(tickers: List[tuple], days: int = 200) -> Dict[str, list]:
    """
    여러 종목의 OHLCV를 차트 데이터 형식으로 수집

    Args:
        tickers: [(종목코드, 종목명), ...] 리스트
        days: 조회 일수

    Returns:
        {종목코드: [{date, open, high, low, close, volume}, ...]}
    """
    chart_data = {}

    for ticker, name in tickers:
        df = get_ohlcv(ticker, days)
        if df is None:
            continue

        records = []
        for idx, row in df.iterrows():
            records.append({
                'date': idx.strftime('%Y-%m-%d'),
                'open': int(row['Open']),
                'high': int(row['High']),
                'low': int(row['Low']),
                'close': int(row['Close']),
                'volume': int(row['Volume']),
            })

        chart_data[ticker] = records
        print(f"  {name}: {len(records)}일 데이터")

    return chart_data


def save_chart_data(chart_data: Dict[str, list], filepath: str) -> None:
    """차트 데이터를 JSON으로 저장"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(chart_data, f, ensure_ascii=False)
    print(f"차트 데이터 저장: {filepath} ({len(chart_data)}개 종목)")


def flush_cache():
    """메모리 캐시를 파일에 저장"""
    if _DATA_CACHE:
        _save_file_cache(_DATA_CACHE)


def clear_cache():
    """메모리 캐시 초기화"""
    _DATA_CACHE.clear()


if __name__ == '__main__':
    print("=" * 60)
    print("OHLCV 데이터 테스트: 삼성전자 (005930)")
    print("=" * 60)

    df = get_ohlcv('005930', days=60)
    if df is not None:
        print(f"\n데이터 기간: {df.index[0]} ~ {df.index[-1]}")
        print(f"데이터 수: {len(df)}일")
        print(df.tail(5))
    else:
        print("데이터 수집 실패")
