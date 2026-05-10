---
description: HollyKR 매일 자동 분석 + 텔레그램 송출 (Phase G-9 최적화). daily-scan → 사전 데이터 수집 → Stage A Haiku 31개 스크린 → Stage B Opus Top 15 깊은 분석 → 부서장 Top 10 결정 → 텔레그램 CIO 보고서 송출.
---

# /daily-orchestrate — HollyKR 매일 자동 분석

당신은 HollyKR 시스템의 매일 분석 자동화를 실행한다. 다음 5단계를 순차로 진행한다.

## ⚠️ 사용자 명시 룰 (반드시 준수)

1. **4 룰 에이전트 호출 X** (완전 제거)
2. **시그널 cutoff = 전략당 Top 20** (ALPHA pool 면제, run.py에서 처리)
3. **Sub-agent 모든 시그널 평가** — Stage A에서 31개 모두 스크린 (cutoff X)
4. **Top 10 분산 cap 5는 부서장 단계** — 미리 적용 X
5. **공석 허용** — 강제로 Top 10 채우지 X
6. **텔레그램 = CIO 보고서 양식** (memory/hollykr_telegram_format.md 준수)
7. **자본 비율 명시** — 25% 노출 / 75% 현금 (Kill Switch 환경)

## 단계 1: Daily-Scan 실행

```bash
python -m scripts.screeners.holly_kr.run --auto --entry close
```

결과 검증:
- `data/holly_kr/signals_today.json` 생성 확인
- 시그널 N개 (보통 20-50개) 확인
- 시그널 0개면 즉시 종료 (텔레그램 "오늘 시그널 없음" 송출 후)

## 단계 2: 사전 데이터 수집

```bash
python scripts/sub_agent_data_prep.py
```

결과 검증:
- `data/holly_kr/sub_agent_input.json` 생성 확인
- 각 시그널에 `indicators` 섹션 (가격 모멘텀/SMA/ATR/RSI/유동성/Stage 2) 포함 확인

## 단계 3: Stage A — Python 정량 스코어러 (환각 0%)

```bash
python scripts/stage_a_quick_score.py
```

결과 검증:
- `data/holly_kr/stage_a_result.json` 생성
- 31개 모두 점수 매김 (사용자 룰 — 모든 시그널 평가)
- Top 15 ticker 추출 (ALPHA pool 강제 진입 + 나머지 점수순)

⚠️ **중요**: Haiku sub-agent 검토 결과 종목명 환각 19/31 발견 → Python 스코어러로 대체.
- Python: 0.003초, 환각 0%, 사용자 룰 준수
- 정량 (50) + 전략 (15) + 정성 (35) = 100점 만점
- ALPHA pool 종목 무조건 Top 15 진입 (cut 면제)

## 단계 4: Stage B — Top 15 깊은 분석 (Opus, 병렬)

`stage_a_result.json`의 `top` 배열 (15개)에서 각 ticker 추출 후 `stock-analyst` sub-agent를 **병렬 호출**:

**중요**: 단일 메시지에 15개 Agent tool use를 동시 launch (병렬). 순차 X.

```
각 ticker마다:
- subagent_type: "stock-analyst"  (Opus 4.7)
- description: "{종목명} 깊은 분석"
- prompt:
  "{종목명} ({ticker}) 깊은 분석.
   
   입력 (Read로 로드):
   - data/holly_kr/sub_agent_input.json — 사전 수집 indicators 활용 (재계산 X)
   - data/holly_kr/stage_a_result.json — Stage A 점수 + 사유 참고
   - data/holly_kr/alpha_pool.json — ALPHA pool 가산점
   
   분석 프레임워크 6단계 모두 (기업/재무/산업/모멘텀/리스크/종합).
   WebSearch는 카탈리스트 1-2회만, 종목당 목표 60-90초.
   
   출력: BUY/HOLD/AVOID + 가격 가이드 + 핵심 근거/리스크"
```

결과 저장:
- 각 sub-agent 결과를 `data/holly_kr/stage_b_results/{ticker}.md` 저장 (선택)

## 단계 5: 부서장 — Top 10 최종 결정

`investment-orchestrator` sub-agent를 **1번** 호출:

```
Agent 도구 호출:
- subagent_type: "investment-orchestrator"
- description: "부서장 Top 10 결정"
- prompt:
  "HollyKR 오늘 31개 시그널 중 Stage B 통과 15개에 대한 깊은 분석 결과를
   종합해서 Top 10을 결정해줘.
   
   입력:
   - 단계 3 결과 (Stage A 31개 스크린)
   - 단계 4 결과 (Stage B 15개 깊은 분석)
   - data/holly_kr/sub_agent_input.json (정량 지표)
   - data/holly_kr/alpha_pool.json (ALPHA pool)
   - data/holly_kr/analysis_today.json (참고용 — 어제 결정)
   
   부서장 원칙 (memory/orchestrator_reasoning_principles.md):
   - Sub-agent 의견은 1표 — 부서장 다른 결정 가능
   - 포트폴리오 관점 (분산 cap 5 강제)
   - ALPHA pool 가산점
   - clenow_momentum 보수 강등 (한국 5년 PF 0.90)
   - 공석 허용 (강제 채우지 X)
   - Kill Switch 환경 → 자본 노출 25%
   
   출력 (memory/hollykr_telegram_format.md 양식):
   - 메시지 1: CIO 보고서 (~2500-3000자)
     · 한 줄 결론 + 시장 진단 + 전략 소개 + 매수 추천 N종목 + 자본별 금액 + 매도 룰 + 회피 + 부서장 의견
   - 메시지 2: Top 10 전체 (~1500-1700자)
     · 매수/보류/공석 + 전략 분산 통계
   
   추가 저장:
   - data/holly_kr/analysis_today.json 갱신 (오늘 날짜 + 전체 결정)"
```

## 단계 6: 텔레그램 송출

부서장 결과를 텔레그램으로 송출 (2개 메시지):

```bash
# 메시지 1 (CIO 보고서)
python -c "
from scripts.telegram_alert import send_telegram
import sys
sys.stdout.reconfigure(encoding='utf-8')
msg = open('temp_msg1.txt', 'r', encoding='utf-8').read()
send_telegram(msg)
"

# 메시지 2 (Top 10 전체) — 약간의 지연 후
python -c "
import time; time.sleep(3)
from scripts.telegram_alert import send_telegram
msg = open('temp_msg2.txt', 'r', encoding='utf-8').read()
send_telegram(msg)
"
```

## 완료 보고

사용자에게 다음 형식으로 한 줄 보고:

```
✅ HollyKR daily-orchestrate 완료 (총 X분 X초)
   • daily-scan: 31개 시그널
   • Stage A: 31 → 15 통과 (Haiku, X분)
   • Stage B: 15개 깊은 분석 (Opus 병렬, X분)
   • 부서장: Top 10 (BUY N / HOLD M / 공석 K)
   • 텔레그램: 2개 메시지 송출 완료

오늘의 BEST PICK: [종목명] (자본 X%)
```

## 에러 처리

각 단계 실패 시:
1. 에러 로그 출력
2. 다음 단계 진행 X (전체 abort)
3. 텔레그램으로 "❌ HollyKR 자동 분석 실패 — [단계] [에러]" 송출
4. 사용자에게 명확한 에러 메시지

## 예상 시간 (Phase G-9 최적화 후)

```
단계 1: daily-scan         ~5-7분
단계 2: 사전 수집          ~30초
단계 3: Stage A (Python)   ~1초 ⚡ Haiku 6분 → Python 0.003초로 변경
단계 4: Stage B (Opus 병렬) ~10-15분 (병렬, 가장 느린 것 기다림)
단계 5: 부서장             ~3-5분
단계 6: 텔레그램           ~10초
─────────────────────────────
합계: 약 20-28분 (현재 30-40분 → 약 -30%)

비용 (Anthropic API 기준 추정):
- Stage A: $0 (Python)
- Stage B: ~$3-4 (Opus 4.7, 15회 병렬)
- 부서장: ~$0.5-1 (Opus 4.7, 1회)
- 합계: ~$4-5 / 회

Claude Code 사용 시 사용자 plan에서 차감 (별도 결제 X).
```
