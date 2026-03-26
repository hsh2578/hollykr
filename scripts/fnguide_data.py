"""
FnGuide 재무제표 수집 모듈 (pd.read_html 기반)

comp.fnguide.com에서 재무제표를 수집합니다.

수집 데이터:
- 연간/분기 손익계산서: 매출액, 매출총이익, 영업이익(EBIT), 당기순이익
- 연간/분기 재무상태표: 총자산, 자본총계, 지배주주지분, 유동자산, 유동부채 등
- 연간/분기 현금흐름표: 영업활동현금흐름, 투자활동현금흐름
- 페이지 헤더: PER, 12M PER, 업종 PER, PBR, 배당수익률

사용법:
    from scripts.fnguide_data import get_financial_data
    data = get_financial_data('005930')
"""

import io
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd
import requests

# ============================================================================
# 상수
# ============================================================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
}

FNGUIDE_FINANCE_URL = 'https://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp'
FNGUIDE_MAIN_URL = 'https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp'

# 재무제표 테이블 인덱스 (SVD_Finance.asp)
TABLE_IDX = {
    'annual_income': 0,
    'quarter_income': 1,
    'annual_balance': 2,
    'quarter_balance': 3,
    'annual_cashflow': 4,
    'quarter_cashflow': 5,
}

# 손익계산서 항목 매핑
INCOME_ITEMS = {
    '매출액': 'revenue',
    '매출총이익': 'gross_profit',
    '영업이익': 'operating_income',
    '당기순이익': 'net_income',
    '지배주주순이익': 'net_income_controlling',
    '법인세비용': 'tax_expense',
    '금융원가': 'finance_cost',
}

# 재무상태표 항목 매핑
BALANCE_SEARCH = {
    'total_assets': ['자산총계', '자산'],
    'total_equity': ['자본총계', '자본'],
    'controlling_equity': ['지배기업주주지분', '지배주주지분'],
    'current_assets': ['유동자산'],
    'current_liabilities': ['유동부채'],
    'non_current_assets': ['비유동자산'],
    'non_current_liabilities': ['비유동부채'],
    'cash': ['현금및현금성자산', '현금'],
    'short_term_debt': ['단기차입금'],
    'long_term_debt': ['장기차입금'],
    'bonds': ['사채'],
    'inventory': ['재고자산'],
}

# SVD_Main.asp 연간 항목 매핑
MAIN_ANNUAL_ITEMS = {
    '매출액': 'revenue',
    '영업이익': 'operating_income',
    '당기순이익': 'net_income',
    '지배주주순이익': 'net_income_controlling',
    'EPS': 'eps',
}

# 현금흐름표 항목 매핑
CASHFLOW_ITEMS = {
    '영업활동으로인한현금흐름': 'cfo',
    '영업활동현금흐름': 'cfo',
}
CASHFLOW_INVEST_ITEMS = ['투자활동으로인한현금흐름', '투자활동현금흐름']

# 페이지 헤더 지표 ID 매핑
HEADER_METRIC_IDS = {
    'h_per': 'per',
    'h_12m': 'per_12m',
    'h_u_per': 'sector_per',
    'h_pbr': 'pbr',
    'h_rate': 'dividend_yield',
}


# ============================================================================
# 데이터 수집 함수
# ============================================================================

def _fetch_tables(code: str, report_type: str = 'D') -> Optional[tuple]:
    """FnGuide 재무제표 페이지에서 테이블들과 HTML 추출"""
    params = {
        'pGB': '1', 'gicode': f'A{code}', 'cID': '',
        'MenuYn': 'Y', 'ReportGB': report_type,
        'NewMenuID': '103', 'stkGb': '701',
    }
    try:
        resp = requests.get(FNGUIDE_FINANCE_URL, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        html_text = resp.text
        tables = pd.read_html(io.StringIO(html_text), encoding='utf-8', displayed_only=False)

        if len(tables) < 6:
            if report_type == 'D':
                return _fetch_tables(code, 'I')
            return None
        return tables, html_text
    except Exception:
        if report_type == 'D':
            return _fetch_tables(code, 'I')
        return None


def _fetch_tables_main(code: str) -> Optional[pd.DataFrame]:
    """SVD_Main.asp에서 연간 Financial Highlight 테이블 추출"""
    params = {
        'pGB': '1', 'gicode': f'A{code}', 'cID': '',
        'MenuYn': 'Y', 'ReportGB': '', 'NewMenuID': '101', 'stkGb': '701',
    }
    try:
        resp = requests.get(FNGUIDE_MAIN_URL, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), encoding='utf-8', displayed_only=False)
        if len(tables) >= 12:
            return tables[11]
    except Exception:
        pass
    return None


def _parse_main_annual(table: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """SVD_Main.asp table[11] 파싱"""
    result = {}
    cols = []
    for c in table.columns:
        cols.append(c[1] if isinstance(c, tuple) else str(c))
    table = table.copy()
    table.columns = cols

    item_col = table.columns[0]
    table = table.set_index(item_col)
    table.index = table.index.astype(str).str.strip()

    date_cols = [c for c in table.columns if re.match(r'\d{4}/\d{2}', str(c))]

    for kr_name, en_key in MAIN_ANNUAL_ITEMS.items():
        matched = None
        for idx in table.index:
            if kr_name == idx or kr_name in idx:
                matched = idx
                break
        if matched is None:
            continue
        row = table.loc[matched, date_cols]
        row = pd.to_numeric(row, errors='coerce').dropna()
        if not row.empty:
            result[en_key] = row.to_dict()

    return result


def _parse_header_metrics(html: str) -> Dict[str, float]:
    """FnGuide 페이지 헤더에서 PER, PBR, 배당수익률 추출"""
    metrics = {}
    pattern = r'class="tip_in"\s*id="(\w+)"[^>]*>.*?</a>\s*</dt>\s*<dd>([^<]*)</dd>'
    for match in re.finditer(pattern, html, re.DOTALL):
        anchor_id = match.group(1)
        value_str = match.group(2).strip().replace('%', '').replace(',', '')
        metric_key = HEADER_METRIC_IDS.get(anchor_id)
        if metric_key:
            try:
                metrics[metric_key] = float(value_str)
            except (ValueError, TypeError):
                pass
    return metrics


def _clean_table(df: pd.DataFrame) -> pd.DataFrame:
    """테이블 정제: 불필요한 열/행 제거, 인덱스 정리"""
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[-1] if isinstance(col, tuple) else col for col in df.columns]

    first_col = df.columns[0]
    df = df.set_index(first_col)
    df.index = df.index.astype(str).str.strip().str.replace(r'\s+', '', regex=True)

    cols_to_drop = [c for c in df.columns if '전년' in str(c) or '동기' in str(c)]
    df = df.drop(columns=cols_to_drop, errors='ignore')

    new_cols = []
    for col in df.columns:
        col_str = str(col).strip()
        match = re.search(r'(\d{4})[/.](\d{2})', col_str)
        if match:
            base = f"{match.group(1)}/{match.group(2)}"
            if re.search(r'\([PE]\)', col_str):
                new_cols.append(base + '(P)')
            else:
                new_cols.append(base)
        else:
            new_cols.append(col_str)
    df.columns = new_cols

    for col in df.columns:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(',', '').str.strip(),
            errors='coerce'
        )

    return df


def _extract_item(df: pd.DataFrame, item_names: list) -> pd.Series:
    """DataFrame에서 항목 추출 (여러 이름 시도, 부분 일치)"""
    if df is None or df.empty:
        return pd.Series(dtype=float)

    for name in item_names:
        if name in df.index:
            return df.loc[name]

        matches = [idx for idx in df.index if name in str(idx)]
        if matches:
            starts_with = [idx for idx in matches if str(idx).startswith(name)]
            if starts_with:
                return df.loc[min(starts_with, key=len)]
            return df.loc[min(matches, key=len)]

    return pd.Series(dtype=float)


# ============================================================================
# 메인 수집 함수
# ============================================================================

def get_financial_data(code: str, retry: int = 2) -> Optional[Dict[str, Any]]:
    """
    FnGuide에서 종목의 재무데이터 수집

    Returns:
        {
            'code', 'annual', 'quarter', 'balance', 'balance_avg',
            'cashflow', 'header',
            '{key}_ttm', 'cfo_ttm', 'invest_cf_ttm'
        }
    """
    for attempt in range(retry):
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_finance = executor.submit(_fetch_tables, code)
                future_main = executor.submit(_fetch_tables_main, code)
                fetch_result = future_finance.result(timeout=30)
                main_tables = future_main.result(timeout=30)

            if not fetch_result:
                if attempt < retry - 1:
                    time.sleep(0.5)
                continue

            tables, html_text = fetch_result
            if len(tables) < 6:
                if attempt < retry - 1:
                    time.sleep(0.5)
                continue

            result = {
                'code': code,
                'annual': {},
                'quarter': {},
                'balance': {},
                'cashflow': {},
            }

            # 헤더 지표 (PER, PBR, 배당수익률)
            result['header'] = _parse_header_metrics(html_text)

            # 손익계산서
            annual_income = _clean_table(tables[TABLE_IDX['annual_income']])
            quarter_income = _clean_table(tables[TABLE_IDX['quarter_income']])

            # 미완성 연간 컬럼 제거
            if not annual_income.empty:
                date_annual_cols = sorted(
                    [c for c in annual_income.columns if re.match(r'\d{4}/\d{2}', str(c))],
                    reverse=True,
                )
                if date_annual_cols and not date_annual_cols[0].endswith('/12'):
                    annual_income = annual_income.drop(columns=[date_annual_cols[0]], errors='ignore')

            if not annual_income.empty:
                for kr_name, en_key in INCOME_ITEMS.items():
                    series = _extract_item(annual_income, [kr_name])
                    if not series.empty:
                        result['annual'][en_key] = series.dropna().to_dict()

            if not quarter_income.empty:
                for kr_name, en_key in INCOME_ITEMS.items():
                    series = _extract_item(quarter_income, [kr_name])
                    if not series.empty:
                        result['quarter'][en_key] = series.dropna().to_dict()

            # 재무상태표 (분기 우선)
            quarter_balance = _clean_table(tables[TABLE_IDX['quarter_balance']])
            annual_balance = _clean_table(tables[TABLE_IDX['annual_balance']])

            bs_source = quarter_balance if not quarter_balance.empty else annual_balance
            if not bs_source.empty:
                for en_key, kr_names in BALANCE_SEARCH.items():
                    series = _extract_item(bs_source, kr_names)
                    if not series.empty:
                        valid = series.dropna()
                        if len(valid) > 0:
                            result['balance'][en_key] = float(valid.iloc[0])

                short_debt = result['balance'].get('short_term_debt', 0) or 0
                long_debt = result['balance'].get('long_term_debt', 0) or 0
                bonds = result['balance'].get('bonds', 0) or 0
                result['balance']['total_debt'] = short_debt + long_debt + bonds

            # 재무상태표 4분기 평균 (ROE, GPA 등 Flow/Stock 혼합 비율용)
            result['balance_avg'] = {}
            bs_q = quarter_balance if not quarter_balance.empty else annual_balance
            if not bs_q.empty:
                for en_key, kr_names in BALANCE_SEARCH.items():
                    series = _extract_item(bs_q, kr_names)
                    if not series.empty:
                        valid = series.dropna()
                        if len(valid) > 0:
                            result['balance_avg'][en_key] = float(valid.head(4).mean())

            # 현금흐름표
            annual_cf = _clean_table(tables[TABLE_IDX['annual_cashflow']])
            quarter_cf = _clean_table(tables[TABLE_IDX['quarter_cashflow']])

            if not annual_cf.empty:
                cfo_series = _extract_item(annual_cf, list(CASHFLOW_ITEMS.keys()))
                if not cfo_series.empty:
                    result['cashflow']['cfo_annual'] = cfo_series.dropna().to_dict()

            if not quarter_cf.empty:
                cfo_q_series = _extract_item(quarter_cf, list(CASHFLOW_ITEMS.keys()))
                if not cfo_q_series.empty:
                    result['cashflow']['cfo_quarter'] = cfo_q_series.dropna().to_dict()

            if not annual_cf.empty:
                invest_series = _extract_item(annual_cf, CASHFLOW_INVEST_ITEMS)
                if not invest_series.empty:
                    result['cashflow']['invest_cf_annual'] = invest_series.dropna().to_dict()

            if not quarter_cf.empty:
                invest_q_series = _extract_item(quarter_cf, CASHFLOW_INVEST_ITEMS)
                if not invest_q_series.empty:
                    result['cashflow']['invest_cf_quarter'] = invest_q_series.dropna().to_dict()

            # SVD_Main.asp 5년 데이터로 연간 보충
            if main_tables is not None:
                try:
                    main_annual = _parse_main_annual(main_tables)
                    existing_years = set()
                    for v in result.get('annual', {}).values():
                        existing_years.update(v.keys())
                    min_existing = min(existing_years) if existing_years else '9999/99'
                    for en_key, year_dict in main_annual.items():
                        if en_key not in result['annual']:
                            result['annual'][en_key] = {
                                p: v for p, v in year_dict.items() if p.endswith('/12')
                            }
                        else:
                            for period, value in year_dict.items():
                                if period < min_existing:
                                    result['annual'][en_key][period] = value
                except Exception:
                    pass

            # TTM 계산
            _calculate_ttm(result)

            return result

        except Exception:
            if attempt < retry - 1:
                time.sleep(0.5)
            continue

    return None


def _calculate_ttm(data: Dict[str, Any]) -> None:
    """TTM (Trailing Twelve Months) 계산"""
    for key in ['revenue', 'operating_income', 'net_income', 'gross_profit',
                'net_income_controlling', 'tax_expense', 'finance_cost']:
        annual = data['annual'].get(key, {})
        quarter = data['quarter'].get(key, {})
        ttm_value = None

        if len(quarter) >= 4:
            sorted_quarters = sorted(quarter.items(), key=lambda x: x[0], reverse=True)
            recent_4 = [v for _, v in sorted_quarters[:4] if v is not None and not np.isnan(v)]
            if len(recent_4) == 4:
                ttm_value = sum(recent_4)

        if ttm_value is None and annual:
            sorted_annual = sorted(annual.items(), key=lambda x: x[0], reverse=True)
            for _, v in sorted_annual:
                if v is not None and not np.isnan(v):
                    ttm_value = v
                    break

        if ttm_value is not None:
            data[f'{key}_ttm'] = ttm_value

    # CFO TTM
    for prefix, annual_key, quarter_key, ttm_key in [
        ('cfo', 'cfo_annual', 'cfo_quarter', 'cfo_ttm'),
        ('invest_cf', 'invest_cf_annual', 'invest_cf_quarter', 'invest_cf_ttm'),
    ]:
        cf_annual = data['cashflow'].get(annual_key, {})
        cf_quarter = data['cashflow'].get(quarter_key, {})
        ttm = None

        if len(cf_quarter) >= 4:
            sorted_q = sorted(cf_quarter.items(), key=lambda x: x[0], reverse=True)
            recent_4 = [v for _, v in sorted_q[:4] if v is not None and not np.isnan(v)]
            if len(recent_4) == 4:
                ttm = sum(recent_4)

        if ttm is None and cf_annual:
            sorted_a = sorted(cf_annual.items(), key=lambda x: x[0], reverse=True)
            for _, v in sorted_a:
                if v is not None and not np.isnan(v):
                    ttm = v
                    break

        if ttm is not None:
            data[ttm_key] = ttm


# ============================================================================
# 배치 수집
# ============================================================================

def get_financial_data_batch(codes: List[str], delay: float = 0.3) -> Dict[str, Dict]:
    """여러 종목의 재무데이터 순차 수집"""
    results = {}
    total = len(codes)
    print(f"FnGuide 재무데이터 수집 시작 ({total}개 종목)")

    for i, code in enumerate(codes):
        data = get_financial_data(code)
        if data:
            results[code] = data
        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"  진행: {i + 1}/{total} (수집: {len(results)}개)")
        if delay > 0:
            time.sleep(delay)

    print(f"수집 완료: {len(results)}/{total}개")
    return results


# ============================================================================
# 재무비율 헬퍼 함수
# ============================================================================

def get_ebit(data: Dict) -> Optional[float]:
    """EBIT = 영업이익(TTM)"""
    op = data.get('operating_income_ttm')
    if op is not None:
        return op
    ni = data.get('net_income_ttm')
    tax = data.get('tax_expense_ttm')
    fin_cost = data.get('finance_cost_ttm')
    if ni is not None and tax is not None and fin_cost is not None:
        return ni + tax + fin_cost
    return None


def get_invested_capital(data: Dict) -> Optional[float]:
    """투하자본 = 유동자산 - 유동부채 + 비유동자산 (4분기 평균)"""
    bs = data.get('balance_avg') or data.get('balance', {})
    ca, cl, nca = bs.get('current_assets'), bs.get('current_liabilities'), bs.get('non_current_assets')
    if ca is not None and cl is not None and nca is not None:
        return ca - cl + nca
    return None


def get_ev(market_cap: float, data: Dict) -> Optional[float]:
    """기업가치 = 시가총액 + 총부채 - 여유자금"""
    bs = data.get('balance', {})
    cl = bs.get('current_liabilities', 0) or 0
    ncl = bs.get('non_current_liabilities', 0) or 0
    total_liabilities = cl + ncl
    cash = bs.get('cash', 0) or 0
    ca = bs.get('current_assets', 0) or 0
    if cash > 0:
        excess_cash = cash - max(0, cl - ca + cash)
    else:
        excess_cash = 0
    ev = market_cap + total_liabilities - excess_cash
    return ev if ev > 0 else market_cap


def get_roe(data: Dict) -> Optional[float]:
    """ROE = 지배주주순이익(TTM) / 지배주주지분(4분기 평균)"""
    ni = data.get('net_income_controlling_ttm') or data.get('net_income_ttm')
    bs = data.get('balance_avg') or data.get('balance', {})
    eq = bs.get('controlling_equity') or bs.get('total_equity')
    if ni is not None and eq is not None and eq > 0:
        return (ni / eq) * 100
    return None


def get_roa(data: Dict) -> Optional[float]:
    """ROA = 순이익(TTM) / 총자산(4분기 평균) x 100"""
    ni = data.get('net_income_ttm')
    bs = data.get('balance_avg') or data.get('balance', {})
    ta = bs.get('total_assets')
    if ni is not None and ta is not None and ta > 0:
        return (ni / ta) * 100
    return None


def get_roic(data: Dict) -> Optional[float]:
    """ROIC = EBIT / 투하자본 x 100"""
    ebit = get_ebit(data)
    ic = get_invested_capital(data)
    if ebit is not None and ic is not None and ic > 0:
        return (ebit / ic) * 100
    return None


def get_gpa(data: Dict) -> Optional[float]:
    """GPA = 매출총이익(TTM) / 총자산(4분기 평균)"""
    gp = data.get('gross_profit_ttm')
    bs = data.get('balance_avg') or data.get('balance', {})
    ta = bs.get('total_assets')
    if gp is not None and ta is not None and ta > 0:
        return gp / ta
    return None


def get_cfo_ratio(data: Dict) -> Optional[float]:
    """CFO = 영업활동현금흐름(TTM) / 총자산(4분기 평균)"""
    cfo = data.get('cfo_ttm')
    bs = data.get('balance_avg') or data.get('balance', {})
    ta = bs.get('total_assets')
    if cfo is not None and ta is not None and ta > 0:
        return cfo / ta
    return None


def get_per_from_data(market_cap: float, data: Dict) -> Optional[float]:
    """PER: FnGuide 헤더값 우선, 없으면 시가총액/순이익TTM"""
    header_per = data.get('header', {}).get('per')
    if header_per is not None and header_per > 0:
        return round(header_per, 2)
    ni = data.get('net_income_controlling_ttm') or data.get('net_income_ttm')
    if ni is not None and ni > 0 and market_cap > 0:
        return round(market_cap / ni, 2)
    return None


def get_pbr_from_data(market_cap: float, data: Dict) -> Optional[float]:
    """PBR: FnGuide 헤더값 우선, 없으면 시가총액/자본총계"""
    header_pbr = data.get('header', {}).get('pbr')
    if header_pbr is not None and header_pbr > 0:
        return round(header_pbr, 2)
    bs = data.get('balance', {})
    eq = bs.get('controlling_equity') or bs.get('total_equity')
    if eq is not None and eq > 0 and market_cap > 0:
        return round(market_cap / eq, 2)
    return None


def get_psr(market_cap: float, data: Dict) -> Optional[float]:
    """PSR = 시가총액 / 매출액(TTM)"""
    rev = data.get('revenue_ttm')
    if rev is not None and rev > 0:
        return market_cap / rev
    return None


def get_pcr(market_cap: float, data: Dict) -> Optional[float]:
    """PCR = 시가총액 / 영업현금흐름(TTM)"""
    cfo = data.get('cfo_ttm')
    if cfo is not None and cfo > 0:
        return market_cap / cfo
    return None


def get_current_ratio(data: Dict) -> Optional[float]:
    """유동비율 = 유동자산 / 유동부채"""
    bs = data.get('balance', {})
    ca, cl = bs.get('current_assets'), bs.get('current_liabilities')
    if ca is not None and cl is not None and cl > 0:
        return ca / cl
    return None


def get_debt_ratio(data: Dict) -> Optional[float]:
    """부채비율 = (유동부채+비유동부채) / 자본총계 x 100"""
    bs = data.get('balance', {})
    cl = bs.get('current_liabilities', 0) or 0
    ncl = bs.get('non_current_liabilities', 0) or 0
    eq = bs.get('total_equity')
    if eq is not None and eq > 0:
        return ((cl + ncl) / eq) * 100
    return None


def get_net_current_assets(data: Dict) -> Optional[float]:
    """순유동자산 = 유동자산 - 유동부채"""
    bs = data.get('balance', {})
    ca, cl = bs.get('current_assets'), bs.get('current_liabilities')
    if ca is not None and cl is not None:
        return ca - cl
    return None


def get_fcf(data: Dict) -> Optional[float]:
    """FCF = CFO(TTM) + 투자활동CF(TTM)"""
    cfo = data.get('cfo_ttm')
    inv_cf = data.get('invest_cf_ttm')
    if cfo is not None and inv_cf is not None:
        return cfo + inv_cf
    return None


def get_peg(market_cap: float, data: Dict) -> Optional[float]:
    """PEG = PER / EPS성장률(3년평균)"""
    per = get_per_from_data(market_cap, data)
    if per is None or per <= 0:
        return None
    growth_rates = get_annual_growth_rates(data, 'eps', years=3)
    if not growth_rates:
        growth_rates = get_growth_rates_with_ttm(data, 'net_income', years=3)
    valid_rates = [r for r in growth_rates if r is not None and r > 0]
    if not valid_rates:
        return None
    avg_growth = sum(valid_rates) / len(valid_rates)
    if avg_growth <= 0:
        return None
    return per / avg_growth


# ============================================================================
# 성장률/마진 헬퍼
# ============================================================================

def get_growth_rates_with_ttm(data: Dict, key: str, years: int = 5) -> List[Optional[float]]:
    """TTM + 연간 데이터로 YoY 성장률 시리즈"""
    ttm = data.get(f'{key}_ttm')
    annual = data.get('annual', {}).get(key, {})
    sorted_annual = sorted(annual.items(), key=lambda x: x[0], reverse=True)
    annual_values = [v for _, v in sorted_annual]

    values = [ttm] + annual_values if ttm is not None else annual_values

    rates = []
    for i in range(min(years, len(values) - 1)):
        curr, prev = values[i], values[i + 1]
        if curr is not None and prev is not None and prev != 0 and not np.isnan(curr) and not np.isnan(prev):
            rates.append(round(((curr / prev) - 1) * 100, 2))
        else:
            rates.append(None)
    return rates


def get_annual_growth_rates(data: Dict, key: str, years: int = 5) -> List[Optional[float]]:
    """연간 데이터만으로 YoY 성장률"""
    annual = data.get('annual', {}).get(key, {})
    sorted_annual = sorted(annual.items(), key=lambda x: x[0], reverse=True)
    values = [v for _, v in sorted_annual]

    rates = []
    for i in range(min(years, len(values) - 1)):
        curr, prev = values[i], values[i + 1]
        if curr is not None and prev is not None and prev != 0 and not np.isnan(curr) and not np.isnan(prev):
            rates.append(round(((curr / prev) - 1) * 100, 2))
        else:
            rates.append(None)
    return rates


def get_operating_margins(data: Dict, years: int = 5) -> List[Optional[float]]:
    """영업이익률 시리즈 (TTM + 연간)"""
    margins = []
    rev_ttm = data.get('revenue_ttm')
    op_ttm = data.get('operating_income_ttm')
    if rev_ttm and op_ttm and rev_ttm != 0:
        margins.append(round((op_ttm / rev_ttm) * 100, 2))

    annual_rev = data.get('annual', {}).get('revenue', {})
    annual_op = data.get('annual', {}).get('operating_income', {})
    sorted_years = sorted(annual_rev.keys(), reverse=True)
    for year in sorted_years[:years]:
        rev = annual_rev.get(year)
        op = annual_op.get(year)
        if rev and op and rev != 0:
            margins.append(round((op / rev) * 100, 2))
        else:
            margins.append(None)

    return margins[:years + 1]


# ============================================================================
# 캐시 저장/로드
# ============================================================================

def save_fnguide_cache(results: Dict[str, Dict], filepath: str) -> None:
    """FnGuide 수집 결과를 pickle 캐시로 저장"""
    import pickle
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'wb') as f:
        pickle.dump(results, f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"캐시 저장: {filepath} ({len(results)}개 종목, {size_mb:.1f}MB)")


def load_fnguide_cache(filepath: str = None) -> Optional[Dict[str, Dict]]:
    """FnGuide pickle 캐시 로드. filepath이 None이면 .cache/에서 최신 파일 탐색."""
    import pickle
    import glob as glob_mod

    if filepath and os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                data = pickle.load(f)
            print(f"캐시 로드: {filepath} ({len(data)}개 종목)")
            return data
        except Exception as e:
            print(f"캐시 로드 실패: {e}")
            return None

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(script_dir, '.cache')
    if not os.path.exists(cache_dir):
        return None

    pkl_files = sorted(
        glob_mod.glob(os.path.join(cache_dir, 'fnguide_*.pkl')),
        reverse=True
    )
    for pkl_file in pkl_files:
        try:
            with open(pkl_file, 'rb') as f:
                data = pickle.load(f)
            print(f"캐시 로드: {pkl_file} ({len(data)}개 종목)")
            return data
        except Exception:
            continue

    return None


if __name__ == '__main__':
    print("=" * 60)
    print("FnGuide 재무데이터 테스트: 삼성전자 (005930)")
    print("=" * 60)

    data = get_financial_data('005930')
    if data:
        print(f"\n연간 손익계산서:")
        for key, values in data.get('annual', {}).items():
            print(f"  {key}: {values}")
        print(f"\nTTM 데이터:")
        for key in ['revenue_ttm', 'operating_income_ttm', 'net_income_ttm', 'cfo_ttm']:
            print(f"  {key}: {data.get(key)}")
        print(f"\n재무상태표:")
        for key, value in data.get('balance', {}).items():
            print(f"  {key}: {value}")
        print(f"\nROE: {get_roe(data)}, EBIT: {get_ebit(data)}")
    else:
        print("데이터 수집 실패")
