"""
결과 출력

터미널 테이블 + CSV/JSON 파일 저장.
"""

import json
from datetime import datetime

import pandas as pd
from tabulate import tabulate

from scripts.screeners.pairs_trading.signals import PairSignal
from scripts.screeners.pairs_trading.config import OUTPUT_DIR


def _signal_to_row(s: PairSignal) -> dict:
    if s.direction == 'LONG_A':
        long_target = f"{s.name_a}({s.stock_a})"
    elif s.direction == 'LONG_B':
        long_target = f"{s.name_b}({s.stock_b})"
    else:
        long_target = '-'

    return {
        '등급': s.grade,
        '종목A': f"{s.name_a}({s.stock_a})",
        '종목B': f"{s.name_b}({s.stock_b})",
        '섹터': s.sector,
        'β': f"{s.beta:.2f}",
        'ADF_p': f"{s.adf_pvalue:.4f}",
        '안정성': f"{s.stability_pct:.0f}%",
        '반감기': f"{s.half_life:.1f}일",
        'Z_fast': f"{s.zscore.z_fast:+.2f}",
        'Z_main': f"{s.zscore.z_main:+.2f}",
        'Z_slow': f"{s.zscore.z_slow:+.2f}",
        '시그널': s.signal,
        '매수대상': long_target,
        '기대수익': f"{s.expected_return:.2f}%",
        '위험': ', '.join(s.risk_warnings) if s.risk_warnings else '-',
    }


def print_table(signals: list, signal_filter: str = None):
    print("\n[7/7] 결과 출력")
    print("=" * 50)

    if signal_filter:
        signals = [s for s in signals if s.signal == signal_filter]

    if not signals:
        print("  표시할 시그널 없음")
        return

    rows = [_signal_to_row(s) for s in signals]
    print(f"\n총 {len(signals)}쌍")
    print(tabulate(rows, headers='keys', tablefmt='simple', stralign='left'))


def print_summary(signals: list, total_pairs: int = 0,
                  coint_pass: int = 0, stable_pass: int = 0):
    print("\n" + "=" * 50)
    print("통계 요약")
    print("=" * 50)
    if total_pairs:
        print(f"  총 스캔 쌍:      {total_pairs:,}")
    if coint_pass:
        print(f"  공적분 통과:     {coint_pass}")
    if stable_pass:
        print(f"  안정성 통과:     {stable_pass}")
    print(f"  활성 시그널:     {len(signals)}")

    signal_counts = {}
    for s in signals:
        signal_counts[s.signal] = signal_counts.get(s.signal, 0) + 1
    for sig_type in ['ENTRY_STRONG', 'WATCH', 'STOP', 'EXIT', 'HOLD']:
        count = signal_counts.get(sig_type, 0)
        if count:
            print(f"    {sig_type}: {count}")

    grade_counts = {}
    for s in signals:
        grade_counts[s.grade] = grade_counts.get(s.grade, 0) + 1
    print(f"  등급 분포: " + ", ".join(f"{g}={c}" for g, c in sorted(grade_counts.items())))


def save_csv(signals: list) -> str:
    if not signals:
        return ''

    today = datetime.now().strftime('%Y-%m-%d')
    filepath = OUTPUT_DIR / f'pairs_{today}.csv'

    rows = []
    for s in signals:
        rows.append({
            'date': today, 'grade': s.grade,
            'stock_a': s.stock_a, 'name_a': s.name_a,
            'stock_b': s.stock_b, 'name_b': s.name_b,
            'sector': s.sector,
            'beta': round(s.beta, 4), 'adf_pvalue': round(s.adf_pvalue, 4),
            'stability_pct': round(s.stability_pct, 1),
            'half_life': round(s.half_life, 1),
            'z_fast': round(s.zscore.z_fast, 4),
            'z_main': round(s.zscore.z_main, 4),
            'z_slow': round(s.zscore.z_slow, 4),
            'signal': s.signal, 'direction': s.direction,
            'expected_return': round(s.expected_return, 4),
            'risk_warnings': '|'.join(s.risk_warnings),
        })

    df = pd.DataFrame(rows)
    df.to_csv(filepath, index=False, encoding='utf-8-sig')
    print(f"  CSV 저장: {filepath}")
    return str(filepath)


def save_json(signals: list) -> str:
    if not signals:
        return ''

    today = datetime.now().strftime('%Y-%m-%d')
    filepath = OUTPUT_DIR / f'pairs_{today}.json'

    data = {'date': today, 'total_pairs': len(signals), 'pairs': []}

    for s in signals:
        data['pairs'].append({
            'grade': s.grade,
            'stock_a': {'code': s.stock_a, 'name': s.name_a},
            'stock_b': {'code': s.stock_b, 'name': s.name_b},
            'sector': s.sector,
            'cointegration': {'beta': round(s.beta, 4), 'adf_pvalue': round(s.adf_pvalue, 4)},
            'stability': {'pct': round(s.stability_pct, 1), 'half_life': round(s.half_life, 1)},
            'zscore': {
                'fast': round(s.zscore.z_fast, 4),
                'main': round(s.zscore.z_main, 4),
                'slow': round(s.zscore.z_slow, 4),
            },
            'signal': s.signal, 'direction': s.direction,
            'expected_return': round(s.expected_return, 4),
            'risk_warnings': s.risk_warnings,
        })

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  JSON 저장: {filepath}")
    return str(filepath)
