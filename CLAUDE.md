# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HollyKR — Trade Ideas Holly AI의 한국 시장 적응 버전. 매일 KOSPI/KOSDAQ 시총 1,000억+ 종목을 37개 전략으로 스캔, 텔레그램으로 시그널 송출. **자동매매 X**, 사용자가 시그널 보고 직접 매수/매도 판단.

핵심 컨셉: **37개 전략 모두 영구 후보**. 매일 60일 성과 기반으로 점수 매겨 Top 10 ACTIVE 선정 → 그 전략들만 시그널. 영구 제외 X, 매일 동적 로테이션. (Trade Ideas Holly의 "매일 밤 70+ 전략 평가 → 다음날 적용" 철학)

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
  grid_search.py                 # 전략 파라미터 그리드 서치 (Phase 8)
  signal_model.py                # Signal dataclass (target/stop/RR/사이즈/사유)
  nightly_selector.py            # 60일 성과 평가 → Top N ACTIVE 선정
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

scripts/                         # 데이터 레이어
  ohlcv_data.py                  # FDR/Yahoo + 영구 캐시 .cache/ohlcv/
  investor_data.py               # KIS primary, 네이버 fallback
  kis_sector_data.py             # KIS bstp_kor_isnm
  kis_price.py                   # KIS 실시간 현재가
  fnguide_data.py                # FnGuide 재무 (Magic Formula/Piotroski용)
  telegram_alert.py              # 강력/관심 + 현재가 + 사유 + 권장 포지션

.github/workflows/
  holly-nightly.yml              # 평일 19:00 KST — ACTIVE 갱신
  holly-daily.yml                # 평일 14:20 KST — ACTIVE 로드 → 스캔
  holly-backtest.yml             # 평일 20:00 KST — 백테스트 (참고용)
```

## 37개 전략 구성

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

### 워크포워드 검증된 ALPHA (PF 95% CI 하한 > 1.0)

| 전략 | 누적 거래 | PF | 95% CI | 추정 실전 PF (×0.75) | 윈도우 |
|---|---|---|---|---|---|
| **box_range_watch** ⭐ | 203 | 2.27 | [1.65, 3.11] | 1.70 | 4/4 |
| close_to_a_cross | 80 | 1.89 | [1.06, 3.22] | 1.42 | 3/4 |
| wake_up_call | 330 | 1.55 | [1.17, 2.03] | 1.16 | 4/4 |

`run.py::WORKFLOW_PROVEN`이 위 3개. ACTIVE.json 없을 때 fallback으로 사용.

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

## 동적 ACTIVE 선정 (`nightly_selector.py`)

매일 19:00 KST 실행:
1. 37개 전략 모두 60일 백테스트
2. `composite_score = 0.25×WR + 0.30×PF_norm + 0.15×regime_weight + 0.30×sample_norm` 계산
3. 거래 발생 전략 점수순 → **Top 10 ACTIVE**
4. 부족하면 거래 없는 전략도 추가하여 min_active(5) 보장
5. `.cache/active_strategies.json` 저장 → repo 커밋

Top 30% = STRONG, 나머지 = WATCH (텔레그램 표시용 동적 분류).

## Schedule (GitHub Actions cron, 모두 KST 기준)

| Workflow | Cron (UTC) | 실제 (KST) | 동작 |
|---|---|---|---|
| holly-nightly.yml | `0 9 * * 1-5` | ~19:00 | 37개 평가 → ACTIVE 갱신 → commit |
| holly-daily.yml | `20 3 * * 1-5` | ~14:20 | ACTIVE 로드 → `--auto` 스캔 → 텔레그램 |
| holly-backtest.yml | `0 11 * * 1-5` | ~20:00 | 백테스트 (참고용) |

GitHub Actions cron은 SLA 없음 (피크타임 1-2시간 지연). 위 cron은 지연 보정용으로 앞당겨 설정됨.

## 핵심 설정 (`holly_kr/config.py`)

```python
MIN_MARKET_CAP = 1000             # 시총 1,000억 이상
LOOKBACK_DAYS = 500               # OHLCV 조회 (200일 SMA 커버)
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

# 시장 레짐 + Kill Switch 상태
python -c "from scripts.screeners.holly_kr.filters.market_filter import get_market_regime; r=get_market_regime(); print('regime:', r['regime'], 'kill:', r['kill_switch'], r.get('kill_reasons',[]))"
```

## 과거 버그 (재발 주의)

- **OHLCV `_needs_update()` 주말 무한 정체**: 수정됨. 주말이면 무조건 `return False`였던 로직 → "예상 최신 거래일" 기준. 주말 전환 테스트 필수.
- **백테스트 ↔ 실전 청산 불일치**: 1주차 수정. 이전 백테스트는 손절/목표/시간만 → 실전(50%익절+트레일링+갭다운+first-day-3%) 결과와 다른 PF 산출 ("가짜 PF 4.64"). 지금은 backtest.py가 ExitManager와 동일.
- **OHLCV 길이 시프트로 인한 비결정성**: 4주차 수정. `len(df)` 동적 → `scan_end = len(df) - day_offset` 시프트로 같은 백테스트가 다른 결과. `end_date` 고정으로 해결.
- **Auto-extend target to RR**: 시도 후 롤백. 짧은 stop + 늘려진 target = 자주 손절 + 미도달 → PF<1. silent 전략은 silent 유지가 정답.
- **target_pct=0 버그** (livermore_pivot, minervini_trend): RR 게이트가 자동 폐기. ATR-based target으로 수정됨.

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
