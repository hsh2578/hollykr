---
name: hollykr-rules-check
description: PROACTIVELY use BEFORE any HollyKR daily-orchestrate, sub-agent 호출, 부서장 호출, 텔레그램 송출 작업. 사용자가 명시한 10개 룰 자동 검증 → 위반 가능 시점에 즉시 경고. 반복 실수 방지 (어시스턴트가 자주 cutoff 적용/분산 cap을 잘못된 단계에 적용).
---

# HollyKR 사용자 룰 검증 (반복 실수 방지)

이 skill은 HollyKR 작업 시작 전 + 진행 중 + 완료 시 사용자 명시 룰 위반을 자동 감지한다.

## ⚠️ 자주 하는 실수 (정직 기록)

다음은 어시스턴트가 반복 위반한 패턴 — 새 작업 시작 시 가장 먼저 체크.

### 실수 1: Sub-agent 단계에서 cutoff 적용 ❌
```
잘못된 패턴:
  daily-scan 31개 → Stage A "Top 15만" sub-agent 호출
                  → 16개는 sub-agent 평가 안 받음

올바른 패턴 (사용자 룰 3):
  daily-scan 31개 → 31개 모두 sub-agent 호출
                  → 부서장이 31개 보고서 받아 Top 10 결정
```

**검증 포인트**: sub-agent 호출 시 `signals_today.json count == 호출 수`인지 확인.
일치 X면 룰 위반 → 누락 종목 추가 호출 필요.

### 실수 2: Top 10 분산 cap 5를 sub-agent 단계 적용 ❌
```
잘못된 패턴:
  Stage A에서 "전략당 5개로 제한" → bottom_breakout 누락

올바른 패턴 (사용자 룰 4):
  Stage A는 점수만 매김 (분산 X)
  Stage B sub-agent 31개 모두 평가
  부서장 단계에서만 Top 10 분산 cap 5 적용
```

**검증 포인트**: 분산 cap 5 코드는 부서장 prompt에만 존재해야.

### 실수 3: 거래대금 cut 임의 추가 ❌
```
잘못된 패턴:
  "거래대금 30억 미만 자동 제외" 룰 추가

올바른 패턴 (사용자 룰 2):
  거래대금 cut 절대 X (사용자 명시)
  표시만 OK ("⚠️ 거래대금 14억 작전 위험")
```

### 실수 4: 4 룰 에이전트 단순화 ❌
```
잘못된 패턴:
  "Macro/Theme/Risk/Postmortem 일부 단순화 후 유지"

올바른 패턴 (사용자 룰 1):
  완전 제거. run.py에서 호출 X.
```

### 실수 5: 종목명 KRX CSV 무시 ❌
```
잘못된 패턴:
  Sub-agent (Haiku) 종목명 환각 → 잘못된 종목 분석
  066570 → "LG화학" (실제 LG전자)

올바른 패턴 (사용자 룰 7):
  종목코드 매핑은 KRX CSV (data/holly_kr/krx_master.csv 또는
  root 종목코드.csv)가 유일한 진실. Sub-agent 환각 방지 위해
  Stage A는 Python으로 (LLM 종목명 추측 X).
```

### 실수 6: 매주 토요일 백테스팅 잊음 ❌
```
잘못된 패턴:
  매일 백테스트 cron 활성화

올바른 패턴 (사용자 룰 8):
  holly-nightly.yml cron: '0 10 * * 6' (매주 토 19:00 KST)
```

## 📋 사용자 명시 10대 룰 (CLAUDE.md 동일)

```
1. 4 룰 에이전트 (Macro/Theme/Risk/Postmortem) 완전 제거
2. 시그널 cutoff = 모든 전략 Top 20 (ALPHA pool 면제, run.py에서 처리)
3. Sub-agent 모든 시그널 평가 (cutoff X) — 31개면 31개 모두
4. Top 10 분산 cap 5는 부서장 단계 (sub-agent 단계 X)
5. 부서장 = 의사결정자 (sub-agent와 다른 결정 가능)
6. 공석 허용 (강제로 Top 10 채우지 X)
7. 종목코드 = KRX CSV (root 종목코드.csv 우선) 검증 필수
8. 텔레그램 양식 = CIO 보고서 (memory/hollykr_telegram_format.md)
9. 백테스팅 = 매주 토요일 (매일 X)
10. 새 전략 추가 시 5년 strict 검증 필수
```

## 🔍 작업 단계별 체크리스트

### Stage 0: 작업 시작 전
```
□ CLAUDE.md 읽음 (사용자 룰 10개 인지)
□ memory/MEMORY.md 읽음 (이전 결정사항 확인)
□ 오늘 signals_today.json 존재 확인
□ ALPHA pool 현재 상태 확인 (alpha_pool.json)
```

### Stage 1: daily-scan
```
□ 4 룰 에이전트 호출 X (run.py --auto만)
□ ALPHA pool cut 면제 적용 (전략별 Top 20 cut)
□ 거래대금 cut 절대 X
□ 결과 signals_today.json + 시그널 N개 확인
```

### Stage 2: 사전 데이터 수집 (Python — DART/FnGuide 통합)
```
□ scripts/sub_agent_data_prep.py 실행
   - 내부에서 sub_agent_dart_fnguide.collect_for_tickers() 호출
   - DART corp_code 캐시 로드 (3963개 상장사)
   - 31개 병렬 수집 (FnGuide + DART)
   - 약 12-15초 소요
□ sub_agent_input.json N개 == signals_today.json N개 확인
□ 각 종목에 다음 섹션 모두 포함 확인:
   - indicators (가격/거래량 30+ 지표)
   - dart (events 카테고리별: 자사주/임원매도/유상증자/최대주주변경/주요사항/배당)
   - fnguide (header/ttm/quality/valuation/trends_5y)
□ FnGuide quality 핵심:
   - cfo_to_ni (이익 질, 1.0+ 양호)
   - debt_ratio_pct (200%+ 위험)
   - current_ratio_pct (100%- 압박)
   - roe_pct, roic_pct
```

### Stage 3: Stage A 정량 점수 (Python, sub-agent X)
```
□ scripts/stage_a_quick_score.py 실행
□ 31개 모두 점수 매김 (한 종목도 누락 X)
□ ALPHA pool 종목 강제 진입 적용
□ stage_a_result.json 검증
```

### Stage 4: Stage B Sub-agent 호출 ⚠️ 가장 위반 위험 큰 단계
```
□ signals_today.json의 N개 == sub-agent 호출 수
   ✗ Top 15만 호출 = 룰 위반
   ✓ 31개 모두 호출 = 룰 준수
□ 종목명은 sub_agent_input.json의 'name' 필드 사용
   (sub-agent prompt에 명시 — 환각 방지)
□ 단일 메시지 다중 Agent 호출 (병렬)
□ 부서장 호출 X (다음 단계)
□ Sub-agent prompt에 사전 수집 데이터 활용 명시:
   - "indicators / dart / fnguide 섹션 활용"
   - "FnGuide WebFetch 호출 X (사전 수집됨)"
   - "DART WebFetch 호출 X (사전 수집됨)"
   - "WebSearch는 카탈리스트 1회만"
   → 종목당 50-70초 (이전 60-90초보다 단축)
```

### Stage 5: 부서장 호출
```
□ Stage B 31개 결과 모두 전달 (cutoff X)
□ Top 10 분산 cap 5 명시 (이 단계에서만 적용)
□ ALPHA pool 가산점
□ clenow_momentum 보수 강등 (한국 PF 0.90)
□ 공석 허용 (강제 Top 10 채우기 X)
□ 텔레그램 양식 명시 (CIO 보고서 + Top 10)
```

### Stage 6: 텔레그램 송출
```
□ 메시지 1: CIO 보고서 (~2500-3000자)
   - 한 줄 결론 + 시장 진단 + 전략 소개 + 매수 추천
   - 자본별 매수 금액 + 매도 룰 + 회피 + 부서장 의견
□ 메시지 2: Top 10 전체 (~1500-1700자)
   - 매수/보류/공석 + 전략 분산 통계
□ 형식적/기계적 톤 X — CIO가 사용자에게 직접 보고
```

## 🚨 위반 감지 시 행동

위반 발견 → **즉시 사용자에게 보고 + 정정**:
```
1. 어떤 룰을 위반했는지 명시 (룰 번호 + 내용)
2. 정정 방법 제시
3. 사용자 승인 후 정정 (이미 진행한 작업이라도)
```

## 🎯 최종 검증 (텔레그램 송출 직전)

```
□ Sub-agent 호출 수 = signals_today.json count (룰 3)
□ Top 10 전략 분산 ≤5개 per strategy (룰 4)
□ ALPHA pool 종목 적절 우대 (룰 5)
□ 공석 시 명시 ("VACANT (의도적 공석)") (룰 6)
□ 종목명 KRX CSV와 100% 일치 (룰 7)
□ CIO 보고서 양식 (룰 8)
□ 주말이면 백테스트 자동 트리거 안 됨 (룰 9)
```

## 사용 방법

이 skill은 사용자가 명시적으로 호출하지 않아도, HollyKR 작업 시작 시 자동 활성화돼야 한다.

특히 다음 키워드 감지 시 무조건 이 skill 체크리스트 적용:
- `/daily-orchestrate`
- `daily-scan`
- `Stage A`, `Stage B`, `부서장`, `orchestrator`
- `텔레그램`, `telegram`, `CIO 보고서`
- HollyKR sub-agent 호출 (`stock-analyst`, `investment-orchestrator`)

작업 시작 메시지에 다음 한 줄 명시:
```
✓ HollyKR 룰 체크 완료 — 룰 1-10 위반 없음, 진행
```

위반 발견 시:
```
⚠️ HollyKR 룰 N 위반 — [위반 내용]
   정정: [방법]
```
