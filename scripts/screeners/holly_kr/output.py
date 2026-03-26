"""
Holly AI 결과 출력 — 터미널 + CSV/JSON.
"""

import json
from datetime import datetime
from typing import List

import pandas as pd
from tabulate import tabulate

from scripts.screeners.holly_kr.signal_model import Signal
from scripts.screeners.holly_kr.config import OUTPUT_DIR


def print_signals(signals: List[Signal], limit: int = 30):
    """터미널 테이블 출력."""
    if not signals:
        print("\n  시그널 없음")
        return

    rows = []
    for s in signals[:limit]:
        supply = getattr(s, 'supply_demand_grade', '-')
        rows.append({
            '전략': s.strategy_name,
            '등급': s.grade,
            '수급': supply,
            '종목': f"{s.ticker_name}({s.ticker})",
            '섹터': s.sector[:8],
            '카테고리': s.category,
            '진입가': f"{s.entry_price:,.0f}",
            '목표': f"+{s.target_pct*100:.1f}%",
            '손절': f"{s.stop_loss_pct*100:.1f}%",
            'R:R': f"{s.rr_ratio:.1f}",
            '신뢰도': f"{s.confidence:.0%}",
            '보유': f"{s.hold_days_min}~{s.hold_days_max}일",
        })

    print(f"\n총 {len(signals)}개 시그널 (상위 {min(limit, len(signals))}개)")
    print(tabulate(rows, headers='keys', tablefmt='simple', stralign='left'))


def save_csv(signals: List[Signal]) -> str:
    if not signals:
        return ''

    today = datetime.now().strftime('%Y-%m-%d')
    filepath = OUTPUT_DIR / f'holly_{today}.csv'

    rows = []
    for s in signals:
        rows.append({
            'date': today, 'grade': s.grade, 'strategy': s.strategy_name,
            'ticker': s.ticker, 'name': s.ticker_name, 'sector': s.sector,
            'category': s.category, 'entry_price': round(s.entry_price),
            'target_price': round(s.target_price),
            'stop_loss_price': round(s.stop_loss_price),
            'target_pct': round(s.target_pct, 4),
            'stop_loss_pct': round(s.stop_loss_pct, 4),
            'rr_ratio': round(s.rr_ratio, 2),
            'confidence': round(s.confidence, 4),
            'hold_min': s.hold_days_min, 'hold_max': s.hold_days_max,
            'risk_warnings': '|'.join(s.risk_warnings),
        })

    pd.DataFrame(rows).to_csv(filepath, index=False, encoding='utf-8-sig')
    print(f"  CSV 저장: {filepath}")
    return str(filepath)


def save_json(signals: List[Signal]) -> str:
    if not signals:
        return ''

    today = datetime.now().strftime('%Y-%m-%d')
    filepath = OUTPUT_DIR / f'holly_{today}.json'

    data = {
        'date': today,
        'total_signals': len(signals),
        'signals': [
            {
                'grade': s.grade, 'strategy': s.strategy_name,
                'ticker': s.ticker, 'name': s.ticker_name,
                'sector': s.sector, 'category': s.category,
                'entry_price': round(s.entry_price),
                'target_pct': round(s.target_pct, 4),
                'stop_loss_pct': round(s.stop_loss_pct, 4),
                'rr_ratio': round(s.rr_ratio, 2),
                'confidence': round(s.confidence, 4),
                'hold_days': f"{s.hold_days_min}~{s.hold_days_max}",
                'risk_warnings': s.risk_warnings,
            }
            for s in signals
        ],
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  JSON 저장: {filepath}")
    return str(filepath)
