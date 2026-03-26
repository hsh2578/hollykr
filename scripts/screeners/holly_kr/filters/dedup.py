"""
중복 시그널 처리
"""

from typing import List

from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.config import MULTI_SIGNAL_BOOST


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

    result = []
    for ticker, sigs in by_ticker.items():
        # 3개+ 전략 동시 → 부스팅
        if len(sigs) >= 3:
            for s in sigs:
                s.confidence = min(s.confidence * MULTI_SIGNAL_BOOST, 1.0)

        # 최고 confidence 채택
        best = max(sigs, key=lambda s: s.confidence)
        if len(sigs) >= 3:
            best.risk_warnings.append(f'{len(sigs)}개전략동시')
        result.append(best)

    return result
