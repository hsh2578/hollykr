"""
DART 전자공시시스템 데이터 수집 스크립트
- 회사 고유번호 조회
- 재무제표 (손익계산서, 재무상태표) 수집
- 사업보고서 목록 조회
- 사업보고서 본문 다운로드 및 핵심 섹션 추출
"""

import requests
import json
import sys
import os
import re
import zipfile
import io
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

def _load_env_auto():
    """프로젝트 → 상위 폴더 .env 자동 로드"""
    here = Path(__file__).resolve().parent
    for env_path in [here.parent / '.env', here.parent.parent / '.env', here.parent.parent.parent / '.env']:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            pass

_load_env_auto()

DART_API_KEY = os.environ.get("DART_API_KEY", "")
if not DART_API_KEY:
    print("[WARN] DART_API_KEY 환경변수가 설정되지 않았습니다. https://opendart.fss.or.kr 에서 발급 후 설정하세요.", file=sys.stderr)
BASE_URL = "https://opendart.fss.or.kr/api"


def get_corp_code(company_name: str) -> tuple[str, str]:
    """회사명으로 고유번호 조회 (DART 고유번호 전체 목록에서 검색)"""
    url = f"{BASE_URL}/corpCode.xml"
    params = {"crtfc_key": DART_API_KEY}
    resp = requests.get(url, params=params)
    resp.raise_for_status()

    # ZIP 파일로 반환됨 → 압축 해제
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    xml_data = z.read(z.namelist()[0])
    root = ET.fromstring(xml_data)

    results = []
    for corp in root.findall("list"):
        name = corp.findtext("corp_name", "")
        code = corp.findtext("corp_code", "")
        stock_code = corp.findtext("stock_code", "").strip()
        if company_name in name and stock_code:  # 상장사만
            results.append((name, code, stock_code))

    if not results:
        raise ValueError(f"'{company_name}'에 해당하는 상장사를 찾을 수 없습니다.")

    # 정확히 일치하는 것 우선
    for name, code, stock_code in results:
        if name == company_name:
            print(f"[OK] {name} (고유번호: {code}, 종목코드: {stock_code})")
            return code, stock_code

    # 없으면 첫 번째 결과
    name, code, stock_code = results[0]
    print(f"[OK] {name} (고유번호: {code}, 종목코드: {stock_code})")
    return code, stock_code


def get_financial_statements(corp_code: str, year: str, report_code: str = "11011") -> dict:
    """
    재무제표 조회
    report_code: 11011=사업보고서, 11012=반기보고서, 11013=1분기, 11014=3분기
    """
    url = f"{BASE_URL}/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": year,
        "reprt_code": report_code,
        "fs_div": "OFS"  # OFS: 개별, CFS: 연결
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def get_consolidated_statements(corp_code: str, year: str, report_code: str = "11011") -> dict:
    """연결 재무제표 조회"""
    url = f"{BASE_URL}/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": year,
        "reprt_code": report_code,
        "fs_div": "CFS"  # 연결재무제표
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def get_disclosure_list(corp_code: str, page_count: int = 10) -> dict:
    """최근 공시 목록 조회"""
    url = f"{BASE_URL}/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "page_count": page_count,
        "sort": "date",
        "sort_mth": "desc"
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def get_major_reports(corp_code: str) -> dict:
    """사업보고서/반기/분기보고서 목록"""
    url = f"{BASE_URL}/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "pblntf_ty": "A",  # A: 정기공시
        "page_count": 50,  # v4.10: 20→50 확대 (분기보고서 누락 방지)
        "sort": "date",
        "sort_mth": "desc"
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def format_krw(val_str: str) -> str:
    """원화 금액 포맷"""
    try:
        val = int(val_str.replace(",", ""))
        if abs(val) >= 1_000_000_000_000:
            return f"{val/1_000_000_000_000:.2f}조원"
        elif abs(val) >= 100_000_000:
            return f"{val/100_000_000:.0f}억원"
        elif abs(val) >= 10_000:
            return f"{val/10_000:.0f}만원"
        else:
            return f"{val}원"
    except (ValueError, AttributeError):
        return val_str


def extract_key_metrics(data: dict) -> dict:
    """재무제표에서 핵심 지표 추출 (필터링 없이 전체 저장)"""
    if data.get("status") != "000":
        return {"error": data.get("message", "데이터 없음")}

    items = data.get("list", [])

    result = {}
    for item in items:
        account_name = item.get("account_nm", "")
        if not account_name:
            continue

        current = item.get("thstrm_amount", "")
        prev = item.get("frmtrm_amount", "")
        prev2 = item.get("bfefrmtrm_amount", "")

        if current and current != "-":
            result[account_name] = {
                "당기": current,
                "전기": prev if prev and prev != "-" else "N/A",
                "전전기": prev2 if prev2 and prev2 != "-" else "N/A"
            }

    return result


# ============================================
# 사업보고서 본문 추출
# ============================================

class HTMLTextExtractor(HTMLParser):
    """HTML에서 텍스트만 추출하는 파서"""
    def __init__(self):
        super().__init__()
        self.result = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip = True
        if tag in ('br', 'p', 'div', 'tr', 'li', 'h1', 'h2', 'h3', 'h4'):
            self.result.append('\n')
        if tag == 'td':
            self.result.append('\t')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.result.append(data)

    def get_text(self):
        text = ''.join(self.result)
        # 연속 빈줄 정리
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 연속 공백 정리
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()


def html_to_text(html_content: str) -> str:
    """HTML을 텍스트로 변환"""
    parser = HTMLTextExtractor()
    parser.feed(html_content)
    return parser.get_text()


def get_all_report_rcept_nos(corp_code: str) -> list:
    """최근 6개 정기보고서 + 전년 사업보고서 1개 = 최대 7개 접수번호 조회 (v4.10)

    v4.10 확대: 기존 4개 → 6개. 삼성전자 사례처럼 최근 4개가 사업+반기 2쌍으로 채워져
    Q1/Q3 분기보고서가 누락되는 사고 방지. 분기보고서는 최신 변화점 (신규 계약, 소송,
    CapEx 변경, 위험 요인 변화) 검출에 필수이므로 반드시 포함한다.

    Returns:
        list of dict: [{"rcept_no", "report_nm", "rcept_dt", "type"}, ...]
        type: "사업보고서" / "1분기보고서" / "반기보고서" / "3분기보고서"
    """
    from datetime import datetime, timedelta
    url = f"{BASE_URL}/list.json"

    # 임원 관련 공시가 많아 100건이 금방 차므로, 6개월씩 나눠서 조회
    now = datetime.now()
    periods = []
    for i in range(4):  # 최근 2년을 6개월씩 4구간
        end_dt = now - timedelta(days=180 * i)
        start_dt = now - timedelta(days=180 * (i + 1))
        periods.append((start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d")))

    all_items = []
    for start_date, end_date in periods:
        params = {
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bgn_de": start_date,
            "end_de": end_date,
            "page_count": 100,
            "sort": "date",
            "sort_mth": "desc"
        }
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "000":
            all_items.extend(data.get("list", []))

    if not all_items:
        print(f"    공시 검색 실패")
        return []

    # 중복 제거 (겹치는 기간 경계)
    seen_rcept = set()
    deduped = []
    for item in all_items:
        rcept_no = item.get("rcept_no", "")
        if rcept_no not in seen_rcept:
            seen_rcept.add(rcept_no)
            deduped.append(item)
    all_items = deduped

    # 정기보고서 필터링
    # 정기보고서는 보고서명이 "사업보고서", "반기보고서", "분기보고서"로 시작함
    # "기업지배구조보고서" 등 다른 보고서 제외
    all_reports = []
    for item in all_items:
        report_name = item.get("report_nm", "").strip()

        rtype = None
        # 정확한 매칭: 보고서명이 해당 키워드로 시작해야 함
        if report_name.startswith("사업보고서"):
            rtype = "사업보고서"
        elif report_name.startswith("[정정]사업보고서") or report_name.startswith("정정 사업보고서"):
            rtype = "사업보고서"
        elif report_name.startswith("반기보고서") or report_name.startswith("[정정]반기보고서"):
            rtype = "반기보고서"
        elif report_name.startswith("분기보고서") or report_name.startswith("[정정]분기보고서"):
            # DART: "분기보고서 (2025.09)" 또는 "분기보고서 (2025.03)"
            if ".03)" in report_name:
                rtype = "1분기보고서"
            elif ".09)" in report_name:
                rtype = "3분기보고서"
            else:
                rtype = "분기보고서"

        if rtype:
            all_reports.append({
                "rcept_no": item.get("rcept_no", ""),
                "report_nm": report_name,
                "rcept_dt": item.get("rcept_dt", ""),
                "type": rtype,
            })

    if not all_reports:
        print("    정기보고서를 찾지 못했습니다.")
        return []

    # v4.10: 최근 6개 + 전년 사업보고서 1개 선별 (분기보고서 누락 방지)
    all_reports.sort(key=lambda x: x["rcept_dt"], reverse=True)

    selected = []
    annual_count = 0

    for report in all_reports:
        if len(selected) < 6:
            selected.append(report)
            if report["type"] == "사업보고서":
                annual_count += 1
        elif report["type"] == "사업보고서" and annual_count < 2:
            # 전년 사업보고서 (YoY 비교용)
            selected.append(report)
            annual_count += 1
            break

    for r in selected:
        print(f"    [OK] {r['type']}: {r['report_nm']} ({r['rcept_dt']})")

    return selected


def download_report_document(rcept_no: str) -> dict:
    """사업보고서 원본 ZIP 다운로드 후 HTML 파일들 추출"""
    url = f"{BASE_URL}/document.xml"
    params = {
        "crtfc_key": DART_API_KEY,
        "rcept_no": rcept_no,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    # ZIP 파일 확인
    if resp.content[:2] != b'PK':
        print(f"    ZIP 파일이 아닙니다. 응답 크기: {len(resp.content)}")
        return {}

    z = zipfile.ZipFile(io.BytesIO(resp.content))
    files = {}
    for name in z.namelist():
        if name.endswith('.htm') or name.endswith('.html') or name.endswith('.xml'):
            try:
                content = z.read(name).decode('utf-8', errors='ignore')
                files[name] = content
            except Exception:
                try:
                    content = z.read(name).decode('euc-kr', errors='ignore')
                    files[name] = content
                except Exception:
                    pass

    print(f"[OK] 문서 다운로드 완료: {len(files)}개 파일")
    return files


def extract_report_sections(files: dict) -> dict:
    """사업보고서 HTML 파일들에서 핵심 섹션 추출"""

    # 핵심 섹션 키워드 매핑
    # (섹션명, 키워드 목록, 최대 추출 글자수)
    section_config = {
        "사업의_내용": (["사업의 내용", "사업의내용", "II. 사업의 내용", "주요 제품 및 서비스"], 15000),
        "위험_요인": (["위험 요인", "투자위험요소", "주요 리스크", "투자 위험", "위험요소", "경영상의 주요계약"], 8000),
        "경영진_현황": (["임원 및 직원", "임원및직원", "이사의 경영진단", "임원의 현황"], 5000),
        "주주_현황": (["주주에 관한 사항", "최대주주", "주식의 총수"], 5000),
        "배당_정보": (["배당에 관한 사항", "이익배당", "배당금", "주주환원"], 5000),
        "주요_계약": (["기타 참고사항", "주요계약", "그 밖에 투자자"], 5000),
        "연구개발": (["연구개발활동", "연구 개발", "R&D"], 8000),
        "임원_보수": (["이사·감사의 보수현황", "임원의 보수", "보수총액", "이사 감사의 보수"], 5000),
    }

    # 모든 파일의 텍스트를 합침
    all_text = ""
    file_texts = {}
    for fname, html in files.items():
        text = html_to_text(html)
        file_texts[fname] = text
        all_text += f"\n===FILE:{fname}===\n{text}"

    sections = {}

    for section_key, (keywords, max_chars) in section_config.items():
        best_match = ""
        best_len = 0

        for fname, text in file_texts.items():
            for keyword in keywords:
                idx = text.find(keyword)
                if idx != -1:
                    extracted = text[idx:idx + max_chars]
                    if len(extracted) > best_len:
                        best_match = extracted
                        best_len = len(extracted)

        if best_match:
            sections[section_key] = best_match
            print(f"    [OK] {section_key}: {len(best_match)}자 추출")
        else:
            print(f"    [--] {section_key}: 미발견")

    return sections


def get_all_reports(corp_code: str) -> list:
    """최근 4개 정기보고서 + 전년 사업보고서에서 핵심 섹션 추출

    Returns:
        list of dict: [{
            "rcept_no", "report_nm", "rcept_dt", "type",
            "sections": {섹션명: 텍스트, ...},
            "file_count": int
        }, ...]
    """
    print("\n[정기보고서 본문 수집 (최근 4개 + 전년 사업보고서)]")

    # 1. 보고서 목록 조회
    reports = get_all_report_rcept_nos(corp_code)
    if not reports:
        return []

    results = []
    for i, report in enumerate(reports):
        rcept_no = report["rcept_no"]
        rtype = report["type"]
        print(f"\n  --- [{i+1}/{len(reports)}] {rtype} ({report['rcept_dt']}) 다운로드 중...")

        # 2. 문서 다운로드
        files = download_report_document(rcept_no)
        if not files:
            print(f"    다운로드 실패, 건너뜀")
            continue

        # 3. 섹션 추출
        sections = extract_report_sections(files)

        results.append({
            "rcept_no": rcept_no,
            "report_nm": report["report_nm"],
            "rcept_dt": report["rcept_dt"],
            "type": rtype,
            "sections": sections,
            "file_count": len(files),
        })

    print(f"\n[OK] 총 {len(results)}개 보고서 수집 완료")
    return results


def test_dart(company_name: str):
    """DART API 테스트"""
    print(f"\n{'='*60}")
    print(f"  DART 전자공시 데이터 수집 테스트: {company_name}")
    print(f"{'='*60}\n")

    # 1. 고유번호 조회
    print("[1] 회사 고유번호 조회 중...")
    corp_code, stock_code = get_corp_code(company_name)

    # 2. 최근 공시 목록
    print("\n[2] 최근 공시 목록:")
    disclosures = get_disclosure_list(corp_code)
    if disclosures.get("status") == "000":
        for item in disclosures.get("list", [])[:10]:
            print(f"    {item['rcept_dt']} | {item['report_nm']}")
    else:
        print(f"    공시 목록 조회 실패: {disclosures.get('message')}")

    # 3. 사업보고서 목록
    print("\n[3] 정기보고서 목록:")
    reports = get_major_reports(corp_code)
    if reports.get("status") == "000":
        for item in reports.get("list", [])[:10]:
            print(f"    {item['rcept_dt']} | {item['report_nm']}")
    else:
        print(f"    정기보고서 조회 실패: {reports.get('message')}")

    # 4. 연결 재무제표 (최근 사업보고서)
    print("\n[4] 연결 재무제표 (2024년 사업보고서):")
    fin_data = get_consolidated_statements(corp_code, "2024")
    metrics = extract_key_metrics(fin_data)

    if "error" in metrics:
        print(f"    연결재무제표 없음, 개별재무제표 시도...")
        fin_data = get_financial_statements(corp_code, "2024")
        metrics = extract_key_metrics(fin_data)

    if "error" in metrics:
        print(f"    2024년 데이터 없음, 2023년 시도...")
        fin_data = get_consolidated_statements(corp_code, "2023")
        metrics = extract_key_metrics(fin_data)
        if "error" in metrics:
            fin_data = get_financial_statements(corp_code, "2023")
            metrics = extract_key_metrics(fin_data)

    if "error" not in metrics:
        print(f"    {'─'*55}")
        print(f"    {'계정과목':<20} {'당기':>15} {'전기':>15}")
        print(f"    {'─'*55}")
        for account, values in metrics.items():
            current = format_krw(values['당기'])
            prev = format_krw(values['전기'])
            print(f"    {account:<20} {current:>15} {prev:>15}")
    else:
        print(f"    재무제표 조회 실패: {metrics['error']}")

    # 5. 정기보고서 본문 추출 (최근 4개 + 전년 사업보고서)
    print("\n[5] 정기보고서 본문 추출:")
    all_reports = get_all_reports(corp_code)
    if all_reports:
        print(f"\n    === 수집 결과 요약 ===")
        for report in all_reports:
            section_count = len(report.get("sections", {}))
            total_chars = sum(len(v) for v in report.get("sections", {}).values())
            print(f"    {report['type']} ({report['rcept_dt']}): {section_count}개 섹션, {total_chars:,}자")
    else:
        print("    정기보고서 본문 추출 실패")

    print(f"\n{'='*60}")
    print("  DART 테스트 완료!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    company = sys.argv[1] if len(sys.argv) > 1 else "삼성전자"
    test_dart(company)
