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

# 백테스트 (단일 윈도우 Train/Test OOS 분할)
python -m scripts.screeners.holly_kr.backtest --days 200 --sample 1000 --entry close --csv

# 워크포워드 백테스트 (4 윈도우, 결정적 + 신뢰구간)
python -m scripts.screeners.holly_kr.backtest --walk-forward 4 --window-offset 60 --days 200 --sample 200 --entry close --csv

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

## 실전 전략 (3주차 검증 — 200일/200종목, 진짜 PF)

**통계적으로 유의미한 PASS (Test 거래수 30+)**
- **wake_up_call** (Test PF 1.25, 40건, +26.1%) ⭐ 안정적
- **trend_play** (Test PF 1.35, 42건, +26.7%) ⭐ 추세 알파

**작은 표본 PASS (참고)**
- weinstein_stage (PF 1.93, 2건)
- bullish_pullback (PF 2.65, 4건)
- yesterday_hammer (1건, artifact)

**OVERFIT (Train PASS / Test FAIL)**
- darvas_box: Train PF 2.05 → Test 0.67, 67건. 박스 돌파 자체는 작동, OOS 약함
- close_to_a_cross: Train 2.93 → Test 0.28. Stage 2 + 거래량 컷 조합이 너무 강함
- volume_doesnt_lie: Train 1.8 → Test 0.86. 갭 모멘텀 OOS 변동성
- quarterback: Train 1.3 → Test 0.67. 풀백 timing 차이

**FAIL**: engulfing, horseshoe_up, bullish_trend_change, tailwind

**시그널 없음 (19개)** — RR 게이트 정상 작동. 진입 조건 너무 엄격(VCP 등) 또는 구조적 stop+small target = RR 미달 → 폐기 (작동하는 안전장치)

### Week 3 학습 사항
- "Auto-extend target to RR threshold" 시도 실패: 9603 거래 / 다수 PF<1 → 롤백
- 짧은 stop + 늘려진 target = 자주 손절 + 미도달 → 손해
- 결론: silent 전략은 silent 유지가 정답. 신규 알파는 새 전략 추가로 확보

## 4주차 — 통계 인프라 (퀀트 정직성)

### 비결정성 해결 (`backtest.py::_load_universe_ohlcv`)
- `end_date` 파라미터 추가. OHLCV cache가 자라도 동일 백테스트 = 동일 결과
- 기존 문제: `len(df)` 동적 → `scan_end = len(df) - day_offset` 시프트 → 결과 변동
- 해결: 진입 시 `df = df[df.index <= end_date]` 슬라이싱

### 워크포워드 (`backtest.py::run_walk_forward`)
- 4 윈도우 × 200일 × 60일 슬라이딩
- 각 윈도우는 동일 OHLCV 풀에서 다른 end_date로 실행 → 시간대 다양성
- CLI: `--walk-forward 4 --window-offset 60`

### PF 신뢰구간 (`backtest.py::bootstrap_pf_ci`)
- Trade-level PnL 부트스트랩 1000회 (deterministic seed=42)
- 95% CI 하한 + 상한 산출
- `pf_significant = pf_ci_lower > 1.0` → 통계적 진짜 알파

### PASS 기준 강화 (3단계)
- **ALPHA**: Test 거래 ≥ 30 AND 승률 ≥ 40% AND PF 95% CI 하한 > 1.0 (진짜 알파)
- **PASS**: Test 거래 ≥ 30 AND 승률 ≥ 40% AND PF ≥ 1.2 (점추정 통과, 통계적 의미 X 가능)
- **OVERFIT**: Train PASS / Test FAIL
- **FAIL**: 그 외

### 워크포워드 종합 판정 (4 윈도우)
- **ALPHA**: 4중 3+ 윈도우 PASS AND 누적 거래 30+ AND 누적 PF 95% CI 하한 > 1.0
- **CONSISTENT**: 4중 3+ 윈도우 PASS (통계적 미만)
- **BORDERLINE**: 누적 PF ≥ 1.2 but 일관성 부족
- **FAIL**: 그 외

### 포지션 사이징 (`base.py::_make_signal`)
- Vol-target: `position_size_pct = min(RISK_PER_TRADE / |stop_loss_pct|, MAX_POSITION_PER_STOCK)`
- `RISK_PER_TRADE_PCT = 0.5%` (자본 대비)
- 예: stop -3% → 포지션 = min(0.5/3, 10) = 약 17% (캡 10% 적용)
- 모든 시그널이 동일 위험 노출 → Sharpe ratio 비교 가능

## Phase 6 — 시장 레짐 + Kill Switch (안전 장치)

### 5단계 레짐 분류 (`market_filter.py::get_market_regime`)
- 강한상승: KOSPI/KOSDAQ 둘 다 50일선 위 + 5일 +3%+
- 상승장_저변동: 둘 중 하나 이상 50일선 위 + 변동성 <20%
- 상승장_고변동: 둘 중 하나 이상 50일선 위 + 변동성 ≥20%
- 횡보장: 기본
- 완만하락: 둘 다 50일선 아래 + 변동성 ≥20%
- 강한하락: Kill Switch 발동 시

### Kill Switch 조건 (3 중 1+ 발동)
1. KOSPI 5일 누적 -5% 이상
2. KOSPI < 200일 SMA AND 200일 SMA 우하향 (Stage 4)
3. KOSPI 연율화 변동성 ≥35% (panic mode)

### 동작
- 평일 14:20 daily-scan 직전 레짐 점검
- Kill Switch 활성 → 시그널 송출 동결
- 텔레그램에 "⚠️ Kill Switch 발동" + 사유 + "보유 포지션 손절 점검 권장" 전송

## Phase 7 — 신규 5개 전략 (총 32 → 37개)

stock-screener-kr 사이트 전략 한국화 + Phase 5 인프라 통합. 학술/실증 기반 손절 적용:

| 전략 | 카테고리 | 핵심 조건 | 손절 정석 |
|---|---|---|---|
| **ma_convergence** | trend_following | 주봉 10>20>60 정배열 + 100주봉 신고가 30주 내 + 일봉 이격도 ≤5% | 마지막 수축 저점 -0.5% (Minervini VCP) |
| **new_high_52w_approach** | breakout | 52주 고가 5% 이내 미돌파 + 저항선 20일+ + **하루 +5~25%** | swing low + 저항선 -3% (Earn2Trade) |
| **bottom_breakout** | mean_reversion | 12점 점수제 (3 필수 + 6 점수 항목, 7점+ 통과) | 200일 SMA -1% + swing low (Weinstein) |
| **volume_dry_up** | accumulation | 거래량 ×4 +8% 양봉 → 3-8일 후 거래량 ×40% 이하 | dry-up 저점 + 폭발봉 시가 -1% (Wyckoff) |
| **box_range_watch** | breakout | 60일 횡보 + 저항선 2회+ 터치 + 후반 거래량 dry-up + 박스 상단 ±3% 근접 | 박스 하단 -0.3% (Darvas) |

## Phase 7 워크포워드 결과 (37 전략, 4 윈도우, 200일/200종목)

### 통계적 ALPHA (PF 95% CI 하한 > 1.0)
1. **wake_up_call**: 4/4, 330건, PF 1.55, CI [1.17, 2.03]
2. **close_to_a_cross**: 3/4, 80건, PF 1.89, CI [1.06, 3.22]
3. **box_range_watch**: 4/4, 203건, **PF 2.27, CI [1.65, 3.11]** ⭐ **신규 최강**

### BORDERLINE (CI는 좋으나 윈도우 일관성 2/4)
- ma_convergence: PF 1.56, CI [1.09, 2.24]
- new_high_52w_approach: PF 1.84, CI [0.79, 3.67] (표본 작음)

### 핵심 발견
- 사이트 전략 추가가 진짜 알파(box_range_watch) 발굴 → 추가 가치 입증
- 정석 손절 (Minervini/Wyckoff/Weinstein/Darvas) 적용 효과: 안정성 ↑
- volume_dry_up은 단일 윈도우 PF 1.39였으나 4윈도우 누적 1.1 → **워크포워드가 fake alpha 잡아냄**

## Phase 8 — 그리드 서치 인프라 (`grid_search.py`)

ALPHA 전략의 (target_mult, stop_mult) 경험적 최적화:
```bash
python -m scripts.screeners.holly_kr.grid_search --strategy box_range_watch \
  --target-mults 4,5,6,7 --stop-mults 1.5,2,2.5 --csv
```
- Monkey-patch로 `_atr_target_stop` 오버라이드
- 각 조합 워크포워드 4 윈도우 검증 (OOS)
- 결과: ALPHA 컷 (PF CI 하한 > 1.0) 적용된 최적 조합 자동 식별

### box_range_watch 그리드 서치 결과 (12 조합)
| 순위 | target×ATR | stop×ATR | RR | 거래 | PF | CI 하한 | 윈도우 |
|---|---|---|---|---|---|---|---|
| 1 | 7 | 2.5 | 2.8 | 245 | 2.46 | 1.82 | 3/4 |
| **3 (현재 default)** | **5** | **2** | **2.5** | **203** | **2.27** | **1.69** | **4/4** ⭐ |

**결론**: 현재 카테고리 preset (breakout 5×/2×)이 경험적으로 최적. 윈도우 일관성 4/4 = 최고. 변경 불필요.

## Phase 9 — Survivorship Bias 보정 (정직성)

### 한계 인지
- 현재 유니버스: '오늘 시점' 시총 1,000억+ 종목 = 살아남은 풀
- 200일 전 상폐 종목 누락 + 당시 시총 작던 종목이 운 좋게 포함
- **결과: PF가 실전보다 약 20-30% 부풀려져 있음**

### 보정 (`survivorship_bias.py::SURVIVORSHIP_BIAS_DISCOUNT = 0.75`)
- 백테스트 출력에 "추정 실전 PF" 자동 표시 (PF × 0.75)
- ALPHA 판정도 보정 후 의미 있는지 재해석:
  - wake_up_call: PF 1.55 → 추정 1.16 (여전히 알파)
  - close_to_a_cross: PF 1.89 → 추정 1.42
  - **box_range_watch**: PF 2.27 → 추정 1.70 (보정 후에도 가장 강력)

### 향후 작업 (PIT 유니버스 — 미완)
- pykrx historical은 KRX_ID/KRX_PW 필요 (미공개)
- KRX OpenAPI 등록 또는 KIS API 활용 검토 필요

## 5주차 — 동적 ACTIVE 선정 (사용자 컨셉)

### 핵심 철학
**32개 전략 모두 영구 보존**. 매일 60일 평가 → 점수 기반 Top 10 선정 → 그날의 ACTIVE.
- 어제 부진한 전략이 오늘 1위일 수 있음
- 영구 제외 X
- 시장 레짐에 따른 자연스러운 로테이션

### 데이터 흐름
```
평일 19:00 KST  →  holly-nightly.yml  →  32개 전략 모두 60일 평가
                                       →  Top 10 ACTIVE 선정
                                       →  data/holly_kr/active/active_strategies.json commit

평일 14:20 KST  →  holly-daily.yml    →  ACTIVE.json 로드 → --auto 모드 스캔
                                       →  ACTIVE 상위 30% = STRONG, 나머지 = WATCH (동적)
                                       →  텔레그램 송출

금요일 21:00 KST → holly-backtest.yml  →  주간 워크포워드 (참고용 통계 추적)
```

### 점수 공식 (`nightly_selector.py::_calc_metrics`)
```
composite_score = 0.25 × win_rate
                + 0.30 × normalized_PF      (캡 3.0)
                + 0.15 × regime_weight      (0.4~1.3)
                + 0.30 × normalized_sample  (sqrt(N)/10)
```
- 표본 크기 가중을 0.30으로 강화 (이전 0.20)
- sqrt 정규화 (log보다 표본 큰 전략 우대)

### ACTIVE 선정 로직
1. 32개 전략 모두 60일 백테스트
2. 거래 발생 전략 → 점수 순 정렬
3. Top max_active(10) 선정 (passed 무관)
4. 너무 적으면 거래 없는 전략도 추가하여 min_active(5) 보장
5. JSON 저장 → 다음날 daily-scan 사용

### 동적 STRONG/WATCH 분류 (`run.py --auto`)
- ACTIVE 상위 30% = STRONG (최소 2개)
- 나머지 = WATCH
- 어제는 quarterback이 STRONG, 오늘은 wake_up_call이 STRONG일 수 있음

### 호환성 (FALLBACK, Phase 7 갱신)
- ACTIVE.json이 없으면 (워크플로 첫 실행 등) `WORKFLOW_PROVEN + FALLBACK_WATCH` 사용
- **WORKFLOW_PROVEN = ['wake_up_call', 'close_to_a_cross', 'box_range_watch']** (진짜 ALPHA 3개)
- FALLBACK_WATCH = 10개 (ma_convergence, new_high_52w_approach + 8 BORDERLINE)

### 검증 (2026-05-05 nightly 실행 결과)
ACTIVE Top 10:
1. **bullish_pullback** Score=0.636 [PASS] (WR 50%, PF 2.86)
2. **wake_up_call** Score=0.603 [PASS] (WR 45.8%, PF 1.60, 48건) ← 워크포워드 ALPHA
3. darvas_box Score=0.571 (75건)
4. **quarterback** Score=0.549 [PASS]
5-10. trend_play, volume_doesnt_lie, horseshoe_up, close_to_a_cross, yesterday_hammer, weinstein_stage

워크포워드 ALPHA 2개 중 wake_up_call은 안정적으로 상위, close_to_a_cross는 60일 단기 평가에서 #8 → 단일 윈도우 노이즈 영향. 매일 ACTIVE가 변동하는 것 자체가 컨셉의 강점 (시장 적응).

## 핵심 설정

- 유니버스: 시총 1,000억+, 보통주, 스팩/리츠 제외 → 약 1,500종목
- 거래비용: 0.21% (매수 0.015% + 매도 0.015% + 세금 0.18%)
- 슬리피지: 대형주 0.1%, 중형주 0.2%, 소형주 0.5%
- ATR 목표/손절: 목표 ATR × 3, 손절 ATR × 2
- 신뢰도: base × 수급(1.0~1.3) × 레짐 × 다중부스트(1.1~1.25), 상한 0.95
- 수급 등급: S(동반매도→동반매수 전환) / A(동반매수+가속) / A-(동반매수) / B / C / D
- **시그널 캡: 강력 우선 최대 5개 + 관심으로 채워 총 10개**

## 진입/청산 규칙 (1주차 업그레이드: 백테스트↔실전 일치 + RR 게이트)

### 진입 게이트 (`base.py::_make_signal`)
- **RR ≥ 2.0** (default): 일반 전략. `(target_pct) / (-stop_loss_pct) < 2.0` → 시그널 폐기
- **RR ≥ 2.5** (`STRONG_RR_CATEGORIES = {'breakout', 'trend_following'}`): 추세/돌파 전략
- 검증 위치: `_make_signal` 헬퍼에서 자동 적용. 모든 전략이 통과해야 Signal 객체 반환

### 청산 규칙 (백테스트 = 실전 ExitManager)
백테스트 엔진(`backtest.py::_simulate_strategy`)과 실전 청산이 동일 우선순위 적용:
1. **갭다운**: 시초가 ≤ 손절가 → 시초가 즉시 청산 (`reason='gap_down'`)
2. **손절**: target 미도달 상태에서 장중 저가 ≤ 손절가 → 손절가 청산
3. **목표가 도달**: 장중 고가 ≥ 목표가 → **50% 익절** (`partial_done=True`), 잔량은 트레일링
4. **트레일링**: target 도달 후, max_close × (1 − 0.05) 하향 이탈 → 잔량 청산
5. **First-day -3% 룰** (Minervini): 진입 다음날(`days_held=1`) 종가 -3% 이하 → 그 다음날 시가 청산
6. **시간 청산**: `days_held >= hold_days_max` → 종가 청산

### 50% 익절 PnL 계산
```
total_pnl = 0.5 × (partial_exit - entry)/entry
          + 0.5 × (final_exit - entry)/entry
          - ROUND_TRIP_COST(0.21%)
```

### 관련 config 상수 (`holly_kr/config.py`)
- `TRAILING_STOP_PCT = 0.05`
- `PARTIAL_PROFIT_PCT = 0.5`
- `FIRST_DAY_LOSS_PCT = -0.03`
- `GAP_DOWN_EXIT_AT_OPEN = True`
- `RR_THRESHOLD_DEFAULT = 2.0`
- `RR_THRESHOLD_STRONG = 2.5`

## 카테고리별 ATR 배수 (2주차 — `base.py::CATEGORY_ATR_PRESETS`)

전략 카테고리에 따라 `_atr_target_stop()`이 자동으로 적절한 배수 적용. 명시적 인자(`target_multiple`, `stop_multiple`) 전달 시 그 값 우선.

| 카테고리 | target × ATR | stop × ATR | RR | 적용 전략 |
|---|---|---|---|---|
| breakout | 5.0 | 2.0 | 2.5 | close_to_a_cross, wake_up_call, engulfing, the_vault, ... (8) |
| trend_following / trend | 5.0 | 2.0 | 2.5 | tailwind, trend_play |
| momentum | 4.5 | 2.0 | 2.25 | got_dough, neo_breakout, neo_pullback, the_continuation |
| gap_momentum | 4.0 | 1.6 | 2.5 | volume_doesnt_lie, staggering_volume |
| accumulation | 5.0 | 2.0 | 2.5 | alpha_predators |
| multi_factor | 4.5 | 2.0 | 2.25 | nice_chart |
| pullback | 3.0 | 1.5 | 2.0 | bullish_pullback, quarterback, strong_stock_pulling_back |
| support_bounce | 3.0 | 1.5 | 2.0 | horseshoe_up, yesterday_hammer |
| mean_reversion | 2.5 | 1.25 | 2.0 | balloon_under_water, snap_back_long |
| reversal | 3.0 | 1.5 | 2.0 | pulling_the_arrow |
| legendary (개별) | 5.0 / 4.0 | 2.0 / 1.5 | 2.5 / - | darvas_box, weinstein_stage, minervini, livermore_pivot |

## Stage 2 거시 필터 (`base.py::_check_stage_2`)

Weinstein/Minervini/O'Neil 통합 룰. 4가지 모두 충족:
1. 종가 > 200일 SMA
2. 종가 > 50일 SMA
3. 50일 SMA > 200일 SMA
4. 200일 SMA 1개월 전 대비 우상향

**적용 전략**: close_to_a_cross, tailwind (full Stage 2), wake_up_call, volume_doesnt_lie (200일선 위만 = lite). 평균회귀/지지반등은 면제 (박스권 매매가 정석).

## 거래량 climax cap (`base.py::_check_volume_with_climax`)

`min_mult ≤ 거래량 / 50일평균 ≤ max_mult` 구간만 통과. 상한 초과 = volume climax = 천장 신호 → 폐기.

| 카테고리 | min | max | 사유 |
|---|---|---|---|
| breakout | 1.5 | 5.0 | Minervini 기준 |
| trend_following | 1.3 | 5.0 | 추세 진입 노이즈 컷 |
| gap_momentum | 2.0 | 6.0 | 갭 강도 검증 |

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
- **백테스트 ↔ 실전 청산 불일치 (1주차에 수정)**: 이전 백테스트는 손절/목표/시간만 단순 적용 → 실전(50% 익절+트레일링+갭다운+first-day -3%) 결과와 다른 PF 산출 ("가짜 PF 4.64" 문제). 이제 backtest.py가 ExitManager와 동일 6단계 우선순위 적용. PF 떨어지지만 진짜 숫자.
- **RR 게이트 도입 후 시그널 급감**: ATR×3 / ATR×2 = RR 1.5라서 RR 2.5 컷에 다수 폐기. 정상 동작이며, Week 2에서 전략별 target/stop 비율 재설계 (예: trend는 ATR×4/2 = RR 2.0, breakout은 ATR×5/2 = RR 2.5)로 회복 예정.

## Known Limitations

- Phase 3 INTRADAY 12개 전략: 분봉 필요, 미구현
- Magic Formula / Piotroski: 스캐너 미연동 (별도 분기 리밸런싱 필요)
- FnGuide 스크래핑: HTML 변경 시 파싱 수정 필요
- 백테스트는 과거 수급 데이터 없이 OHLCV만 사용 (실시간 신뢰도 부스트와 다름)
