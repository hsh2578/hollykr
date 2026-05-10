"""
Sub-agent 사전 데이터 수집 헬퍼 — DART 공시 + FnGuide 재무 (Phase G-9 강화)

dart_api.py + fnguide_data.py 모듈을 활용하여 31개 종목의
- DART: 최근 1년 공시 (자사주/임원매도/유상증자 키워드 매칭)
- FnGuide: 재무 지표 (영업CF, 부채비율, ROE/ROIC, PER/PBR, 컨센서스)

를 병렬 수집한다. 결과는 sub_agent_input.json의 'dart' + 'fnguide' 섹션에 저장.

목적:
- Sub-agent (Stage B Opus)가 WebFetch 호출 X
- 이익 질 / 임원 매도 / 부채비율 자동 포착
- 분석 깊이 ↑, 시간 ↓
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

# 동일 폴더의 모듈
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dart_api import DART_API_KEY, BASE_URL
from fnguide_data import (
    get_financial_data,
    get_consensus_estimates,
    get_roe, get_roa, get_roic,
    get_debt_ratio, get_current_ratio,
    get_per_from_data, get_pbr_from_data,
    get_psr, get_pcr, get_cfo_ratio,
    get_operating_margins,
    get_annual_growth_rates,
)


# ============================================================================
# DART — 공시 + corp_code 캐시
# ============================================================================

_CORP_CACHE: Optional[Dict[str, str]] = None  # stock_code → corp_code


def _load_corp_code_cache() -> Dict[str, str]:
    """KRX 상장사 corp_code 일괄 로드 (한 번만 호출, ZIP)"""
    global _CORP_CACHE
    if _CORP_CACHE is not None:
        return _CORP_CACHE

    import zipfile, io
    import xml.etree.ElementTree as ET

    url = f'{BASE_URL}/corpCode.xml'
    resp = requests.get(url, params={'crtfc_key': DART_API_KEY}, timeout=30)
    resp.raise_for_status()

    z = zipfile.ZipFile(io.BytesIO(resp.content))
    xml_data = z.read(z.namelist()[0])
    root = ET.fromstring(xml_data)

    cache = {}
    for corp in root.findall('list'):
        stock_code = corp.findtext('stock_code', '').strip()
        corp_code = corp.findtext('corp_code', '').strip()
        if stock_code and corp_code:
            cache[stock_code] = corp_code

    _CORP_CACHE = cache
    return cache


# 키워드 분류 (공시 보고서명 기반)
EVENT_KEYWORDS = {
    '자사주': ['자기주식', '자사주'],
    '임원매도': ['주요사항보고서(자기주식', '임원·주요주주특정증권'],
    '유상증자': ['유상증자', '주식회사의외부감사및회계'],
    '무상증자': ['무상증자'],
    '주식분할': ['주식분할', '액면분할'],
    '배당': ['현금·현물배당', '주식배당'],
    '주요사항': ['주요사항보고서'],
    '최대주주변경': ['최대주주변경', '최대주주등소유주식'],
    '실적공시': ['연결재무제표', '재무제표', '잠정실적'],
    '임시주총': ['주주총회'],
}


def _classify_disclosures(items: List[dict]) -> Dict[str, List[dict]]:
    """공시 보고서명을 키워드로 분류"""
    result = {k: [] for k in EVENT_KEYWORDS}
    result['기타'] = []

    for it in items:
        report_nm = it.get('report_nm', '')
        matched = False
        for key, keywords in EVENT_KEYWORDS.items():
            if any(kw in report_nm for kw in keywords):
                result[key].append({
                    'date': it.get('rcept_dt', ''),
                    'name': report_nm,
                    'rcept_no': it.get('rcept_no', ''),
                })
                matched = True
                break
        if not matched:
            pass  # 기타 무시 (소음 감소)

    # 빈 리스트 제거
    return {k: v for k, v in result.items() if v}


def get_dart_summary(stock_code: str, days: int = 365) -> Dict:
    """한 종목의 DART 공시 요약 (최근 days일)"""
    cache = _load_corp_code_cache()
    corp_code = cache.get(str(stock_code).zfill(6))

    if not corp_code:
        return {'error': 'corp_code_not_found', 'stock_code': stock_code}

    # 최근 days일 조회
    end = datetime.now()
    bgn = end - timedelta(days=days)

    url = f'{BASE_URL}/list.json'
    params = {
        'crtfc_key': DART_API_KEY,
        'corp_code': corp_code,
        'bgn_de': bgn.strftime('%Y%m%d'),
        'end_de': end.strftime('%Y%m%d'),
        'page_count': 100,
        'sort': 'date',
        'sort_mth': 'desc',
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
    except Exception as e:
        return {'error': f'request_failed: {e}'}

    if data.get('status') not in ('000', '013'):  # 013 = 데이터 없음 (정상)
        return {'error': f'dart_status_{data.get("status")}', 'message': data.get('message', '')}

    items = data.get('list', []) if data.get('status') == '000' else []
    classified = _classify_disclosures(items)

    return {
        'corp_code': corp_code,
        'period': f'{bgn.strftime("%Y-%m-%d")} ~ {end.strftime("%Y-%m-%d")}',
        'total_count': len(items),
        'events': classified,  # 카테고리별 공시 이벤트
        'recent_5': [
            {'date': it.get('rcept_dt', ''), 'name': it.get('report_nm', '')[:60]}
            for it in items[:5]
        ],
    }


# ============================================================================
# FnGuide — 재무 핵심 지표 추출 (1125 lines 모듈에서 필요한 것만)
# ============================================================================

def get_fnguide_summary(stock_code: str, market_cap_eok: Optional[float] = None) -> Dict:
    """한 종목의 FnGuide 재무 요약 (helper 함수 활용)"""
    try:
        data = get_financial_data(str(stock_code).zfill(6), retry=2)
    except Exception as e:
        return {'error': f'fnguide_failed: {e}'}

    if not data:
        return {'error': 'fnguide_no_data'}

    annual = data.get('annual', {})
    header = data.get('header', {})

    # TTM 지표
    revenue_ttm = data.get('revenue_ttm')
    op_income_ttm = data.get('operating_income_ttm')
    net_income_ttm = data.get('net_income_ttm')
    cfo_ttm = data.get('cfo_ttm')

    # 이익 질: CFO/순이익 비율 (1.0 이상 = 양호)
    cfo_to_ni = (cfo_ttm / net_income_ttm) if (cfo_ttm and net_income_ttm and net_income_ttm != 0) else None

    # FnGuide 헬퍼 함수 활용 (정확한 키 매핑)
    debt_ratio = get_debt_ratio(data)
    current_ratio_x = get_current_ratio(data)  # 배수 (1.5 = 150%)
    current_ratio_pct = (current_ratio_x * 100) if current_ratio_x else None
    roe = get_roe(data)
    roa = get_roa(data)
    roic = get_roic(data)

    # 영업이익률
    op_margin_ttm = (op_income_ttm / revenue_ttm * 100) if (op_income_ttm and revenue_ttm) else None
    op_margins_5y = get_operating_margins(data, years=5)
    revenue_growth_5y = get_annual_growth_rates(data, 'revenue', years=5)
    op_growth_5y = get_annual_growth_rates(data, 'operating_income', years=5)

    # PER/PBR (시가총액 필요 — sub_agent_data_prep에서 전달)
    per = get_per_from_data(market_cap_eok, data) if market_cap_eok else None
    pbr = get_pbr_from_data(market_cap_eok, data) if market_cap_eok else None
    psr = get_psr(market_cap_eok, data) if market_cap_eok else None
    pcr = get_pcr(market_cap_eok, data) if market_cap_eok else None

    return {
        'header': {
            'per_fnguide': header.get('PER'),
            'per_12m': header.get('12M_PER'),
            'industry_per': header.get('업종PER'),
            'pbr_fnguide': header.get('PBR'),
            'div_yield': header.get('배당수익률'),
        },
        'ttm': {
            'revenue': revenue_ttm,
            'op_income': op_income_ttm,
            'net_income': net_income_ttm,
            'cfo': cfo_ttm,
            'op_margin_pct': op_margin_ttm,
        },
        'quality': {
            'cfo_to_ni': cfo_to_ni,  # ★ 이익 질 (1.0+ = 양호, 0.5- = 의심)
            'debt_ratio_pct': debt_ratio,  # ★ 부채비율 (200%+ = 위험)
            'current_ratio_pct': current_ratio_pct,  # ★ 유동비율 (100%- = 단기 압박)
            'roe_pct': roe,  # ★ ROE (자본 효율)
            'roa_pct': roa,
            'roic_pct': roic,
        },
        'valuation': {
            'per_calc': per,  # 시총 / 순이익 (직접 계산)
            'pbr_calc': pbr,
            'psr': psr,
            'pcr': pcr,
        },
        'trends_5y': {
            'op_margins_pct': op_margins_5y,
            'revenue_growth_pct': revenue_growth_5y,
            'op_income_growth_pct': op_growth_5y,
        },
    }


# ============================================================================
# 컨센서스 (별도 함수, 실패해도 무시)
# ============================================================================

def get_consensus_summary(stock_code: str) -> Dict:
    """애널리스트 컨센서스 추정치 요약"""
    try:
        c = get_consensus_estimates(str(stock_code).zfill(6), retry=1)
        if not c:
            return {'available': False}

        # 최근 컨센서스 (다음 분기 또는 다음 연도)
        return {
            'available': True,
            'data': c,  # 원본 그대로 (key 구조는 fnguide 모듈에서 확인)
        }
    except Exception as e:
        return {'available': False, 'error': str(e)}


# ============================================================================
# 병렬 수집 (메인 함수)
# ============================================================================

def collect_for_tickers(
    tickers: List[str],
    market_caps: Optional[Dict[str, float]] = None,
    max_workers: int = 6,
) -> Dict[str, Dict]:
    """
    여러 종목의 DART + FnGuide 데이터 병렬 수집.
    Returns: {stock_code: {dart: {...}, fnguide: {...}, consensus: {...}}}
    """
    # corp_code 캐시 사전 로드 (1회)
    print('  [DART] corp_code 캐시 로드 중...', flush=True)
    _load_corp_code_cache()
    print(f'  [DART] {len(_CORP_CACHE)} 종목 corp_code 로드 완료', flush=True)

    results: Dict[str, Dict] = {t: {} for t in tickers}

    def _fetch_one(ticker: str) -> tuple:
        out = {}
        try:
            out['dart'] = get_dart_summary(ticker, days=365)
        except Exception as e:
            out['dart'] = {'error': str(e)}
        try:
            mcap = (market_caps or {}).get(ticker)
            out['fnguide'] = get_fnguide_summary(ticker, market_cap_eok=mcap)
        except Exception as e:
            out['fnguide'] = {'error': str(e)}
        # consensus는 시간 절감 위해 옵션 (느림)
        # try:
        #     out['consensus'] = get_consensus_summary(ticker)
        # except Exception:
        #     out['consensus'] = {'available': False}
        return ticker, out

    print(f'  [수집 시작] {len(tickers)}개 종목, 병렬 {max_workers}', flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_one, t): t for t in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            ticker, out = fut.result()
            results[ticker] = out
            dart_ok = 'error' not in out.get('dart', {})
            fng_ok = 'error' not in out.get('fnguide', {})
            print(f'    [{i:2d}/{len(tickers)}] {ticker} DART={dart_ok} FnGuide={fng_ok}', flush=True)

    elapsed = time.time() - t0
    print(f'  [완료] {elapsed:.1f}초', flush=True)
    return results


if __name__ == '__main__':
    # 단일 테스트
    test_tickers = ['005930', '000660', '141080']
    results = collect_for_tickers(test_tickers, max_workers=3)
    import json
    for t, d in results.items():
        print(f'\n=== {t} ===')
        if 'error' in d.get('fnguide', {}):
            print('FnGuide ERROR:', d['fnguide']['error'])
        else:
            fng = d['fnguide']
            q = fng['quality']
            v = fng['valuation']
            print(f"  PER (FnGuide): {fng['header'].get('per_fnguide')}, PBR: {fng['header'].get('pbr_fnguide')}")
            roe = q.get('roe_pct')
            print(f"  ROE: {roe:.1f}%" if roe else "  ROE: N/A")
            cfo_ni = q.get('cfo_to_ni')
            print(f"  CFO/NI: {cfo_ni:.2f}" if cfo_ni else "  CFO/NI: N/A")
            dr = q.get('debt_ratio_pct')
            print(f"  부채비율: {dr:.0f}%" if dr else "  부채비율: N/A")
            cr = q.get('current_ratio_pct')
            print(f"  유동비율: {cr:.0f}%" if cr else "  유동비율: N/A")
            roic = q.get('roic_pct')
            print(f"  ROIC: {roic:.1f}%" if roic else "  ROIC: N/A")

        if 'error' in d.get('dart', {}):
            print('DART ERROR:', d['dart']['error'])
        else:
            dart = d['dart']
            print(f"  DART 공시 {dart['total_count']}건")
            for cat, items in dart.get('events', {}).items():
                print(f"    {cat}: {len(items)}건")
