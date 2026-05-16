# HollyKR

> Trade Ideas Holly AI의 한국 시장 적응 버전 — 매일 KOSPI/KOSDAQ 시총 1,000억+ 종목을 30개 전략으로 스캔, AI 에이전트 팀이 분석, 텔레그램으로 시그널 송출.

**자동매매 X** — 시스템이 시그널과 분석 보고서를 제공하고, 사용자가 직접 매수/매도를 판단합니다.

---

## 핵심 컨셉 (Phase G-12)

```
1. 분기 5년 strict 검증 ALPHA pool (항상 ACTIVE 보존, 장기 안전 자산)
   - ma_convergence (CONSISTENT, Hold-out PF 1.30, Sharpe 0.45)
   - new_high_52w_approach (CONSISTENT, Hold-out PF 1.19, Sharpe 0.48)

2. 매일 60일 강조 동적 평가 — 풀 외 28개에서 시장 적응 Top 3 선정
   → ALPHA 2 + 시장 적응 3 = ACTIVE 5개

3. 매일 14:40 daily-scan — ACTIVE 5개로 시그널 발생

4. AI 에이전트 팀 분석:
   - Stage A: Python 정량 스코어러 (환각 0%)
   - Stage B: stock-analyst sub-agent (6단계 분석, 모든 시그널 평가)
   - 부서장: investment-orchestrator (CIO 역할, Top 10 결정)

5. 텔레그램 CIO 보고서 송출 (시장 진단 + 매수 추천 + Top 10)
```

---

> 📊 **시각 다이어그램**: [`ARCHITECTURE.md`](ARCHITECTURE.md) — 전체 파이프라인 / 전략 선정 / 청산 / 자동화 흐름을 mermaid로 정리 (GitHub 자동 렌더링)

## 6단계 운용 하네스

알고픽 인사이트: *"AI 투자 에이전트의 경쟁력은 모델이 아니라 하네스에서 나온다."*

| 단계 | 내용 | 구현 |
|---|---|---|
| 1. 정보 수집 | OHLCV 30+ 지표 + DART 공시 + FnGuide 재무 + 사업보고서 | `sub_agent_data_prep.py` |
| 2. 시장 해석 | 주도 테마 식별 + 자금 회전 + Kill Switch 평가 | 부서장 Phase G-10 |
| 3. 후보 선별 | Stage A 정량 + Stage B 6단계 깊은 분석 (모든 시그널) | `stock-analyst` |
| 4. 포지션 비중 | Top 10 + 분산 cap 5 + ALPHA 가산점 + 공석 허용 | `investment-orchestrator` |
| 5. 실행 조건 | 6단계 청산 (백테스트 = 실전 일치) | `exit_manager.py` |
| 6. 사후 복기 | 매주 토요일 3-시각 복기 + NAV vs KOSPI | `weekly_review.py` |

---

## AI 에이전트 시스템

Anthropic 공식 에이전트 가이드 형식 (YAML frontmatter + 마크다운 시스템 프롬프트, `PROACTIVELY use` 패턴).

```
investment-orchestrator (부서장, Opus 4.7) ── CIO 역할, 최종 의사결정
   │
   └─ stock-analyst (Stage B, Sonnet 4.6) × N개 병렬
        6단계 분석: 기업개요 / 재무 / 산업 / 모멘텀 / 리스크 / 종합

[보조 에이전트]
   memory-keeper · catalyst-analyst · portfolio-risk-analyst · devils-advocate · weekly-reviewer
```

### 사용자 명시 룰 (절대 준수)

1. 시그널 cutoff = 전략당 Top 20 (ALPHA pool 면제, 거래대금 cut X)
2. **Sub-agent는 모든 시그널 평가** (Top N으로 미리 자르지 X)
3. Top 10 분산은 부서장 단계 — 전략당 ≤5 강제
4. 부서장 = 의사결정자 (sub-agent와 다른 결정 가능)
5. 공석 허용 (강제로 Top 10 채우지 X)
6. 종목코드 KRX CSV 필수 검증 (ETF/우선주/SPAC/REIT 자동 제외)
7. 텔레그램 = CIO 보고서 양식 (시장 진단 + 매수 추천 + Top 10)

---

## 30개 전략 + ALPHA pool

| 카테고리 | 대표 전략 | RR 컷 |
|---|---|---|
| breakout | close_to_a_cross, **new_high_52w_approach**, box_range_watch | 2.5 |
| trend | tailwind, trend_play, **ma_convergence** | 2.5 |
| 시스템 트레이딩 거장 | clenow_momentum, donchian_breakout, aqr_tsmom, bollinger_squeeze | 2.5 |
| pullback / support | bullish_pullback, quarterback, horseshoe_up | 2.0 |
| mean_reversion | snap_back_long, bottom_breakout | 2.0 |
| legendary | darvas_box, weinstein_stage, minervini_trend, livermore_pivot | 2.5 |

**ALPHA pool** = 분기 5년 백테스트 (학습 2년 + Hold-out 3년 strict) 통과 전략. `nightly_selector` 듀얼 시간 척도(60일 0.5 / 180일 0.3 / 5년 메타 0.2)가 이 풀 안에서 평가.

---

## 실행 방법

```bash
pip install -r requirements.txt

# 매일 자동 분석 + 텔레그램 (Claude Code slash command)
/daily-orchestrate

# 매주 토요일 복기 (3-시각 sub-agent)
/weekly-review

# 자동 스캔 (평일 14:20 — GitHub Actions)
python -m scripts.screeners.holly_kr.run --auto --entry close --telegram

# 야간 ACTIVE 갱신 (평일 19:00)
python -m scripts.screeners.holly_kr.run --nightly --entry close

# 분기 5년 백테스트 → ALPHA pool 갱신
python -m scripts.screeners.holly_kr.backtest_5y --sample 1500 --workers 16
```

---

## 자동화

| 방식 | 트리거 | 동작 |
|---|---|---|
| **윈도우 작업 스케줄러** | 매일 14:40 KST | `cmd → .bat → claude -c "/daily-orchestrate"` (풀 자동화) |
| 윈도우 작업 스케줄러 | 매일 18:00 KST | `python --nightly` (ACTIVE 갱신) |
| GitHub Actions | 평일 14:20 KST | 단순 daily-scan + 텔레그램 (백업) |
| GitHub Actions | 분기 1일 | 5년 백테스트 → ALPHA pool 갱신 |

윈도우 스케줄러가 Claude Code CLI를 실행 → Claude Code가 `/daily-orchestrate` 슬래시 커맨드로 6단계 자동화 (PC 켜져 있을 때).

---

## 청산 6단계 우선순위 (백테스트 ↔ 실전 동일)

1. **갭다운**: 시초가 ≤ 손절가 → 시초가 즉시 청산
2. **손절**: 장중 저가 ≤ 손절가 → 손절가 청산
3. **목표 도달**: 장중 고가 ≥ 목표가 → 50% 부분익절 + 잔량 트레일링
4. **트레일링**: 보유 중 최고 종가 × 0.95 하향 이탈 → 잔량 청산
5. **First-day -3% 룰**: 진입 다음날 종가 ≤ entry × -3% → 다음날 시가 청산
6. **시간 청산**: `days_held >= hold_days_max` → 종가 청산

---

## 디렉토리 구조

```
scripts/screeners/holly_kr/   # HollyKR 본체 (스캐너/백테스트/전략 30개)
  run.py · scanner.py · backtest.py · backtest_5y.py
  nightly_selector.py · alpha_pool.py · exit_manager.py
  strategies/ · filters/

scripts/                      # 데이터 레이어
  ohlcv_data.py · investor_data.py · kis_*.py
  dart_api.py · fnguide_data.py
  sub_agent_data_prep.py · sub_agent_dart_fnguide.py
  stage_a_quick_score.py · weekly_review.py · nav_tracker.py

.claude/
  agents/        # stock-analyst · investment-orchestrator 등
  commands/      # /daily-orchestrate · /weekly-review
  skills/        # hollykr-rules-check (사용자 룰 자동 검증)

data/holly_kr/   # alpha_pool.json · 누적 로그 · memory/
```

---

## 데이터 소스 (글로벌 IP 호환)

| 데이터 | 소스 |
|---|---|
| OHLCV | FinanceDataReader (Yahoo) — 영구 캐시 |
| 종목 마스터 | KRX CSV (매월 갱신) → 네이버 → FDR 폴백 |
| 수급 (외인/기관) | 한국투자증권 KIS API |
| 재무 | FnGuide 스크래핑 (TTM/ROE/부채/CFO) |
| 공시 + 사업보고서 | DART OpenAPI |

---

## Phase 진화

- **Phase F**: 분기 5년 백테스트 + Hold-out 1년 → ALPHA pool 자동 생성
- **Phase G-6~9**: 5년 strict 검증, Stage A/B + 부서장 일원화, 6단계 하네스
- **Phase G-10~11**: 알고픽 인사이트 통합 (시장 테마 분석, 메모리 자동 로드, 매주 복기, NAV 추적)
- **Phase G-12**: 시간 최적화 (Stage B 모델/prompt 튜닝, 사업보고서 사전 수집)

---

## 정직성 원칙

- **Survivorship bias 보정**: 백테스트 PF × 0.75 (실전 추정)
- **DSR (Deflated Sharpe)**: multiple testing 보정
- **4년 → 5년 strict 변경**: 1년 hold-out은 강세장 운빨 가능 (tailwind ALPHA → 5년 PF 1.04로 약화 입증)
- **검증된 baseline 보존 > 약한 전략 강화**

---

## 라이선스 / 면책

본 시스템은 투자 참고용 분석 도구입니다. 모든 투자 결정과 책임은 사용자 본인에게 있습니다.
