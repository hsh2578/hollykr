# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HollyKR — Trade Ideas Holly AI의 한국 시장 적응 버전. 매일 KOSPI/KOSDAQ 시총 1,000억+ 종목을 30개 전략으로 스캔, 텔레그램으로 시그널 송출. **자동매매 X**, 사용자가 시그널 보고 직접 매수/매도 판단.

핵심 컨셉 (Phase G-5 하이브리드):
1. **분기 5년 strict 검증 ALPHA pool** (현재 2개: ma_convergence + new_high_52w_approach) — 항상 ACTIVE 보존
2. **매일 60일+180일+5년 메타 평가** — 풀 외 28개에서 점수 Top 8 선정 → 합쳐 ACTIVE 10개
3. **매일 14:20 daily-scan** — ACTIVE 10개로 시그널 발생 → 4 agents (Macro/Theme/Risk/Postmortem) 보정 → 텔레그램

## Run Commands

```bash
pip install -r requirements.txt

# 자동 모드 (실전, ACTIVE.json 사용) — 평일 14:20 GitHub Actions가 호출
python -m scripts.screeners.holly_kr.run --auto --entry close --telegram

# 야간 ACTIVE 갱신 (37개 전략 60일 평가 → Top 10 저장) — 평일 19:00
python -m scripts.screeners.holly_kr.run --nightly --entry close

# 단일 전략 스캔/디버깅
python -m scripts.screeners.holly_kr.run --strategy box_range_watch --entry close

# 워크포워드 백테스트 (4 윈도우, 결정적, CI + 추정 실전 PF 표시)
python -m scripts.screeners.holly_kr.backtest --walk-forward 4 --window-offset 60 --days 200 --sample 200 --entry close

# 단일 윈도우 백테스트 (Train/Test OOS)
python -m scripts.screeners.holly_kr.backtest --days 200 --sample 1000 --entry close --csv

# 그리드 서치 (특정 전략의 target_mult/stop_mult 최적화)
python -m scripts.screeners.holly_kr.grid_search --strategy box_range_watch \
  --target-mults 4,5,6,7 --stop-mults 1.5,2,2.5 --csv

# 분기 5년 종합 백테스트 (Phase F): walk-forward + Hold-out 1년 + ALPHA pool 자동 생성
python -m scripts.screeners.holly_kr.backtest_5y --sample 1500 --workers 16

# 데이터 수집·검증
python -m scripts.investor_data              # 수급(KIS) 테스트
python -m scripts.kis_sector_data --collect  # 전종목 섹터 수집 (7~10분)
python -m scripts.kis_price                  # KIS 실시간 현재가 테스트
python -m scripts.telegram_alert             # 텔레그램 송신 테스트
```

## Architecture

```
scripts/screeners/holly_kr/      # HollyKR 본체
  config.py                      # MIN_MARKET_CAP, RR/청산 상수, 포지션 사이징
  run.py                         # CLI: --auto/--nightly/--proven/--strategy
  scanner.py                     # 전략 순회 + 수급 + 레짐 + 중복 제거
  backtest.py                    # 백테스트 엔진 + 워크포워드 + bootstrap CI
  backtest_5y.py                 # Phase F 분기 5년 백테스트 + Hold-out 1년 + ALPHA pool
  grid_search.py                 # 전략 파라미터 그리드 서치 (Phase 8)
  alpha_pool.py                  # Phase F ALPHA 풀 save/load (분기 5년 검증)
  signal_model.py                # Signal dataclass (target/stop/RR/사이즈/사유)
  nightly_selector.py            # 듀얼 시간 척도 (60일+180일+5년 메타) Top N ACTIVE 선정
  active_strategies.py           # ACTIVE.json save/load
  exit_manager.py                # 실전 청산 (6단계 우선순위)
  survivorship_bias.py           # SURVIVORSHIP_BIAS_DISCOUNT = 0.75
  universe.py                    # 시총 1000억+ 유니버스 + 섹터 매핑
  indicators.py                  # ATR, RSI, RS Rating
  confidence.py                  # 신뢰도 = base × 수급 × 레짐 × 다중부스트
  output.py                      # 터미널/CSV/JSON
  strategies/                    # 37개 전략 + base.py
    base.py                      # _make_signal (RR게이트), _atr_target_stop (카테고리), _check_stage_2, _check_volume_with_climax
  filters/
    market_filter.py             # 5단계 레짐 + Kill Switch
    theme_filter.py              # 테마주/작전주 제외
    dedup.py                     # 3+ 전략 동시 매수 시 신뢰도 부스트
  agents/                        # Phase 10 룰 기반 4 에이전트 (LLM X)
    macro_agent.py               # Yahoo Finance 매크로 (KS11/KQ11/KRW=X/GSPC/CL=F) + Kill Switch
    theme_agent.py               # KIS 섹터 → 핫 테마 Top 3 + 알고픽 Top 3 발굴
    risk_agent.py                # 종목별 위험 평가 (시총/거래대금/ATR/변동폭) → VETO or multiplier
    postmortem_agent.py          # 매일 시그널 → 다음날 결과 추적 + 주간 금요일 리포트

scripts/                         # 데이터 레이어
  ohlcv_data.py                  # FDR/Yahoo + 영구 캐시 .cache/ohlcv/
  investor_data.py               # KIS primary, 네이버 fallback
  kis_sector_data.py             # KIS bstp_kor_isnm
  kis_price.py                   # KIS 실시간 현재가
  fnguide_data.py                # FnGuide 재무 (Magic Formula/Piotroski용)
  telegram_alert.py              # 강력/관심 + 3-tier (ALPHA/CONSISTENT/단기적응) + 현재가 + 사유

data/holly_kr/                   # Postmortem agent 누적 로그
  signals_log.csv                # 매일 송출 시그널
  trades_log.csv                 # 다음날 결과 추적
  weekly_report.csv              # 주간 요약
  alpha_pool.json                # Phase F 분기 5년 검증 ALPHA 풀

.github/workflows/
  holly-nightly.yml              # 평일 19:00 KST — ACTIVE 갱신
  holly-daily.yml                # 평일 14:20 KST — ACTIVE 로드 → 스캔
  holly-backtest.yml             # 평일 20:00 KST — 백테스트 (참고용, 수동만)
  holly-quarterly.yml            # 분기 1일 17:00 UTC — 5년 백테스트 → ALPHA pool 갱신
```

## 28개 전략 구성 (Phase G-6 정리: 5년 strict 거래 0건 14개 비활성화)

비활성화 14개 (strategy 파일 보존, scanner.py 제외): pushing_the_spring, float_on, staggering_volume, alpha_predators, strong_stock_pulling_back, the_continuation, got_dough, guiding_hand, nice_chart, the_vault, pulling_the_arrow, balloon_under_water, neo_breakout, neo_pullback



| 카테고리 | 전략 (수) | RR 컷 |
|---|---|---|
| breakout | close_to_a_cross, wake_up_call, engulfing, the_vault, float_on, bullish_trend_change, guiding_hand, pushing_the_spring, **new_high_52w_approach**, **box_range_watch** (10) | 2.5 |
| trend_following + trend | tailwind, trend_play, **ma_convergence** (3) | 2.5 |
| momentum | got_dough, neo_breakout, neo_pullback, the_continuation (4) | 2.25 |
| gap_momentum | volume_doesnt_lie, staggering_volume (2) | 2.5 |
| accumulation | alpha_predators, **volume_dry_up** (2) | 2.5 |
| multi_factor | nice_chart (1) | 2.25 |
| pullback | bullish_pullback, quarterback, strong_stock_pulling_back (3) | 2.0 |
| support_bounce | horseshoe_up, yesterday_hammer (2) | 2.0 |
| mean_reversion | balloon_under_water, snap_back_long, **bottom_breakout** (3) | 2.0 |
| reversal | pulling_the_arrow (1) | 2.0 |
| legendary | darvas_box, weinstein_stage, minervini_trend, livermore_pivot (4) | 2.5 |
| legendary (펀더, 비활성) | magic_formula, piotroski_fscore (2) | - |

**굵게 = Phase 7 신규 추가 (5개)**.

### 분기 5년 Hold-out 검증 ALPHA pool (`data/holly_kr/alpha_pool.json`)

마지막 갱신: 2026-05-08, sample 1500, **5년 strict (학습 2년 + Hold-out 3년) 검증 후**.

| 전략 | tier | Hold-out PF | Sharpe | 거래 | MDD |
|---|---|---|---|---|---|
| **ma_convergence** | CONSISTENT | 1.30 | 0.45 | 723 | -30% |
| **new_high_52w_approach** | CONSISTENT | 1.19 | 0.48 | 165 | -32% |

`nightly_selector` 듀얼 시간 척도가 이 풀 안에서만 평가. 풀 비어있으면 37개 전체로 fallback.

### 4년 baseline → 5년 strict 변경 이유

```
4년 baseline (학습 3년 + Hold-out 1년): ALPHA 1 + CONSISTENT 2
  - tailwind ALPHA PF 1.72 (Sharpe 1.50)
  - close_to_a_cross CONSISTENT PF 1.26
  - new_high_52w_approach CONSISTENT PF 1.36

5년 strict (학습 2년 + Hold-out 3년): ALPHA 0 + CONSISTENT 2
  - tailwind → PF 1.04, Sharpe 0.12 (강세장 운빨이었음 확인)
  - close_to_a_cross → PF 1.13, Sharpe 0.39 (MDD -54%로 컷)
  - new_high_52w_approach → PF 1.19, Sharpe 0.48 (생존)
  - ma_convergence → PF 1.30, Sharpe 0.45 (4년에선 거래 0건, 3년 hold-out에서 723거래로 부활)
```

5년 strict가 더 다양한 시장 환경 (강세 + 약세 + 횡보) 검증 → 진짜 robust 전략만 살아남음.

### 5년 strict에서 boundary (PF≥1.0 but 컷 — 추가 검토)

- close_to_a_cross: PF 1.13, S 0.39, MDD -54% (MDD 컷)
- tailwind: PF 1.04, S 0.12 (Sharpe 컷, 4년 ALPHA였음)

### Phase H 시스템 트레이딩 거장 정통 전략 (신규 7개, scanner.py PHASE_H_STRATEGIES)

학술/실무 정통 구현, 5년 strict (3년 hold-out)에서 모두 ALPHA pool 미진입 (한국 시장 노이즈):

| 전략 | 출처 | 5년 strict PF | Sharpe |
|---|---|---|---|
| `clenow_momentum.py` | Clenow "Stocks on the Move" | 0.90 | -0.20 |
| `donchian_breakout.py` | Donchian-Seykota | 0.89 | -0.25 |
| `aqr_tsmom.py` | Moskowitz TSMOM | 0.83 | -0.27 |
| `bollinger_squeeze.py` | Bollinger + Linda Raschke | 0.86 | -0.34 |
| `elder_triple_screen.py` | Elder "Trading for a Living" | 0.50 | -2.21 |
| `turn_of_month.py` | Lakonishok-Smidt + Ariel calendar effect | 0.82 | -0.56 |
| `adx_trend.py` | Wilder ADX + Carver | 0.82 | -0.43 |

**시사점**: 학술 검증된 정통 전략조차 5년 strict (3년 다양한 시장 환경) 한국 시장에선 통과 어려움. nightly_selector가 60일/180일 점수로 평가하여 최근 효과적이면 ACTIVE 선정 가능 (예: clenow_momentum, elder_triple_screen이 nightly Top 10 진입).

## Data Sources (글로벌 IP 호환)

| 데이터 | 소스 | 비고 |
|---|---|---|
| OHLCV | FinanceDataReader (Yahoo) | `.cache/ohlcv/ohlcv_cache.pkl` 영구 캐시 |
| 종목 마스터 | KRX → 네이버 → FDR 폴백 | FDR 폴백으로 글로벌 동작 |
| 수급 (외인/기관) | KIS `FHKST01010900` | OAuth 토큰, 네이버 폴백 |
| 섹터 | KIS `FHKST01010100` (bstp_kor_isnm) | WICS 캐시 폴백 |
| 현재가 | KIS `FHKST01010100` (stck_prpr) | 실시간 |
| 재무제표 | FnGuide 스크래핑 | Magic Formula/Piotroski만 |

## 진입 게이트 (`base.py::_make_signal`)

모든 전략은 `_make_signal()`을 통해 Signal 생성. 헬퍼가 자동 검증:
1. **risk 검증**: 손절폭 0.5% < |stop| ≤ 10% (비현실적이면 None)
2. **RR 게이트**: `target_pct / |stop_loss_pct| ≥ threshold` (카테고리별 2.0~2.5)
3. **포지션 사이징**: `position_size_pct = min(0.5% / |stop|, 10%)` 자동 계산

## 청산 6단계 우선순위 (`backtest.py` ↔ `exit_manager.py` 동일)

1. **갭다운**: 시초가 ≤ 손절가 → 시초가 즉시 청산 (`reason='gap_down'`)
2. **손절**: target 미도달 + 장중 저가 ≤ 손절가 → 손절가 청산
3. **목표가 도달**: 장중 고가 ≥ 목표가 → **50% 부분익절** (`partial_done=True`), 잔량 트레일링 모드 진입
4. **트레일링**: target 도달 후, 보유 중 최고 종가 × 0.95 하향 이탈 → 잔량 청산
5. **First-day -3% 룰** (Minervini): 진입 다음날 종가 ≤ entry × -3% → 다음날 시가 청산
6. **시간 청산**: `days_held >= hold_days_max` → 종가 청산

PnL = `0.5 × (partial_exit-entry)/entry + 0.5 × (final_exit-entry)/entry - ROUND_TRIP_COST(0.21%)` (50% 익절 발생 시)

## 카테고리별 ATR 배수 (`base.py::CATEGORY_ATR_PRESETS`)

`_atr_target_stop()`이 strategy.category 기반 자동 적용. 명시적 인자 우선.

| 카테고리 | target× | stop× | RR |
|---|---|---|---|
| breakout / trend_following / accumulation | 5.0 | 2.0 | 2.5 |
| momentum / multi_factor | 4.5 | 2.0 | 2.25 |
| gap_momentum | 4.0 | 1.6 | 2.5 |
| pullback / support_bounce / reversal | 3.0 | 1.5 | 2.0 |
| mean_reversion | 2.5 | 1.25 | 2.0 |
| legendary (전략별 개별) | 4-5 | 1.5-2 | 2.5 |

각 전략 코드에서 `target_pct, stop_loss_pct = self._atr_target_stop(df, ep)` 호출.
구조적 stop (예: Darvas 박스 하단)은 `max(structural, atr_stop, -8%)` 패턴으로 통합.

## Stage 2 거시 필터 (`base.py::_check_stage_2`)

Weinstein/Minervini 통합 룰. 4 모두 충족:
- 종가 > 200일 SMA AND > 50일 SMA
- 50일 SMA > 200일 SMA
- 200일 SMA 1개월 전 대비 우상향

적용: `close_to_a_cross`, `tailwind`, `wake_up_call`(200일선만 lite), `volume_doesnt_lie`(lite). 평균회귀/지지반등은 면제 (박스권 정석).

## 시장 레짐 + Kill Switch (`market_filter.py`)

5단계 레짐: 강한상승 / 상승저변동 / 상승고변동 / 횡보장 / 완만하락 / 강한하락

**Kill Switch 발동 조건 (3 중 1+)**:
1. KOSPI 5일 누적 ≤ -5%
2. KOSPI < 200일 SMA AND 200일 SMA 우하향 (Stage 4)
3. KOSPI 연율화 변동성 ≥ 35% (panic)

발동 시: 시그널 송출 동결 + 텔레그램 ⚠️ 경고 + "보유 손절 점검 권장".

## 동적 ACTIVE 선정 (`nightly_selector.py`) — Phase G-5 하이브리드

매일 19:00 KST 실행. 점수 = `0.4 × 60일 + 0.4 × 180일 + 0.2 × 5년 메타`.

**하이브리드 선정 로직** (사용자 의도: "ALPHA pool 고정 + 나머지 매일 평가"):
1. **ALPHA 풀은 항상 ACTIVE** (5년 strict 검증된 자산 보존)
   - 거래 0건이어도 포함 (분기 검증된 안전 자산)
2. **풀 외 38개 매일 동적 평가** → 점수순 Top (max_active - pool 수)
3. 합쳐 **Top 10 ACTIVE** (`.cache/active_strategies.json`)

점수 구성:
- 60일 + 180일 백테스트 점수: `0.25×WR + 0.30×PF_norm + 0.15×regime + 0.30×sample`
- 5년 메타: 분기 5년 백테스트 tier (ALPHA=1.0, CONSISTENT=0.7) + holdout PF

Top 30% = STRONG, 나머지 = WATCH (텔레그램 표시용 동적 분류).

## 분기 5년 백테스트 + ALPHA 풀 (Phase F)

**개념**: 분기에 1번, 5년 데이터로 워크포워드 + Hold-out 1년 종합 평가 → 진짜 ALPHA만 ALPHA pool에 저장. 일별 nightly_selector는 이 풀 안에서만 듀얼 시간 척도로 평가.

`backtest_5y.py` 흐름:
1. 5년 OHLCV (LOOKBACK_DAYS=1500) + 시총 상위 1500 종목
2. 학습 (3년) / Hold-out (1년 = 252거래일) 분리
3. 학습 윈도우 (4 윈도우 × 90일 슬라이딩) 각각 평가 — **정보 출력용** (게이트 X)
4. Hold-out 단독 평가로 tier 분류:
   - **ALPHA**: PF≥1.5 + Sharpe≥1.0 + 거래≥30 + MDD>-50%
   - **CONSISTENT**: PF≥1.0 + Sharpe≥0.3 + 거래≥15
   - **WEAK_HOLDOUT**: 그 외 (저장 X)
5. `data/holly_kr/alpha_pool.json` 자동 생성 → repo 커밋

**핵심 설계 결정** (시행착오 결과):
- 12 윈도우 × 9 그리드 평균 게이트 = 너무 빡빡 (검증 ALPHA도 탈락) → **단일 게이트**
- `walk_forward_optimize` window_end 기준 = today (X) → **learn_end** (실제 데이터 끝)
- 학습 게이트 (윈도우당 PF≥1.2 등) = 통계적 노이즈 → **제거** (Hold-out 단독)

## Phase 10 — 4 Agents (룰 기반, LLM X)

`run.py` 자동 모드에서 4개 agent 순차 실행 → 시그널 보정:

1. **Macro Agent** (`agents/macro_agent.py`): Yahoo Finance KS11/KQ11/KRW=X/GSPC/CL=F → Kill Switch + buying climax 검증 → confidence_multiplier
2. **Theme Agent** (`agents/theme_agent.py`): KIS 섹터 데이터 → 핫 테마 Top 3 + 콜드 테마 Top 3 → 종목 매칭 시 multiplier (HOT 1.30, WARM 1.15, COLD 0.70). 별도로 알고픽 Top 3 발굴.
3. **Risk Agent** (`agents/risk_agent.py`): 종목별 시총/거래대금/ATR/5일 변동폭 평가 → risk_level≥0.85 시 VETO (시그널 폐기)
4. **Postmortem Agent** (`agents/postmortem_agent.py`): 매일 nightly 직전 어제 시그널 → 오늘 결과 추적 (`signals_log.csv` → `trades_log.csv`). 매주 금요일 주간 리포트 텔레그램 송출.

## Schedule (GitHub Actions cron, 모두 KST 기준)

| Workflow | Cron (UTC) | 실제 (KST) | 동작 |
|---|---|---|---|
| holly-nightly.yml | `0 9 * * 1-5` | ~19:00 | 듀얼 시간 척도 평가 → ACTIVE 갱신 → commit |
| holly-daily.yml | `20 3 * * 1-5` | ~14:20 | ACTIVE 로드 → `--auto` 스캔 (4 agents 적용) → 텔레그램 |
| holly-backtest.yml | (수동 only) | — | 백테스트 (참고용, 자동 cron 폐기) |
| holly-quarterly.yml | `0 17 30 3,6,9,12 *` | 분기 1일 새벽 | 5년 backtest_5y → alpha_pool.json 갱신 → commit |

GitHub Actions cron은 SLA 없음 (피크타임 1-2시간 지연). 위 cron은 지연 보정용으로 앞당겨 설정됨.

## 핵심 설정 (`holly_kr/config.py`)

```python
MIN_MARKET_CAP = 1000             # 시총 1,000억 이상
LOOKBACK_DAYS = 1500              # OHLCV 5년 (분기 5년 백테스트 + 듀얼 60/180일 평가 커버)
ROUND_TRIP_COST = 0.0021          # 매매수수료 0.03% + 거래세 0.18%
TRAILING_STOP_PCT = 0.05          # 목표 도달 후 트레일링 5%
PARTIAL_PROFIT_PCT = 0.5          # 목표 도달 시 50% 익절
FIRST_DAY_LOSS_PCT = -0.03        # 진입 다음날 -3% 음봉 → 시가 청산
GAP_DOWN_EXIT_AT_OPEN = True      # 시초가 < 손절 → 시초가 청산
RR_THRESHOLD_DEFAULT = 2.0
RR_THRESHOLD_STRONG = 2.5         # breakout/trend
RISK_PER_TRADE_PCT = 0.005        # 자본 0.5% / 트레이드
MAX_POSITION_PER_STOCK = 0.10     # 종목당 캡 10%
```

## Survivorship Bias 정직성 (`survivorship_bias.py`)

`SURVIVORSHIP_BIAS_DISCOUNT = 0.75` (한국 시장 추정).
백테스트 출력 시 "추정 실전 PF = PF × 0.75" 자동 표시.
PIT 유니버스는 미완 (KRX OpenAPI 등록 또는 KIS API 통합 필요).

## Environment Variables (.env)

로컬 `.env` + 상위 통합 `.env` 병행 로드. 통합 경로: `{repo_parent}/../.env` (`C:\Users\hsh\Desktop\vibecoding\.env`).

```
KIS_APP_KEY
KIS_APP_SECRET
KIS_BASE_URL          # 모의: https://openapivts.koreainvestment.com:29443
                      # 실전: https://openapi.koreainvestment.com:9443
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

GitHub Actions: repo Settings → Secrets에 동일 키 등록.

## gh CLI 운영

```bash
# 수동 트리거
gh workflow run holly-nightly.yml --repo hsh2578/hollykr
gh workflow run holly-daily.yml --repo hsh2578/hollykr
gh workflow run holly-backtest.yml --repo hsh2578/hollykr

# 실행 목록/상태
gh run list --repo hsh2578/hollykr --limit 5

# 특정 job 로그
gh run view --job=<job-id> --repo hsh2578/hollykr --log
gh run view --job=<job-id> --repo hsh2578/hollykr --log-failed

# 시크릿 관리
gh secret list --repo hsh2578/hollykr
printf '%s' "value" | gh secret set NAME --repo hsh2578/hollykr
```

## 디버깅

```bash
# OHLCV 캐시 정체 점검
python -c "import pickle; d=pickle.load(open('.cache/ohlcv/ohlcv_cache.pkl','rb')); print(d['005930_500'].tail())"

# KIS 토큰 만료
cat .cache/.kis_token.json

# 유니버스 캐시 (당일)
python -c "import pickle; d=pickle.load(open('.cache/holly_universe_YYYY-MM-DD.pkl','rb')); print(len(d), d.head())"

# ACTIVE 전략 확인
cat .cache/active_strategies.json | python -m json.tool

# ALPHA pool 확인 (분기 5년 백테스트 결과)
cat data/holly_kr/alpha_pool.json | python -m json.tool

# Postmortem 누적 로그
cat data/holly_kr/signals_log.csv | tail -20
cat data/holly_kr/trades_log.csv | tail -20

# 시장 레짐 + Kill Switch 상태
python -c "from scripts.screeners.holly_kr.filters.market_filter import get_market_regime; r=get_market_regime(); print('regime:', r['regime'], 'kill:', r['kill_switch'], r.get('kill_reasons',[]))"

# 4 Agents 단독 테스트
python -m scripts.screeners.holly_kr.agents.macro_agent
python -m scripts.screeners.holly_kr.agents.theme_agent
python -m scripts.screeners.holly_kr.agents.risk_agent
python -m scripts.screeners.holly_kr.agents.postmortem_agent
```

## 과거 버그 (재발 주의)

- **OHLCV `_needs_update()` 주말 무한 정체**: 수정됨. 주말이면 무조건 `return False`였던 로직 → "예상 최신 거래일" 기준. 주말 전환 테스트 필수.
- **백테스트 ↔ 실전 청산 불일치**: 1주차 수정. 이전 백테스트는 손절/목표/시간만 → 실전(50%익절+트레일링+갭다운+first-day-3%) 결과와 다른 PF 산출 ("가짜 PF 4.64"). 지금은 backtest.py가 ExitManager와 동일.
- **OHLCV 길이 시프트로 인한 비결정성**: 4주차 수정. `len(df)` 동적 → `scan_end = len(df) - day_offset` 시프트로 같은 백테스트가 다른 결과. `end_date` 고정으로 해결.
- **Auto-extend target to RR**: 시도 후 롤백. 짧은 stop + 늘려진 target = 자주 손절 + 미도달 → PF<1. silent 전략은 silent 유지가 정답.
- **target_pct=0 버그** (livermore_pivot, minervini_trend): RR 게이트가 자동 폐기. ATR-based target으로 수정됨.
- **MDD 계산 버그**: `backtest.py:580` `cumulative = np.cumsum(pnls); drawdown = cumulative - peak`은 normalization 없이 PnL 단순 누적 → `MDD -1697%` 같은 비현실적 수치. 수정: `equity = 1 + cumsum(pnls); drawdown = (equity - peak) / peak; max(drawdown, -1.0)`. CONSISTENT 후보들이 MDD -50% 컷에 잘못 걸리는 원인이었음.
- **backtest_5y.py KeyError 'holdout_min_pf'**: ALPHA_CRITERIA 단순화 (Hold-out 단독 평가) 후 `holdout_validate`의 `pass` 필드 계산이 deleted 키 참조. 6개 전략 ERROR로 평가 누락. ALPHA_CRITERIA에 legacy alias 추가로 해결.
- **단순 룰 추가형 보완 vs 6요소 통합 재설계**: engulfing/snap_back_long/horseshoe_up에 (a) 50일 SMA + 거래량 보완 시도 → 큰 변화 X, (b) tailwind 패턴 (Stage 2 + multi-confirmation + ATR) 6요소 재설계 시도 → CONSISTENT 0개로 baseline 대비 후퇴. 두 방식 모두 git checkout 롤백. 교훈: **검증된 baseline 보존이 약한 전략 강화보다 우선**, 룰 변경은 단일 전략 sanity check 후 신중히.
- **run.py nightly mode PHASE1+PHASE2 only 버그**: Phase G-6 fix. PHASE7 (ma_convergence 등) + PHASE_H (clenow 등) 누락 평가. 결과: ALPHA pool 2개 (ma_convergence, new_high_52w_approach)가 ACTIVE.json에 안 들어감. 수정: `from scanner import ALL_STRATEGIES`. 또한 OHLCV 220일 → 500일 (180일 lookback 위함), sample 200 → 1500 (Phase F 정통).
- **4년 baseline (1년 hold-out)이 강세장 운빨**: tailwind PF 1.72 → 5년 strict (3년 hold-out)에서 PF 1.04로 약화. box_range_watch (이전 워크포워드 ALPHA)도 5년 PF 0.61. 결론: 1년 hold-out은 한국 시장에서 충분 X, 3년 hold-out 권장 (학습 2년 + Hold-out 3년 = 5년 데이터 활용 극대화).

## Known Limitations

- Phase 3 INTRADAY 12개 전략: 분봉 필요, 미구현
- Magic Formula / Piotroski: 분기 리밸런싱이라 일별 스캐너에선 비활성
- FnGuide HTML 변경 시 파싱 수정 필요
- 백테스트는 OHLCV만 사용 (실시간 신뢰도 부스트의 수급 데이터는 historical 미수집)
- PIT 유니버스 미구축 → Survivorship bias 보정 계수 0.75로 대체

## 단일 전략 백테스트

```bash
python -m scripts.screeners.holly_kr.backtest --strategy box_range_watch --days 200 --sample 200 --entry close --csv
python -m scripts.screeners.holly_kr.backtest --strategy box_range_watch --walk-forward 4 --window-offset 60 --days 200 --sample 200 --entry close
```
