---
description: HollyKR 매주 토요일 복기 (Phase G-11 알고픽 인사이트). weekly_review.py 실행 + 3-시각 sub-agent (칭찬/비판/시장분석) 병렬 호출 + memory/weekly_philosophy 저장 + 텔레그램 송출.
---

# /weekly-review — HollyKR 매주 복기

알고픽 인사이트: "매주 한 주의 매매를 돌아본다. 칭찬, 비판, 시장 분석 에이전트가 복기하고, 종합해 투자 철학 스냅샷을 갱신한다."

## 단계 1: 정량 복기 실행

```bash
python scripts/weekly_review.py
```

산출물:
- `data/holly_kr/weekly_review_YYYY-MM-DD.md` (정량 통계 + NAV vs KOSPI)
- `data/holly_kr/memory/episodic_YYYY-Wxx.md` (인상적 매매 자동 식별)
- `data/holly_kr/memory/nav_history.json` (NAV 누적)

## 단계 2: 3-시각 복기 sub-agent 병렬 호출

단일 메시지에 3개 Agent tool use 동시 launch (병렬):

### Agent 1: 칭찬 (잘한 점)
```
- subagent_type: "general-purpose"
- description: "이번 주 잘한 판단 5개"
- prompt:
  "이번 주 HollyKR 부서장의 판단 중 잘한 점 5개를 찾아라.
   
   입력 (Read):
   - data/holly_kr/weekly_review_YYYY-MM-DD.md (오늘 정량 복기)
   - data/holly_kr/analysis_*.json (최근 7일)
   - data/holly_kr/memory/episodic_*.md (최근 4주)
   
   분석:
   - 정확한 BUY 격상 (목표 도달 종목)
   - 보수 운용 (Kill Switch 환경 적절)
   - 공석 허용 (강제 채우기 X)
   - ALPHA pool 우대
   - 텔레그램 양식 준수
   
   출력: 5개 잘한 점 + 각 한 줄 사유 (정량 근거 포함)"
```

### Agent 2: 비판 (못한 점)
```
- subagent_type: "general-purpose"
- description: "이번 주 못한 판단 5개"
- prompt:
  "이번 주 HollyKR 부서장의 판단 중 못한 점 5개를 찾아라 (devils-advocate 시각).
   
   분석:
   - 손절 발동된 BUY (왜 격상했나?)
   - 너무 공격적 비중 (Kill Switch 임박인데)
   - 사용자 룰 위반 (있다면)
   - 알고픽 인사이트 미반영 (테마 분석 등)
   
   출력: 5개 못한 점 + 각 한 줄 사유 + 다음 주 개선 제안"
```

### Agent 3: 시장분석 (한 주 변화)
```
- subagent_type: "general-purpose"
- description: "한 주 시장 변화 + 다음 주 전망"
- prompt:
  "지난 주 KOSPI/KOSDAQ 시장 변화를 분석하고 다음 주 전망을 제시.
   
   입력:
   - .cache/ohlcv/ohlcv_cache.pkl (KOSPI 200 ETF 069500 등)
   - data/holly_kr/memory/nav_history.json (Alpha 추이)
   
   분석:
   - 변동성 추이 (Kill Switch 임박?)
   - 주도 테마 변화 (반도체 → 방산? 등)
   - 외국인 흐름
   - 다음 주 calendar effect (월별 평균)
   
   출력: 한 주 시장 요약 + 다음 주 전망 + 부서장에게 권장사항"
```

## 단계 3: 종합 — memory/weekly_philosophy 저장

3 sub-agent 결과 종합 → `data/holly_kr/memory/weekly_philosophy_YYYY-Wxx.md` 저장:
- 잘한 점 5개
- 못한 점 5개
- 시장 변화 요약
- 다음 주 부서장 prompt 조정 제안

## 단계 4: 텔레그램 송출

```bash
python scripts/weekly_review.py --telegram
```

또는 종합 리포트를 별도 텔레그램 메시지로 송출:
- 메시지 1: 정량 복기 (BUY 결과 + NAV vs KOSPI)
- 메시지 2: 3-시각 복기 종합 (잘함/못함/시장)

## 권장 호출 시기

매주 토요일 (KOSPI 휴장):
- 한 주 결과 정리
- 부서장 자기 평가
- 다음 주 prompt 조정 자료

또는 사용자가 호출하고 싶을 때 언제든.
