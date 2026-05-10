# HollyKR Sub-Agent System — 통합 가이드 (Phase G-7)

7개 Claude AI 서브에이전트가 매일 시그널을 평가하고, 부서장 (orchestrator)이 최종 순위를 매김.

## 시스템 다이어그램

```
┌──────────────────────────────────────────────────────────────┐
│  [HollyKR Python — 매일 자동, 14:20]                          │
│                                                                │
│  ALPHA pool 2 (5년 검증, 항상 ACTIVE)                          │
│  + 풀 외 시장 적응 Top 3 (60일 강조 평가)                       │
│  = ACTIVE 5 전략                                                │
│                                                                │
│  ACTIVE 5 × 1500 종목 → 시그널 N개 (자연 발생, 보통 5~15개)     │
└──────────────────────────────────────────────────────────────┘
                              ↓
                    [모든 시그널 → cutoff X]
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  [Claude AI 서브에이전트 — 사원, N개 시그널 모두 평가]          │
│                                                                │
│  Phase 1 (단일): memory-keeper                                 │
│    → 과거 사례 + 회피 패턴 + 현재 philosophy                    │
│                                                                │
│  Phase 2 (병렬): stock-analyst × N + catalyst-analyst × N       │
│    → N개 종목 각각 6단계 분석 + DART/뉴스 카탈리스트              │
│                                                                │
│  Phase 3 (단일): portfolio-risk-analyst                         │
│    → N개 종합 VaR + correlation + cvxpy QP                       │
│                                                                │
│  Phase 4 (단일): devils-advocate                                │
│    → 합의 도전 (Inversion/Premortem/가정/OOS)                  │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  [부서장 — investment-orchestrator, LLM reasoning]              │
│                                                                │
│  N개 사원 보고서 종합 → reasoning 기반 순위 매김                 │
│   - 시그널 5개 → 5개 모두 표시 + 순위                            │
│   - 시그널 15개 → Top 5-10 + BEST PICK                          │
│   - 시그널 30+ → Top 10 + BEST PICK                              │
│                                                                │
│  → BEST PICK + 자본 비중 + 텔레그램 송출                         │
└──────────────────────────────────────────────────────────────┘

[매주 금] weekly-reviewer
  → 칭찬/비판/시장 → philosophy_v{N+1} → memory-keeper
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
| **investment-orchestrator** | 부서장 — N개 사원 보고서 reasoning + 순위 | opus | Task, Read, Write, Bash, Grep |

## 호출 패턴 (3가지)

### Pattern A: 단일 종목 분석
```
사용자: "삼성전자 분석해줘"
   ↓
stock-analyst 직접 호출 (6단계)
[옵션] memory-keeper 참조 (과거 사례)
[옵션] catalyst-analyst 호출 (깊은 카탈리스트)
```

### Pattern B: 일일 시그널 평가 (full pipeline)
```
사용자: "오늘 시그널 평가해줘" 또는 매일 자동
   ↓
investment-orchestrator (부서장)
   ├─ Phase 1: memory-keeper (과거 사례)
   ├─ Phase 2: stock-analyst × N + catalyst-analyst × N (모든 시그널, 병렬)
   ├─ Phase 3: portfolio-risk-analyst (N개 종합)
   ├─ Phase 4: devils-advocate (합의 도전)
   └─ Phase 5: 부서장 reasoning → 순위 + BEST PICK
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

## 부서장 (orchestrator) 핵심 — LLM Reasoning Ranking

이전: 4팩터 Z-Score 자동 계산 (제거됨)
현재: **LLM reasoning 기반 종합 판단** (사용자 의도: 부서장 = 사람처럼 판단)

부서장 입력:
- N개 stock-analyst 보고서 (6단계 분석)
- N개 catalyst-analyst 보고서 (DART/뉴스)
- portfolio-risk-analyst 보고서 (전체 리스크)
- devils-advocate 도전
- memory-keeper 과거 사례

부서장 출력:
```markdown
## 오늘의 부서장 판단 (YYYY-MM-DD)

### 시그널 N개 검토 결과

#### 1위: [종목] (BEST PICK)
**부서장 판단**: [reasoning 3-5문장]
**신뢰도**: HIGH/MEDIUM/LOW
**비중**: X%
**근거**: stock-analyst (재무 우수) + catalyst-analyst (실적 임박) + ...

#### 2위: [종목]
...

### 회피 (devils-advocate 또는 risk VETO)
- [종목] : 사유

### 종합 메시지
[부서장의 한 줄 정리]
```

## 출처 태그 의무 (환각 방지)

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

## 4 룰 에이전트 (Python) — 데이터 fetch 전용

```
[scripts/screeners/holly_kr/agents/]
- macro_agent.py        Yahoo Finance 거시 + Kill Switch (시장 동결)
- theme_agent.py        KIS 섹터 + 알고픽 Top 3 (참고)
- risk_agent.py         종목별 위험 VETO (시총/거래대금/ATR)
- postmortem_agent.py   시그널 → 결과 추적 (학습 데이터)
```

**역할 변화** (Phase G-7): multiplier 보정 X → **데이터 제공 + Kill Switch만**.
시그널 평가 = sub-agent + 부서장 reasoning이 담당.

## 다른 프로젝트 자원 활용

| 자원 | 활용 에이전트 | 도구 |
|---|---|---|
| 주식 ai 리서치 리포트 | catalyst-analyst | dart_api, fnguide_data, peer_snapshot, report_extractor |
| 주식 ai 리서치 리포트 | portfolio-risk-analyst | volatility_beta, fdr_band |
| 주식 ai 리서치 리포트 | stock-analyst | industry_kpi (27 섹터) |
| DB GAPS 대회 | devils-advocate | Inversion/Premortem 패턴 |
| DB GAPS 대회 | portfolio-risk-analyst | cvxpy QP optimization |
| dacon 대회 | 정성 에이전트 | 출처 태그 의무 (환각 방지) |
| 알고픽 | memory-keeper, weekly-reviewer | 기억 주입 + 주간 복기 |
| Bridgewater | devils-advocate | 의사결정 품질 = 반대 의견 품질 |

## 호출 예시

```bash
# Claude Code 환경에서

# 단일 종목
"삼성전자 분석해줘"
  → stock-analyst 자동 호출 (PROACTIVELY use)

# 일일 시그널 평가 (부서장 풀 파이프라인)
"오늘 HollyKR 시그널 평가 + Top 추천"
  → investment-orchestrator 자동 호출
    - ACTIVE 5 전략에서 발생한 N개 시그널
    - sub-agent 모두 평가 (cutoff X)
    - 부서장 reasoning → 순위

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
