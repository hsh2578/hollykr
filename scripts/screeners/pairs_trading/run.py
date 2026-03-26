"""
페어 트레이딩 스크리너 CLI

사용법:
    python -m scripts.screeners.pairs_trading.run                    # 기본 실행
    python -m scripts.screeners.pairs_trading.run --csv --json       # 파일 저장
    python -m scripts.screeners.pairs_trading.run --signal ENTRY_STRONG
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.screeners.pairs_trading.signals import screen_pairs
from scripts.screeners.pairs_trading.output import (
    print_table, print_summary, save_csv, save_json
)


def main():
    parser = argparse.ArgumentParser(
        description='국내 주식 페어 트레이딩 스크리너 v1.0'
    )
    parser.add_argument('--csv', action='store_true', help='CSV 파일 저장')
    parser.add_argument('--json', action='store_true', help='JSON 파일 저장')
    parser.add_argument('--signal', type=str, default=None,
                        choices=['ENTRY_STRONG', 'WATCH', 'EXIT', 'STOP', 'HOLD'],
                        help='특정 시그널만 표시')
    args = parser.parse_args()

    print("=" * 60)
    print("  국내 주식 페어 트레이딩 스크리너 v1.0")
    print("  Engle-Granger 공적분 기반 Statistical Arbitrage")
    print("=" * 60)

    start_time = time.time()
    signals = screen_pairs()
    elapsed = time.time() - start_time

    print_table(signals, signal_filter=args.signal)
    print_summary(signals)

    if args.csv:
        save_csv(signals)
    if args.json:
        save_json(signals)

    print(f"\n실행 시간: {elapsed:.1f}초")


if __name__ == '__main__':
    main()
