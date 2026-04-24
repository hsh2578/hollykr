# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HollyKR — Trade Ideas Holly AI의 한국 시장 적응 버전.
32개 전략, ATR 기반 백테스트, 매일 자동 텔레그램 시그널 전송.
사용자가 시그널 보고 직접 매수/매도 판단 (자동매매 아님).

## How to Run

```bash
pip install -r requirements.txt

# 실전 모드 (검증된 10개 전략, 종가매매, 텔레그램)
python -m scripts.screeners.holly_kr.run --proven --entry close --telegram

# 야간 전략 선정 (18:00 실행, 내일 쓸 전략 자동 선별)
python -m scripts.screeners.holly_kr.run --nightly --entry close --csv

# 자동 모드 (야간 선정 결과 사용, 14:40 실행)
python -m scripts.screeners.holly_kr.run --auto --entry close --telegram

# 전체 32개 전략 스캔
python -m scripts.screeners.holly_kr.run --entry close --telegram

# 백테스트 (Train/Test OOS 분할)
python -m scripts.screeners.holly_kr.backtest --days 200 --sample 200 --entry close --csv

# 단일 전략 백테스트 / 스캔
python -m scripts.screeners.holly_kr.run --strategy tailwind --entry close

# 데이터 수집·검증
python -m scripts.investor_data              # 수급(KIS) 테스트
python -m scripts.kis_sector_data --test     # 섹터 10종목 테스트
python -m scripts.kis_sector_data --collect  # 전종목 섹터 수집 (7~10분)
python -m scripts.kis_price                  # 현재가 조회 테스트
python -m scripts.telegram_alert             # 텔레그램 전송 테스트
python collect_data.py                       # 재무 증분 수집
```

## Architecture

```
config.py                     # 공통 설정 (BASE_DIR, CACHE_DIR, DATA_DIR)
collect_data.py               # 재무데이터 배치 수집기

scripts/
  krx_data.py                 # KRX 종목 마스터 (OTP → 네이버 → FDR 폴백)
  ohlcv_data.py               # OHLCV (FDR/Yahoo, 증분 파일 캐시)
  investor_data.py            # 외국인/기관 수급 (KIS primary, 네이버 fallback)
  kis_sector_data.py          # KRX 업종 분류 (KIS bstp_kor_isnm, 캐시)
  kis_price.py                # KIS 실시간 현재가
  fnguide_data.py             # FnGuide 재무제표 (Piotroski/Magic Formula용)
  telegram_alert.py           # 텔레그램 (강력/관심 2단계, 현재가·사유 포함)
  utils/indicators.py         # 기술적 지표

  screeners/
    holly_kr/                 # HollyKR 스크리너 본체
      config.py               # 유니버스/비용/포지션 파라미터
      run.py                  # CLI (--proven/--auto/--nightly/--strategy)
      scanner.py              # 오케스트레이터 (전략 순회 + 수급 + 레짐)
      backtest.py             # 백테스트 엔진 (OOS, 슬리피지, 거래비용)
      signal_model.py         # Signal 데이터클래스 (reason, current_price 포함)
      indicators.py           # RS Rating, 캔들 패턴, RSI
      universe.py             # 유니버스 + 섹터 매핑 (KIS 우선, WICS 폴백)
      output.py               # 터미널 + CSV/JSON
      confidence.py           # 종합 신뢰도 (수급+레짐+다중부스트)
      exit_manager.py         # 청산 규칙
      nightly_selector.py     # 야간 전략 선정
      active_strategies.py    # 야간 선정 결과 저장/로드
      strategies/             # 32개 전략 (base.py가 reason 파라미터 지원)
      filters/
        theme_filter.py       # 테마주/작전주 제외
        market_filter.py      # 시장 레짐 판별
        dedup.py              # 중복 시그널 처리 (3+ 전략 동시 매수 시 부스트)
    pairs_trading/            # 페어 트레이딩 스크리너 (별도 프로젝트, 분리됨)

.github/workflows/
  holly-daily.yml             # 평일 14:40 KST 자동 스캔
  holly-backtest.yml          # 평일 20:00 KST 자동 백테스트

deploy/
  hollykr_scan.bat            # Windows 스케줄러용 (GitHub Actions 병행)
  hollykr_nightly.bat         # 야간 선정용
```

## 데이터 소스 (글로벌 IP 호환)

| 데이터 | 소스 | IP 의존 | 비고 |
|---|---|---|---|
| OHLCV | FinanceDataReader (Yahoo) | ✅ 글로벌 | 영구 파일 캐시 `.cache/ohlcv/ohlcv_cache.pkl` |
| 종목 마스터 | KRX → 네이버 → FDR 폴백 | 🟡 | FDR 폴백으로 글로벌에서도 동작 |
| 외국인/기관 수급 | **KIS OpenAPI** `FHKST01010900` | ✅ 글로벌 | OAuth 토큰, 네이버 크롤링 폴백 |
| 섹터 (KRX 업종) | **KIS OpenAPI** `FHKST01010100` | ✅ 글로벌 | `bstp_kor_isnm`, WICS 캐시 폴백 |
| 현재가 | **KIS OpenAPI** `FHKST01010100` | ✅ 글로벌 | `stck_prpr` 실시간 |
| 재무제표 | FnGuide HTML 스크래핑 | 🟡 | Piotroski/Magic Formula용 (proven 전략엔 미사용) |

## 실전 전략 (OOS Test PF 기준)

**강력 (PF 2.0+ at Test)**
- close_to_a_cross (PF 3.61), weinstein_stage (PF 3.33), tailwind (PF 4.52)

**관심 (PF 1.2+ at Test)**
- wake_up_call (PF 1.42), quarterback (PF 1.21), nice_chart (PF 1.25)

**⚠️ 과적합 감지 (Train PASS / Test FAIL)**
- volume_doesnt_lie, float_on, staggering_volume, bullish_pullback,
  strong_stock_pulling_back, pushing_the_spring, darvas_box (FAIL)
- `PROVEN_STRATEGIES`에 포함돼 있지만 Test 단계에서 손실. 재평가 필요.

## 핵심 설정

- 유니버스: 시총 1,000억+, 보통주, 스팩/리츠 제외 → 약 1,500종목
- 거래비용: 0.21% (매수 0.015% + 매도 0.015% + 세금 0.18%)
- 슬리피지: 대형주 0.1%, 중형주 0.2%, 소형주 0.5%
- ATR 목표/손절: 목표 ATR × 3, 손절 ATR × 2
- 신뢰도: base × 수급(1.0~1.3) × 레짐 × 다중부스트(1.1~1.25), 상한 0.95
- 수급 등급: S(동반매도→동반매수 전환) / A(동반매수+가속) / A-(동반매수) / B / C / D
- **시그널 캡: 강력 우선 최대 5개 + 관심으로 채워 총 10개**

## 텔레그램 포맷 (중요 변경)

각 시그널은 다음 정보 포함:
- 진입가(종가/시가) | **현재가 + 변동률** (KIS 실시간)
- 목표 / 손절 (ATR 기반)
- 신뢰도 | 수급등급 | N개전략동시
- **매수 사유**: 전략 트리거 조건을 구체적 숫자로 서술
  - 예: `MA5>MA50 골든크로스 · 당일 +3.2% 상승 · 거래량 2.5배`
  - 예: `Darvas 박스 상단 70,000원 돌파 · 거래량 3.0배`

## 환경 변수 (.env)

프로젝트는 로컬 `.env` + 상위 통합 `.env` 병행 로드.
통합 .env 경로: `{repo_parent}/../.env` (`C:\Users\hsh\Desktop\vibecoding\.env`).

```
KIS_APP_KEY
KIS_APP_SECRET
KIS_BASE_URL          # 모의: https://openapivts.koreainvestment.com:29443
                      # 실전: https://openapi.koreainvestment.com:9443
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

GitHub Actions 사용 시 GitHub repo Settings → Secrets에 동일 키 등록.

## 스케줄 (2중 운영)

**GitHub Actions (주 실행)**
- Daily Scan: cron `20 3 * * 1-5` (UTC 03:20 = KST 12:20 스케줄)
  → GitHub Actions 지연 평균 2시간, 실제 ~14:20 KST 실행 예상
- Daily Backtest: cron `0 11 * * 1-5` (UTC 11:00 = KST 20:00 스케줄)
  → 지연 ~1시간, 실제 ~21:00 KST 실행
- 첫 실행 25~40분 (캐시 구축), 이후 3~8분
- 수동 트리거: `gh workflow run holly-daily.yml --repo hsh2578/hollykr`
- **주의**: GitHub Actions cron은 SLA 없음. 피크타임 지연으로 스케줄을 앞당겨 설정.

**Windows 작업 스케줄러 (백업 가능)**
- `deploy/hollykr_scan.bat` / `hollykr_nightly.bat`
- 필요 시 사용, 현재는 GitHub Actions로 대체 운영 가능

## GitHub Actions 관리 (gh CLI)

```bash
# 수동 트리거
gh workflow run holly-daily.yml --repo hsh2578/hollykr
gh workflow run holly-backtest.yml --repo hsh2578/hollykr

# 실행 목록/상태
gh run list --repo hsh2578/hollykr --limit 5

# 특정 job 로그 (전체)
gh run view --job=<job-id> --repo hsh2578/hollykr --log

# 실패한 스텝만
gh run view --job=<job-id> --repo hsh2578/hollykr --log-failed

# 시크릿 관리
gh secret list --repo hsh2578/hollykr
printf '%s' "value" | gh secret set NAME --repo hsh2578/hollykr
```

## 디버깅 커맨드

```bash
# OHLCV 캐시에서 특정 종목 최근값 확인 (캐시 정체 여부 점검)
python -c "import pickle; d=pickle.load(open('.cache/ohlcv/ohlcv_cache.pkl','rb')); print(d['005930_500'].tail())"

# KIS 토큰 만료일 확인
cat .cache/.kis_token.json

# 수급 캐시 상태 (종목별 pkl)
ls -la .cache/investor/ | head

# KIS 섹터 캐시 크기/행 수
wc -l .cache/kis_sectors.csv

# 유니버스 캐시 (당일) 검증
python -c "import pickle; d=pickle.load(open('.cache/holly_universe_YYYY-MM-DD.pkl','rb')); print(len(d), d.head())"

# 백테스트 CSV 판정 재계산 (판정 컬럼이 CSV에 없으므로 Train/Test 2행씩 그룹화 필요)
python -c "
import pandas as pd
df = pd.read_csv('data/holly_kr/backtest_summary_YYYY-MM-DD.csv')
for name, g in df.groupby('strategy', sort=False):
    g = g.reset_index(drop=True)
    if len(g) < 2: continue
    tr, te = g.iloc[0], g.iloc[1]
    print(f'{name}: Train PF={tr.profit_factor} / Test PF={te.profit_factor}')
"
```

## 단일 전략 실행

```bash
# 스캐너: 특정 전략만 (CLI 지원됨)
python -m scripts.screeners.holly_kr.run --strategy tailwind --entry close

# 백테스트: 현재 전체 32개만 지원. 특정 전략만 돌리려면
# backtest.py의 strategies 리스트를 임시 제한하거나 --strategy 플래그 추가 필요.
```

## 주의사항 / 과거 버그

- **OHLCV `_needs_update()` 버그 (수정됨)**: 이전엔 주말이면 무조건 `return False`라 캐시가 무기한 정체. 이제 "예상 최신 거래일" 기준으로 판단. 이 로직 건드릴 때는 주말 전환 테스트 필수.
- **FDR 수정종가**: Yahoo가 장 후 종가를 사후 보정할 수 있어, 같은 종목이라도 조회 시각에 따라 종가가 다를 수 있음. 시그널 재현이 안 될 때 확인.
- **KIS 모의투자 URL**: `openapivts.koreainvestment.com:29443` (현재 기본값). 투자자 동향·현재가·업종 등 조회 엔드포인트는 모의/실전 동일 데이터 반환.

## Known Limitations

- Phase 3 INTRADAY 12개 전략: 분봉 필요, 미구현
- Magic Formula / Piotroski: 스캐너 미연동 (별도 분기 리밸런싱 필요)
- FnGuide 스크래핑: HTML 변경 시 파싱 수정 필요
- 백테스트는 과거 수급 데이터 없이 OHLCV만 사용 (실시간 신뢰도 부스트와 다름)
