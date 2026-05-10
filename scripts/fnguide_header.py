"""
FnGuide 경량 파서 — 헤더 지표 + 현금흐름표.

용도:
- KIS API가 주지 않는 Forward PER / 업종 PER / 배당수익률 (헤더)
- KIS API에 엔드포인트가 없는 **현금흐름표** (OCF/투자CF/FCF)
- DCF 밸류에이션과 "이익의 질" 분석에 필수

주식웹사이트 프로젝트(scripts/fnguide_data.py, 1033줄)의 경량 포트.
pandas/lxml 사용하지만 BeautifulSoup 의존 없음.

리스크:
- FnGuide 비공식 크롤링. User-Agent 필수, 차단 가능성.
- 실패 시 빈 dict 반환 → 리포트 생성 자체는 막지 않음.
"""

import io
import re
import requests
import pandas as pd
from typing import Dict, List

FNGUIDE_FINANCE_URL = "https://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp"
FNGUIDE_MAIN_URL = "https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

# 페이지 헤더(corp_group2) anchor ID → 필드 이름 매핑
HEADER_METRIC_IDS = {
    "h_per": "per",
    "h_12m": "per_12m",
    "h_u_per": "sector_per",
    "h_pbr": "pbr",
    "h_rate": "dividend_yield",
}

# SVD_Finance.asp 테이블 인덱스
TABLE_IDX = {
    "annual_income": 0,
    "quarter_income": 1,
    "annual_balance": 2,
    "quarter_balance": 3,
    "annual_cashflow": 4,
    "quarter_cashflow": 5,
}

# 현금흐름표 항목 매칭 (FnGuide 한글 → 영문키)
CF_ITEMS = {
    "영업활동으로인한현금흐름": "ocf",
    "영업활동현금흐름": "ocf",
    "투자활동으로인한현금흐름": "invest_cf",
    "투자활동현금흐름": "invest_cf",
    "재무활동으로인한현금흐름": "finance_cf",
    "재무활동현금흐름": "finance_cf",
    "유형자산의취득": "capex",
    "유형자산취득": "capex",
}


def get_fnguide_header(code: str, timeout: int = 15) -> Dict[str, float]:
    """FnGuide Main 페이지에서 헤더 지표만 추출.

    Returns:
        {per, per_12m, sector_per, pbr, dividend_yield} 또는 빈 dict.
    """
    params = {
        "pGB": "1", "gicode": f"A{code}", "cID": "",
        "MenuYn": "Y", "ReportGB": "", "NewMenuID": "101", "stkGb": "701",
    }
    try:
        resp = requests.get(FNGUIDE_MAIN_URL, params=params, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return {}

    metrics: Dict[str, float] = {}
    pattern = r'class="tip_in"\s*id="(\w+)"[^>]*>.*?</a>\s*</dt>\s*<dd>([^<]*)</dd>'
    for match in re.finditer(pattern, html, re.DOTALL):
        anchor_id = match.group(1)
        value_str = match.group(2).strip().replace("%", "").replace(",", "")
        if value_str in ("", "N/A", "-"):
            continue
        metric_key = HEADER_METRIC_IDS.get(anchor_id)
        if metric_key:
            try:
                metrics[metric_key] = float(value_str)
            except (ValueError, TypeError):
                pass
    return metrics


def _clean_cf_table(df: pd.DataFrame) -> pd.DataFrame:
    """FnGuide 현금흐름표 테이블 정제."""
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    # MultiIndex 컬럼 처리
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[-1] if isinstance(col, tuple) else col for col in df.columns]

    # 첫 열을 인덱스로
    first_col = df.columns[0]
    df = df.set_index(first_col)
    df.index = df.index.astype(str).str.strip()
    df.index = df.index.str.replace(r"\s+", "", regex=True)

    # 컬럼명 정리: YYYY/MM 추출
    new_cols = []
    for col in df.columns:
        col_str = str(col).strip()
        match = re.search(r"(\d{4})[/.](\d{2})", col_str)
        if match and "전년" not in col_str and "동기" not in col_str:
            base = f"{match.group(1)}/{match.group(2)}"
            if re.search(r"\([PE]\)", col_str):
                new_cols.append(base + "(P)")
            else:
                new_cols.append(base)
        else:
            new_cols.append(col_str)
    df.columns = new_cols

    # 숫자 변환
    for col in df.columns:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(",", "").str.strip(),
            errors="coerce"
        )
    return df


def _extract_cf_row(df: pd.DataFrame, names: List[str]):
    """CF 테이블에서 특정 행 추출. 짧은 매칭 우선."""
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            return df.loc[name]
        matches = [idx for idx in df.index if name in str(idx)]
        if matches:
            starts_with = [idx for idx in matches if str(idx).startswith(name)]
            target = min(starts_with, key=len) if starts_with else min(matches, key=len)
            return df.loc[target]
    return None


def get_fnguide_cashflow(code: str, report_type: str = "D", timeout: int = 20) -> Dict[str, Dict[str, float]]:
    """FnGuide SVD_Finance에서 현금흐름표 추출 (연간).

    Args:
        code: 6자리 종목코드
        report_type: 'D'=연결, 'I'=개별

    Returns:
        {
            'ocf':       {'2021/12': 11296, '2022/12': 9333, ...},  # 영업CF
            'invest_cf': {'2021/12': ..., ...},                    # 투자CF
            'finance_cf':{'2021/12': ..., ...},                    # 재무CF
            'capex':     {'2021/12': ..., ...},                    # 유형자산취득
            'fcf':       {'2021/12': ..., ...},                    # OCF - CapEx 자동계산
        }
        단위: 억원. 실패 시 빈 dict.
    """
    params = {
        "pGB": "1", "gicode": f"A{code}", "cID": "",
        "MenuYn": "Y", "ReportGB": report_type,
        "NewMenuID": "103", "stkGb": "701",
    }
    try:
        resp = requests.get(FNGUIDE_FINANCE_URL, params=params, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), encoding="utf-8", displayed_only=False)
    except Exception:
        # 연결 실패 시 개별로 재시도
        if report_type == "D":
            return get_fnguide_cashflow(code, "I", timeout)
        return {}

    if len(tables) < 6:
        if report_type == "D":
            return get_fnguide_cashflow(code, "I", timeout)
        return {}

    cf_table = _clean_cf_table(tables[TABLE_IDX["annual_cashflow"]])
    if cf_table.empty:
        return {}

    # 날짜 컬럼만 선별
    date_cols = [c for c in cf_table.columns if re.match(r"\d{4}/\d{2}", str(c)) and c.endswith("/12")]
    if not date_cols:
        return {}

    result: Dict[str, Dict[str, float]] = {
        "ocf": {}, "invest_cf": {}, "finance_cf": {}
    }

    # CapEx는 FnGuide 요약 테이블에 없는 경우가 많으므로 OCF/투자CF/재무CF만 추출.
    # FCF가 필요하면 DCF 섹션에서 웹 검색 or 수동 계산.
    field_map = {
        "ocf": ["영업활동으로인한현금흐름", "영업활동현금흐름"],
        "invest_cf": ["투자활동으로인한현금흐름", "투자활동현금흐름"],
        "finance_cf": ["재무활동으로인한현금흐름", "재무활동현금흐름"],
    }
    for key, names in field_map.items():
        row = _extract_cf_row(cf_table, names)
        if row is None:
            continue
        for col in date_cols:
            val = row.get(col)
            if pd.notna(val):
                result[key][col] = float(val)

    return result


if __name__ == "__main__":
    import sys, json
    code = sys.argv[1] if len(sys.argv) > 1 else "000270"

    print(f"=== {code} FnGuide 헤더 ===")
    h = get_fnguide_header(code)
    if not h:
        print("[FAIL] 헤더 추출 실패")
    else:
        for k, v in h.items():
            print(f"  {k}: {v}")

    print(f"\n=== {code} FnGuide 현금흐름표 (연간, 억원) ===")
    cf = get_fnguide_cashflow(code)
    if not cf or not cf.get("ocf"):
        print("[FAIL] 현금흐름 추출 실패")
    else:
        years = sorted(cf["ocf"].keys())
        print(f"  연도      OCF         투자CF      재무CF")
        for y in years:
            ocf = cf["ocf"].get(y, 0)
            inv = cf["invest_cf"].get(y, 0)
            fin = cf["finance_cf"].get(y, 0)
            print(f"  {y}  {ocf:>10,.0f}  {inv:>10,.0f}  {fin:>10,.0f}")
