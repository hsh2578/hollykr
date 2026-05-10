# HollyKR Sub-Agent System — 통합 가이드

7개 Claude AI 서브에이전트 + 4개 Python 룰 에이전트 (HollyKR 시스템 내장).

## 시스템 다이어그램

```
┌──────────────────────────────────────────────────────────────┐
│  [HollyKR Python — 매일 자동, 14:20]                          │
│  30 전략 × 1500 종목 → 시그널 → 4 룰 에이전트 보정 → Top 9-10  │
└──────────────────────────────────────────────────────────────┘
                              ↓
                    [후보 풀 (candidate pool)]
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  [Claude AI 서브에이전트 — 7개, 사용자 요청 시 또는 자동]      │
│                                                                │
│  Phase 1 (병렬): memory-keeper                                 │
│    → 과거 사례 + 회피 패턴 + 현재 philosophy                    │
│                                                                │
│  Phase 2 (병렬): stock-analyst × N + catalyst-analyst × N       │
│    → 개별 6단계 분석 + DART/뉴스 카탈리스트                      │
│                                                                │
│  Phase 3 (단일): portfolio-risk-analyst                         │
│    → VaR + correlation + cvxpy QP                               │
│                                                                │
│  Phase 4 (단일): devils-advocate                                │
│    → 합의 도전 (Inversion/Premortem/가정/OOS)                  │
│                                                                │
│  Phase 5 (orchestrator): investment-orchestrator               │
│    → 4팩터 Z-Score → Top 3/5/10 + BEST PICK                    │
│                                                                │
│  [매주 금] weekly-reviewer                                      │
│    → 칭찬/비판/시장 → philosophy_v{N+1} → memory-keeper         │
└──────────────────────────────────────────────────────────────┘
```

## 7개 서브에이전트 요약

| 에이전트 | 역할 | model | tools |
|---|---|---|---|
| **stock-analyst** | 개별 종목 6단계 분석 | sonnet | Read, Bash, WebSearch, WebFetch, Grep |
| **catalyst-analyst** | DART/뉴스/이벤트 deep dive | sonnet | Bash, Read, WebSearch, WebFetch, Grep |
| **portfolio-risk-analyst** | VaR + cvxpy QP | sonnet | Bash, Read, Write, Grep |
| **memory-keeper** | 알고픽 기억 시스템 | sonnet | Read, Write, Glob, Grep |
| **weekly-reviewer** | 알고픽 복기 + 철학 진화 | opus | Read, Write, Bash, Glob, Grep |
| **devils-advocate** | Bridgewater 그룹사고 방지 | opus | Read, WebSearch, WebFetch, Grep |
| **investment-orchestrator** | Top N 종합 + 비중 | opus | Task, Read, Write, Bash, Grep |

## 호출 패턴 (3가지)

### Pattern A: 단일 종목 분석
```
사용자: "삼성전자 분석해줘"
   ↓
stock-analyst 직접 호출 (6단계)
[옵션] memory-keeper 참조 (과거 사례)
[옵션] catalyst-analyst 호출 (깊은 카탈리스트)
```

### Pattern B: 다종목 추천 (full pipeline)
```
사용자: "오늘 시그널 중 Top 3 추천"
   ↓
investment-orchestrator (Phase 0-5 모두)
   ├─ Phase 1: memory-keeper
   ├─ Phase 2: stock-analyst × N + catalyst-analyst × N (병렬)
   ├─ Phase 3: portfolio-risk-analyst
   ├─ Phase 4: devils-advocate
   └─ Phase 5: 4팩터 Z-Score → Top 3 + BEST PICK
```

### Pattern C: 주간 복기
```
매주 금요일 또는 사용자: "지난 주 어땠어?"
   ↓
weekly-reviewer
   ├─ memory-keeper 호출 (5일치 메모리)
   ├─ 3관점 분석 (칭찬/비판/시장)
   ├─ 패턴 발견 → 에피소드 저장 (memory-keeper)
   └─ philosophy_v{N+1} 갱신
```

## 4팩터 Z-Score Ranking (Phase 5, dacon 검증 패턴)

```python
# 각 종목 점수 (0-100)
stock_score   = stock-analyst.total       # 6단계 종합
catalyst_score = catalyst-analyst.score   # 카탈리스트 강도
risk_score    = 100 - portfolio-risk.var  # 위험 역산
devil_score   = 100 - devils-advocate.challenge_strength  # 도전 역산

# Z-score 정규화 (universe 내)
Z_value  = z_score(stock_score)
Z_growth = z_score(catalyst_score)
Z_risk   = z_score(risk_score)
Z_devil  = z_score(devil_score)

# 가중 합산
combined = 0.30 × Z_value + 0.30 × Z_growth + 0.20 × Z_risk + 0.20 × Z_devil

# 분산 필터 (섹터 3개+ 페널티)
# 비중 산출 (vol-target)
```

## 출처 태그 의무 (환각 방지 — dacon 패턴)

stock-analyst, catalyst-analyst, devils-advocate 모두 정성 항목에 출처 태그 필수:

```
[출처: WebSearch · YYYY-MM]   외부 검색
[출처: DART · YYYY-MM-DD 공시]  공시 (URL + 일자)
[출처: KIS API · YYYY-MM-DD]   KIS 실시간
[출처: FnGuide · YYYY-MM 컨센]  컨센서스
[정량]                          정량 데이터 (KRX/FnGuide)
확인 필요                       출처 불명확 (환각 가능성)
```

태그 없는 정성 주장 = 환각 의심 → 자가 검증 후 재작성.

## Python 룰 에이전트 (HollyKR 내장, 별도)

```
[scripts/screeners/holly_kr/agents/]
- macro_agent.py        Yahoo Finance 거시 + Kill Switch
- theme_agent.py        KIS 섹터 + 알고픽 Top 3
- risk_agent.py         종목별 위험 VETO
- postmortem_agent.py   시그널 → 결과 추적
```

이건 daily-scan (`run --auto`)이 자동 호출. Sub-agent와 별개 레이어.

## 다른 프로젝트 자원 활용

| 자원 | 활용 에이전트 | 도구 |
|---|---|---|
| 주식 ai 리서치 리포트 | catalyst-analyst | dart_api, fnguide_data, peer_snapshot, report_extractor |
| 주식 ai 리서치 리포트 | portfolio-risk-analyst | volatility_beta, fdr_band |
| 주식 ai 리서치 리포트 | stock-analyst | industry_kpi (27 섹터) |
| DB GAPS 대회 | devils-advocate | Inversion/Premortem 패턴 |
| DB GAPS 대회 | portfolio-risk-analyst | cvxpy QP optimization |
| dacon 대회 | orchestrator | 4팩터 Z-Score ranking |
| dacon 대회 | 정성 에이전트 | 출처 태그 의무 |

## 호출 예시

```bash
# Claude Code 환경에서

# 단일 종목
"삼성전자 분석해줘"
  → stock-analyst 자동 호출 (PROACTIVELY use)

# 다종목 추천
"오늘 HollyKR 시그널 중 Top 3 추천 + 자동매매 가능?"
  → investment-orchestrator 자동 호출 (full pipeline)

# 카탈리스트만
"펩트론 임상 결과 임박 카탈리스트 분석"
  → catalyst-analyst 자동 호출

# 주간 복기
"지난 주 매매 복기 + 다음 주 plan"
  → weekly-reviewer 자동 호출
```

## 자동화 옵션 (선택)

```yaml
# .claude/hooks/ 또는 cron으로 자동 trigger 가능
- daily 14:30: HollyKR 시그널 → orchestrator 자동 호출
- weekly Friday 18:00: weekly-reviewer 자동 호출
- 큰 사건 (Kill Switch): devils-advocate 우선 호출
```

현재 수동 호출. 자동화는 Phase K (자동매매)와 함께 신중하게.

## 갱신 시 주의

- `.claude/agents/*.md` 수정 후 Claude Code 세션 재시작 필요 (file watcher 갱신)
- tools 필드 변경은 권한 영향 → 신중하게
- description의 PROACTIVELY use 키워드 절대 제거 X (자동 트리거 핵심)
