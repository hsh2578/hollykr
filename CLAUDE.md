# CLAUDE.md

## Project Overview

한국 주식 데이터 수집·분석 프로젝트. 공통 데이터 수집 인프라 위에 다양한 스크리너를 구축하는 구조.
HollyKR: Trade Ideas Holly AI의 한국 버전 — 45개 전략, 매일 백테스트, 텔레그램 알림.

## How to Run

```bash
pip install -r requirements.txt

# 공통: 전 종목 재무데이터 수집
python collect_data.py             # 증분 수집 (이전 캐시 7일내 재사용, ~1분)
python collect_data.py --full      # 전체 재수집 (약 5~10분)

# 공통: 개별 모듈 테스트
python -m scripts.krx_data        # KRX 종목 마스터
python -m scripts.fnguide_data    # FnGuide 재무제표 (삼성전자)
python -m scripts.ohlcv_data      # OHLCV 차트 데이터
python -m scripts.investor_data   # 외국인/기관 수급 데이터

# 스크리너: HollyKR (Phase 1 EOD 12개 전략)
python -m scripts.screeners.holly_kr.run                    # 기본 실행
python -m scripts.screeners.holly_kr.run --csv --json       # 파일 저장
python -m scripts.screeners.holly_kr.run --telegram         # 텔레그램 알림
python -m scripts.screeners.holly_kr.run --strategy engulfing  # 특정 전략만

# 스크리너: 페어 트레이딩
python -m scripts.screeners.pairs_trading.run                    # 기본 실행
python -m scripts.screeners.pairs_trading.run --csv --json       # 파일 저장
python -m scripts.screeners.pairs_trading.run --signal ENTRY_STRONG
python -m scripts.screeners.pairs_trading.visualize              # 차트 생성

# 텔레그램 알림 테스트
python -m scripts.telegram_alert
```

## Architecture

```
config.py                     # 공통 설정 (경로, 네트워크, FnGuide, 수급)
collect_data.py               # 전종목 재무데이터 배치 수집기 (증분 수집)
scripts/
├── krx_data.py               # [공통] KRX 종목 마스터
├── fnguide_data.py           # [공통] FnGuide 재무제표
├── ohlcv_data.py             # [공통] FinanceDataReader OHLCV
├── investor_data.py          # [공통] 외국인/기관 수급 (네이버 금융)
├── telegram_alert.py         # [공통] 텔레그램 알림 전송
├── utils/
│   └── indicators.py         # [공통] 기술적 지표
└── screeners/
    ├── holly_kr/             # HollyKR 스크리너 (Holly AI 한국 버전)
    │   ├── config.py             # 유니버스/비용/포지션/RS Rating 설정
    │   ├── run.py                # CLI 진입점
    │   ├── scanner.py            # 오케스트레이터 (전략 순회 + 수급 등급)
    │   ├── signal_model.py       # Signal 데이터 클래스
    │   ├── indicators.py         # RS Rating, 캔들 패턴, RSI
    │   ├── universe.py           # 유니버스 필터 (WICS 기반)
    │   ├── output.py             # 터미널 테이블 + CSV/JSON
    │   ├── strategies/           # 12개 EOD 전략
    │   │   ├── base.py               # BaseStrategy 부모 클래스
    │   │   ├── pushing_the_spring.py  # 스프링 돌파
    │   │   ├── engulfing.py           # 장악형
    │   │   ├── yesterday_hammer.py    # 해머 반전
    │   │   ├── snap_back_long.py      # 과매도 반등
    │   │   ├── horseshoe_up.py        # 갭업 U자 반등
    │   │   ├── volume_doesnt_lie.py   # 거래량 폭발 갭
    │   │   ├── minervini_trend.py     # Minervini 8조건
    │   │   ├── darvas_box.py          # Darvas 박스 돌파
    │   │   ├── weinstein_stage.py     # Weinstein Stage 2
    │   │   ├── magic_formula.py       # Greenblatt ROIC+EY
    │   │   ├── piotroski_fscore.py    # Piotroski 9점
    │   │   └── livermore_pivot.py     # Livermore 신고가
    │   └── filters/
    │       ├── theme_filter.py       # 테마주/작전주 제외
    │       ├── market_filter.py      # 시장 레짐 판별
    │       └── dedup.py              # 중복 시그널 처리
    └── pairs_trading/        # 페어 트레이딩 스크리너
        ├── config.py             # 페어 전용 설정
        ├── run.py                # CLI 진입점
        ├── visualize.py          # 차트 생성
        ├── universe.py           # 유니버스 필터 + WICS 섹터
        ├── data_prep.py          # 가격 매트릭스 + 로그수익률
        ├── cointegration.py      # Engle-Granger 공적분 검정
        ├── stability.py          # 롤링 ADF + 반감기
        ├── zscore.py             # 멀티 윈도우 Z-Score
        ├── signals.py            # 시그널 생성 (오케스트레이터)
        └── output.py             # 터미널 테이블 + CSV/JSON
.cache/                       # 캐시 (fnguide pkl, wics_sectors.csv, investor/)
data/                         # 결과 출력
├── holly_kr/                 # HollyKR 결과
└── pairs/                    # 페어 트레이딩 결과
```

## 공통 데이터 수집

### 종목 마스터 (krx_data.py)
폴백 체인: KRX OTP CSV → finder_stkisu + MDCSTAT01501 → 네이버 모바일 API → FDR

### 재무제표 (fnguide_data.py)
SVD_Finance.asp + SVD_Main.asp, TTM 자동 계산, pickle 캐시

### OHLCV (ohlcv_data.py)
FinanceDataReader.DataReader(), 메모리 캐시

### 수급 데이터 (investor_data.py)
네이버 금융 외국인/기관 순매수 (finance.naver.com/item/frgn.naver)
수급 등급: A(동반매수) / B(일부매수) / C(중립) / D(동반매도)
pickle 캐시 (.cache/investor/), 12시간 유효

### 재무데이터 증분 수집 (collect_data.py)
이전 캐시 로드 → 7일 이내면 재사용 → 신규/갱신 종목만 FnGuide 수집
--full 옵션으로 전체 재수집 가능

## 스크리너: HollyKR (Holly AI 한국 버전)

- Trade Ideas Holly AI 모방 — 한국 시장 + 스윙(EOD) 특화
- Phase 1: 12개 EOD 전략 (기술적 6 + Holly 원본 4 + 전설적 퀀트 2)
- 파이프라인: 유니버스 → OHLCV → 전략 스캔 → 수급 등급 → 중복 제거 → 시그널
- 수급 연동: A등급 → 신뢰도 +10%, D등급 → 경고 + 신뢰도 -15%
- 텔레그램 알림: --telegram 옵션으로 시그널 자동 전송

## 스크리너: 페어 트레이딩

- WICS 중분류 섹터 기반 (wiseindex.com API → .cache/wics_sectors.csv)
- 파이프라인: 유니버스 필터 → OHLCV 수집 → 공적분 검정 → 안정성 검증 → Z-Score → 시그널
- OLS log(P_A) = α + β×log(P_B) + ε → ADF 검정 (p<0.05)
- 롤링 ADF 안정성 + OU 반감기(5~30일) + 멀티윈도우 Z-Score(20/60/120)
- 롱 온리 (한국 공매도 제한), 비용 필터 0.84%

## Known Limitations

- KRX OTP: 403/LOGOUT 반환 가능 → 폴백 자동 처리
- FnGuide: 동시 요청 최대 10개 (MAX_WORKERS=5 × 2 ThreadPool)
- FDR: timeout 옵션 없음 → socket.setdefaulttimeout() 사용
- pykrx: 거래일/OHLCV 조회 불안정 → WICS는 wiseindex.com API로 대체
- 네이버 수급: HTML 스크래핑 기반 (구조 변경 시 파싱 수정 필요)

## Key Patterns

- **폴백 체인**: 모든 데이터 소스에 다단계 폴백 구현
- **pickle 캐시**: 날짜별 캐시로 반복 수집 방지
- **증분 수집**: 이전 캐시 7일내 재사용, 신규 종목만 수집
- **ThreadPoolExecutor**: 병렬 수집 (FnGuide, OHLCV)
- **한글/영문 컬럼 호환**: indicators.py가 둘 다 지원
- **스크리너 독립 구조**: 각 스크리너가 자체 config/run/output 보유, 공통 모듈 재사용
- **수급 등급**: 외국인/기관 순매수 기반 A~D 등급, 시그널 신뢰도 조정
- **텔레그램 알림**: python-telegram-bot 비동기 전송, 4096자 자동 분할
