# HollyKR 아키텍처 (시각 정리)

> 지금까지 구축한 알고리즘을 다이어그램으로 정리. GitHub에서 자동 렌더링됩니다.

---

## 1. 전체 일일 파이프라인

```mermaid
flowchart TD
    T["🕐 14:40 KST<br/>윈도우 작업 스케줄러"] --> BAT["cmd.exe → hollykr_scan.bat"]
    BAT --> CLI["claude -c --dangerously-skip-permissions<br/>/daily-orchestrate"]

    CLI --> S1["단계 1: daily-scan<br/>ACTIVE 5전략 × 시총 1000억+ 종목"]
    S1 --> S2["단계 2: 사전 데이터 수집<br/>OHLCV 30+지표 · DART공시 · FnGuide재무 · 사업보고서"]
    S2 --> S3["단계 3: Stage A (Python)<br/>정량 점수 · 모든 시그널 · 환각 0%"]
    S3 --> S4["단계 4: Stage B (Sonnet 4.6)<br/>stock-analyst × N개 병렬<br/>6단계 깊은 분석 · 모든 시그널"]
    S4 --> S5["단계 5: 부서장 (Opus 4.7)<br/>investment-orchestrator<br/>Top 10 · 분산 cap 5 · 공석 허용"]
    S5 --> S6["단계 6: 텔레그램 송출<br/>메시지1 CIO보고서 · 메시지2 Top10"]

    S5 -.저장.-> LOG["analysis_YYYY-MM-DD.json<br/>(매주 복기용 누적)"]

    style T fill:#ffe6cc
    style S4 fill:#cce5ff
    style S5 fill:#d4edda
    style S6 fill:#fff3cd
```

---

## 2. ACTIVE 전략 동적 선정 (시장 적응)

```mermaid
flowchart LR
    subgraph 분기["분기 1회 (5년 백테스트)"]
        B5["backtest_5y.py<br/>학습 2년 + Hold-out 3년 strict"]
        B5 --> AP["ALPHA pool<br/>ma_convergence<br/>new_high_52w_approach"]
    end

    subgraph 매일["매일 19:00 (nightly)"]
        NS["nightly_selector.py<br/>28개 전략 평가<br/>0.5×60일 + 0.3×180일 + 0.2×5년"]
        NS --> MKT["시장 적응 Top 3<br/>(강세→trend / 약세→reversion<br/>횡보→range)"]
    end

    AP --> ACT["ACTIVE 5개<br/>active_strategies.json"]
    MKT --> ACT
    ACT --> SCAN["매일 14:40 daily-scan"]

    style AP fill:#d4edda
    style MKT fill:#cce5ff
    style ACT fill:#fff3cd
```

---

## 3. Stage B 6단계 분석 프레임워크

```mermaid
flowchart TD
    IN["사전 수집 데이터<br/>sub_agent_input.json"] --> A1

    subgraph SA["stock-analyst (Sonnet 4.6) — 종목당 1개"]
        A1["1. 기업 개요<br/>DART 사업보고서"] --> A2
        A2["2. 재무 분석<br/>FnGuide TTM/ROE/부채/CFO"] --> A3
        A3["3. 산업 분석<br/>WebSearch 1회 카탈리스트"] --> A4
        A4["4. 모멘텀 분석<br/>가격/SMA/RSI/ALPHA가산"] --> A5
        A5["5. 리스크 요인<br/>DART공시/작전의심/유동성"] --> A6
        A6["6. 종합 의견<br/>BUY/HOLD/AVOID + 가격가이드"]
    end

    A6 --> OUT["부서장에게 전달<br/>(38개 시그널 → 38 결과)"]

    style SA fill:#cce5ff
    style A6 fill:#d4edda
```

---

## 4. 부서장 의사결정 (CIO)

```mermaid
flowchart TD
    M["호출 즉시 메모리 자동 로드<br/>episodic / weekly_philosophy / analysis 5일"] --> TH

    TH["Phase G-10 시장 테마 분석<br/>주도 테마 · 자금 회전 · Kill Switch"] --> P1

    P1["Phase 1: stock-analyst × N 병렬"] --> P2
    P2["Phase 2: 비교 매트릭스"] --> P3
    P3["Phase 3: 포트폴리오 평가<br/>분산/상관/시장 컨텍스트"] --> P4
    P4["Phase 4: Top 10 결정"]

    P4 --> R1["✓ 분산 cap 5 (전략당 ≤5)"]
    P4 --> R2["✓ ALPHA pool 가산점"]
    P4 --> R3["✓ clenow_momentum 보수 강등"]
    P4 --> R4["✓ 공석 허용 (강제 채우기 X)"]
    P4 --> R5["✓ Kill Switch → 자본 노출 25%"]

    R1 & R2 & R3 & R4 & R5 --> OUT["텔레그램 CIO 보고서<br/>메시지1 + 메시지2"]

    style M fill:#ffe6cc
    style TH fill:#ffe6cc
    style P4 fill:#d4edda
    style OUT fill:#fff3cd
```

---

## 5. 청산 6단계 우선순위 (백테스트 ↔ 실전 동일)

```mermaid
flowchart TD
    P["보유 포지션 (매일 점검)"] --> C1{"시초가 ≤ 손절가?"}
    C1 -->|Yes| E1["① 갭다운: 시초가 즉시 청산"]
    C1 -->|No| C2{"장중 저가 ≤ 손절가?"}
    C2 -->|Yes| E2["② 손절가 청산"]
    C2 -->|No| C3{"장중 고가 ≥ 목표가?"}
    C3 -->|Yes| E3["③ 50% 부분익절<br/>잔량 트레일링 모드"]
    C3 -->|No| C4{"트레일링 중 &<br/>최고종가×0.95 이탈?"}
    C4 -->|Yes| E4["④ 잔량 트레일링 청산"]
    C4 -->|No| C5{"진입 다음날<br/>종가 ≤ entry×-3%?"}
    C5 -->|Yes| E5["⑤ First-day -3%<br/>다음날 시가 청산"]
    C5 -->|No| C6{"days_held ≥<br/>hold_days_max?"}
    C6 -->|Yes| E6["⑥ 시간 청산 (종가)"]
    C6 -->|No| P

    style E1 fill:#f8d7da
    style E2 fill:#f8d7da
    style E3 fill:#d4edda
    style E5 fill:#fff3cd
```

---

## 6. 6단계 운용 하네스

```mermaid
flowchart LR
    H1["1️⃣ 정보 수집<br/>OHLCV+DART+FnGuide"] --> H2["2️⃣ 시장 해석<br/>테마+Kill Switch"]
    H2 --> H3["3️⃣ 후보 선별<br/>Stage A/B"]
    H3 --> H4["4️⃣ 포지션 비중<br/>Top10+분산cap5"]
    H4 --> H5["5️⃣ 실행 조건<br/>6단계 청산"]
    H5 --> H6["6️⃣ 사후 복기<br/>매주 3-시각"]
    H6 -.피드백 (메모리 주입).-> H2

    style H1 fill:#e7f3ff
    style H3 fill:#cce5ff
    style H4 fill:#d4edda
    style H6 fill:#ffe6cc
```

알고픽 인사이트: *"AI 투자 에이전트의 경쟁력은 모델이 아니라 하네스에서 나온다."*

---

## 7. 자동화 트리거 구조

```mermaid
flowchart TD
    subgraph WIN["윈도우 작업 스케줄러 (로컬 PC)"]
        W1["HollyKR_Scan<br/>매일 14:40 KST"] --> WC1["claude -c /daily-orchestrate<br/>(풀 자동화 6단계)"]
        W2["HollyKR_Nightly<br/>매일 18:00 KST"] --> WC2["python --nightly<br/>(ACTIVE 갱신)"]
    end

    subgraph GH["GitHub Actions (클라우드, 백업)"]
        G1["holly-daily.yml<br/>평일 14:20 KST"] --> GC1["python --auto --telegram<br/>(단순 daily-scan)"]
        G2["holly-quarterly.yml<br/>분기 1일"] --> GC2["backtest_5y.py<br/>(ALPHA pool 갱신)"]
    end

    WC1 --> TG["📱 텔레그램"]
    GC1 --> TG

    style W1 fill:#ffe6cc
    style WC1 fill:#cce5ff
    style TG fill:#fff3cd
```

---

## 8. 분기 5년 백테스트 → ALPHA pool

```mermaid
flowchart TD
    D["5년 OHLCV<br/>시총 상위 1500종목"] --> SPLIT["학습 3년 / Hold-out 1년 분리"]
    SPLIT --> LEARN["학습 윈도우 4개<br/>(정보 출력용, 게이트 X)"]
    SPLIT --> HOLD["Hold-out 단독 평가<br/>(tier 분류 게이트)"]

    HOLD --> T1{"PF≥1.5 + Sharpe≥1.0<br/>+ 거래≥30 + MDD>-50%"}
    T1 -->|Yes| ALPHA["🏆 ALPHA"]
    T1 -->|No| T2{"PF≥1.0 + Sharpe≥0.3<br/>+ 거래≥15"}
    T2 -->|Yes| CONS["✓ CONSISTENT"]
    T2 -->|No| WEAK["✗ WEAK (저장 X)"]

    ALPHA --> POOL["alpha_pool.json<br/>(repo 커밋)"]
    CONS --> POOL

    style ALPHA fill:#d4edda
    style CONS fill:#d4edda
    style WEAK fill:#f8d7da
    style POOL fill:#fff3cd
```

---

## 작업 히스토리 (주요 개선)

```mermaid
timeline
    title HollyKR Phase 진화
    Phase F : 분기 5년 백테스트 : Hold-out 검증 : ALPHA pool 자동 생성
    Phase G-6~9 : 5년 strict 검증 : Stage A/B + 부서장 일원화 : 6단계 하네스
    Phase G-10~11 : 알고픽 통합 : 시장 테마 분석 : 메모리 자동 로드 : 매주 복기 + NAV
    Phase G-12 : 시간 최적화 : Stage B Sonnet 4.6 : 사업보고서 사전 수집 : Top15 cutoff 버그 수정
```

### Phase G-12 주요 수정 내역

| 항목 | Before | After |
|---|---|---|
| Stage A→B cutoff | Top 15로 자름 (룰 위반) | **모든 시그널 평가** (룰 3 준수) |
| Stage B 모델 | Opus 4.7 | Sonnet 4.6 (속도 ↑) |
| 부서장 prompt | 467줄 | 214줄 압축 (Opus 유지) |
| 기업 개요 출처 | Sonnet 학습 데이터 | DART 사업보고서 사전 수집 |
| 자동화 | GitHub Actions만 | 윈도우 스케줄러 + Claude Code CLI |

---

> 📌 이 문서는 시각적 이해용 요약입니다. 상세 구현은 [`CLAUDE.md`](CLAUDE.md), 개요는 [`README.md`](README.md) 참조.
