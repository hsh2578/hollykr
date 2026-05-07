"""HollyKR 서브에이전트 (Phase 10).

기술적 시그널을 보강하는 룰 기반 에이전트 4종:
- Macro Agent: 시장 환경 평가 → confidence × 0.5~1.0
- Theme Agent: 핫 테마 매칭 + 알고픽 Top 3 발굴
- Risk Agent: 종목별 위험 점검
- Postmortem Agent: 매일 결과 추적 + 주간 리포트

설계 원칙:
1. 시그널 생성은 항상 기술적 분석에서만
2. 에이전트는 시그널을 거르거나 가중치 부여만 (생성 X)
3. 룰 80% + LLM 20% (현재는 100% 룰 기반)
4. 결정적 (deterministic), 백테스트 가능
"""
