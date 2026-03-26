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

# 메모리 캐시 (세션 내)
_DATA_CACHE: Dict[str, pd.DataFrame] = {}

# 파일 캐시 (당일 유효)
_OHLCV_CACHE_DIR = CACHE_DIR / 'ohlcv'
_OHLCV_CACHE_DIR.mkdir(exist_ok=True)


def _get_cache_file() -> Path:
    """당일 OHLCV 캐시 파일 경로"""
    today = datetime.now().strftime('%Y-%m-%d')
    return _OHLCV_CACHE_DIR / f'ohlcv_{today}.pkl'


def _load_file_cache() -> Dict[str, pd.DataFrame]:
    """당일 파일 캐시 로드"""
    cache_file = _get_cache_file()
    if cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            pass
    return {}


def _save_file_cache(cache: Dict[str, pd.DataFrame]):
    """파일 캐시 저장"""
    cache_file = _get_cache_file()
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(cache, f)
    except Exception:
        pass


def _cleanup_old_cache():
    """어제 이전 OHLCV 캐시 삭제"""
    today = datetime.now().strftime('%Y-%m-%d')
    for f in _OHLCV_CACHE_DIR.glob('ohlcv_*.pkl'):
        if today not in f.name:
            try:
                f.unlink()
            except Exception:
                pass


# 시작 시 파일 캐시를 메모리에 로드
_file_cache = _load_file_cache()
if _file_cache:
    _DATA_CACHE.update(_file_cache)

# 저장 카운터 (매 100개마다 파일에 flush)
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
    if use_cache and cache_key in _DATA_CACHE:
        return _DATA_CACHE[cache_key]

    try:
        end = datetime.now()
        start = end - timedelta(days=int(days * 1.5))  # 여유 있게 조회
        df = fdr.DataReader(ticker, start.strftime('%Y-%m-%d'))

        if df is None or len(df) == 0:
            return None

        # 컬럼명 통일 (FDR은 영문, pykrx는 한글)
        col_map = {
            '시가': 'Open', '고가': 'High', '저가': 'Low',
            '종가': 'Close', '거래량': 'Volume', '등락률': 'Change'
        }
        df = df.rename(columns=col_map)

        # 최근 days일만
        df = df.tail(days)

        if use_cache:
            _DATA_CACHE[cache_key] = df
            _save_counter += 1
            # 100개마다 파일에 flush
            if _save_counter % 100 == 0:
                _save_file_cache(_DATA_CACHE)

        return df

    except Exception as e:
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
        _cleanup_old_cache()


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
