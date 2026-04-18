"""
중복 시그널 처리
"""

from typing import List

from scripts.screeners.holly_kr.signal_model import Signal


def dedup_signals(signals: List[Signal]) -> List[Signal]:
    """
    동일 종목 다중 시그널 처리.

    1. 동일 종목 → confidence 가장 높은 것 1개 채택
    2. 3개 이상 전략이 동시에 가리키면 confidence × 1.3 부스팅
    """
    # 종목별 그룹핑
    by_ticker = {}
    for sig in signals:
        by_ticker.setdefault(sig.ticker, []).append(sig)

    # 전략 수별 부스트 배율 (보수적)
    BOOST_MAP = {3: 1.1, 4: 1.15, 5: 1.2}
    BOOST_MAX = 1.25  # 6개+

    result = []
    for ticker, sigs in by_ticker.items():
        n = len(sigs)
        if n >= 3:
            boost = BOOST_MAP.get(n, BOOST_MAX)
            for s in sigs:
                s.confidence = min(s.confidence * boost, 0.95)

        best = max(sigs, key=lambda s: s.confidence)
        best.risk_warnings.append(f'{n}개전략' if n < 3 else f'{n}개전략동시')
        result.append(best)

    return result
