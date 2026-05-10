"""KRX 공식 종목 마스터 CSV 로더 — 종목코드 100% 정확 매핑.

배경 (Phase G-9):
- 네이버 금융 / FDR fallback 사용 시 종목코드 ↔ 종목명 매핑 버그 발견 (8건)
- 예: 469830 = ETF (실제 GS피앤엘 X), 095570 = AJ네트웍스 (수산세보틱스 X)
- 해결: KRX 공식 종목 마스터 CSV 사용 (data/holly_kr/krx_master.csv)

CSV 출처: KRX 정보데이터시스템 종목 다운로드 (사용자 직접 다운로드)
컬럼: 표준코드, 단축코드, 한글 종목명, 한글 종목약명, 영문 종목명,
      상장일, 시장구분, 증권구분, 소속부, 주식종류, 액면가, 상장주식수

필터:
- 주식종류 = 보통주 (우선주/종류주 제외)
- 증권구분 = 주권 (REIT/외국주권/SPAC/투자회사 제외)
- 시장구분 = KOSPI / KOSDAQ / KOSDAQ GLOBAL (KONEX 제외)

→ ETF/ETN은 자동 제외 (CSV에 없음)
→ 보통주 약 2,606개 (2026-05-10 기준)
"""
import os
from pathlib import Path
from typing import Optional, Dict

import pandas as pd

# 프로젝트 루트 기준 (이 파일이 scripts/krx_master_csv.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / 'data' / 'holly_kr' / 'krx_master.csv'

# 캐시 (메모리)
_master_cache: Optional[pd.DataFrame] = None
_code_to_name: Optional[Dict[str, str]] = None


def load_krx_master(use_cache: bool = True) -> Optional[pd.DataFrame]:
    """KRX 공식 종목 마스터 로드 (보통주 + KOSPI/KOSDAQ만).

    Returns:
        DataFrame: ['Code', 'Name', 'Market', 'Shares']
        실패 시 None
    """
    global _master_cache
    if use_cache and _master_cache is not None:
        return _master_cache

    if not CSV_PATH.exists():
        return None

    try:
        df = pd.read_csv(CSV_PATH, encoding='cp949', dtype={'단축코드': str})
    except Exception as e:
        print(f"  [KRX CSV 로드 실패] {e}")
        return None

    # 보통주만 (우선주/종류주 제외)
    df = df[(df['주식종류'] == '보통주') & (df['증권구분'] == '주권')]
    # KOSPI/KOSDAQ만 (KONEX 제외)
    df = df[df['시장구분'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])]

    # 표준 컬럼
    result = pd.DataFrame({
        'Code': df['단축코드'].astype(str).str.zfill(6),
        'Name': df['한글 종목약명'].fillna(df['한글 종목명']),
        'Market': df['시장구분'].replace('KOSDAQ GLOBAL', 'KOSDAQ'),
        'Shares': pd.to_numeric(df['상장주식수'], errors='coerce').fillna(0).astype('int64'),
    }).reset_index(drop=True)

    _master_cache = result
    return result


def get_code_to_name() -> Dict[str, str]:
    """종목코드 → 종목명 dict (빠른 매핑용)."""
    global _code_to_name
    if _code_to_name is not None:
        return _code_to_name

    master = load_krx_master()
    if master is None:
        return {}

    _code_to_name = dict(zip(master['Code'], master['Name']))
    return _code_to_name


def verify_code_name(code: str, expected_name: str) -> bool:
    """종목코드 ↔ 종목명 일치 검증.

    Returns:
        True: 일치
        False: 불일치 (잘못된 매핑)
    """
    code_to_name = get_code_to_name()
    actual_name = code_to_name.get(str(code).zfill(6))
    if actual_name is None:
        return False  # CSV에 없음 (ETF/ETN/우선주 등)
    # 부분 일치 (공백/대소문자 무시)
    return expected_name.strip() in actual_name or actual_name in expected_name.strip()


def is_valid_stock_code(code: str) -> bool:
    """종목코드가 KRX 공식 보통주 마스터에 존재하는지."""
    return str(code).zfill(6) in get_code_to_name()


def filter_to_krx_master(df: pd.DataFrame, code_col: str = 'Code') -> pd.DataFrame:
    """DataFrame을 KRX 공식 보통주만 필터링.

    Args:
        df: 종목 DataFrame
        code_col: 종목코드 컬럼명

    Returns:
        KRX 보통주만 남은 DataFrame
    """
    valid_codes = set(get_code_to_name().keys())
    return df[df[code_col].astype(str).str.zfill(6).isin(valid_codes)].copy()


if __name__ == '__main__':
    # 단독 테스트
    master = load_krx_master()
    if master is None:
        print("KRX CSV 로드 실패 — data/holly_kr/krx_master.csv 확인")
    else:
        print(f"[KRX 종목 마스터] {len(master)}개 보통주")
        print(master.head(10).to_string())
        print()
        print("[시장 분포]")
        print(master['Market'].value_counts())
        print()
        print("[종목코드 검증]")
        test = {
            '005930': '삼성전자',
            '000660': 'SK하이닉스',
            '469830': 'GS피앤엘 (ETF 의심)',
            '474220': '우진 (ETF 의심)',
            '317830': '샌즈랩 (실제는 에스피시스템스)',
        }
        for code, label in test.items():
            valid = is_valid_stock_code(code)
            actual = get_code_to_name().get(code, '없음')
            status = '✓' if valid else '✗'
            print(f"  {status} {code}: 입력={label} / KRX={actual}")
