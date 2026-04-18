"""
HollyKR 스크리너 CLI

사용법:
    # 실전 모드 (검증된 9개 전략, 종가매매, 텔레그램)
    python -m scripts.screeners.holly_kr.run --proven --entry close --telegram

    # 전체 스캔
    python -m scripts.screeners.holly_kr.run                         # 32개 전략
    python -m scripts.screeners.holly_kr.run --entry close           # 종가 매수
    python -m scripts.screeners.holly_kr.run --csv --json            # 파일 저장
    python -m scripts.screeners.holly_kr.run --strategy tailwind     # 특정 전략만
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.screeners.holly_kr.scanner import run_scanner
from scripts.screeners.holly_kr.output import print_signals, save_csv, save_json

# 백테스트 검증 전략 (200일, ATR 기반, 종가매매, 슬리피지+거래비용 포함)
# 기준: PF 1.0+ AND 총수익 10%+
# [강력 매수] PF 1.2+
STRONG_STRATEGIES = ['close_to_a_cross', 'weinstein_stage', 'tailwind', 'wake_up_call']

# [관심 종목] PF 1.05~1.2 AND 총수익 10%+
WATCH_STRATEGIES = ['darvas_box', 'volume_doesnt_lie', 'staggering_volume',
                    'quarterback', 'trend_play', 'nice_chart']

# 실전 모드 전체 (강력 + 관심)
PROVEN_STRATEGIES = STRONG_STRATEGIES + WATCH_STRATEGIES


def main():
    parser = argparse.ArgumentParser(
        description='HollyKR 퀀트 전략 스크리너 v2.0'
    )
    parser.add_argument('--csv', action='store_true', help='CSV 파일 저장')
    parser.add_argument('--json', action='store_true', help='JSON 파일 저장')
    parser.add_argument('--telegram', action='store_true', help='텔레그램 알림 전송')
    parser.add_argument('--strategy', type=str, default=None,
                        help='특정 전략만 (전략명)')
    parser.add_argument('--phase', type=str, default='all',
                        choices=['all', 'phase1', 'phase2'],
                        help='실행할 Phase')
    parser.add_argument('--entry', type=str, default='close',
                        choices=['open', 'close'],
                        help='진입: open=다음날 시가, close=당일 종가 (기본: close)')
    parser.add_argument('--select', action='store_true',
                        help='야간 전략 선정 (최근 60일 백테스트 기반)')
    parser.add_argument('--proven', action='store_true',
                        help='실전 모드 - 검증된 9개 전략만 (강력 3 + 관심 6)')
    parser.add_argument('--nightly', action='store_true',
                        help='야간 모드 - 전략 선정 + 결과 저장 (18:00 실행용)')
    parser.add_argument('--auto', action='store_true',
                        help='자동 모드 - 야간 선정 결과 로드 → 스캔 → 텔레그램 (14:40 실행용)')

    args = parser.parse_args()

    entry_desc = '다음날 시가' if args.entry == 'open' else '당일 종가(15:20 전)'

    # --nightly: 야간 전략 선정 + 저장 (18:00)
    if args.nightly:
        mode_desc = '야간 전략 선정 (결과 저장)'
    # --auto: 야간 결과 로드 + 스캔 + 텔레그램 (14:40)
    elif args.auto:
        mode_desc = '자동 모드 (야간 선정 결과 사용)'
    elif args.proven:
        mode_desc = f'실전 모드: 강력 {len(STRONG_STRATEGIES)}개 + 관심 {len(WATCH_STRATEGIES)}개'
    elif args.select:
        mode_desc = '야간 전략 선정'
    else:
        phase_desc = {'all': '32개 전략', 'phase1': 'EOD 12개', 'phase2': 'HYBRID 20개'}
        mode_desc = phase_desc.get(args.phase, args.phase)

    print("=" * 60)
    print("  HollyKR 퀀트 전략 스크리너 v2.0")
    print(f"  {mode_desc}")
    print(f"  진입: {entry_desc}")
    print("=" * 60)

    start_time = time.time()

    if args.nightly:
        # 야간 모드: 전략 선정 + 결과 저장 + 전체 스캔 (CSV 기록용)
        signals = run_scanner(
            phase=args.phase,
            entry_mode=args.entry,
            use_nightly_selection=True,
        )
        # 활성 전략 저장
        from scripts.screeners.holly_kr.active_strategies import save_active
        active_names = list(set(s.strategy_name for s in signals))
        # PROVEN 전략은 항상 포함
        for name in PROVEN_STRATEGIES:
            if name not in active_names:
                active_names.append(name)
        save_active(active_names)

    elif args.auto:
        # 자동 모드: 야간 결과 로드 → 해당 전략만 스캔
        from scripts.screeners.holly_kr.active_strategies import load_active
        active_names = load_active()
        if not active_names:
            print("  야간 선정 결과 없음 → 기본 PROVEN 전략 사용")
            active_names = PROVEN_STRATEGIES

        signals = run_scanner(
            phase=args.phase,
            entry_mode=args.entry,
        )
        signals = [s for s in signals if s.strategy_name in active_names]

    else:
        signals = run_scanner(
            phase=args.phase,
            entry_mode=args.entry,
            use_nightly_selection=args.select and not args.proven,
        )
        if args.proven:
            signals = [s for s in signals if s.strategy_name in PROVEN_STRATEGIES]
        elif args.strategy:
            signals = [s for s in signals if s.strategy_name == args.strategy]

    elapsed = time.time() - start_time

    # 강력/관심 분류 + 캡 적용 (강력 우선, 관심으로 채워서 총 10개)
    strong = [s for s in signals if s.strategy_name in STRONG_STRATEGIES]
    watch = [s for s in signals if s.strategy_name in WATCH_STRATEGIES]
    strong.sort(key=lambda s: -s.confidence)
    watch.sort(key=lambda s: -s.confidence)
    strong_cap = strong[:5]
    signals = strong_cap + watch[:10 - len(strong_cap)]

    for sig in signals:
        if sig.strategy_name in STRONG_STRATEGIES:
            sig.signal_tier = 'STRONG'
        else:
            sig.signal_tier = 'WATCH'

    print_signals(signals)

    if args.csv:
        save_csv(signals)
    if args.json:
        save_json(signals)

    if args.telegram:
        from scripts.telegram_alert import send_holly_signals_sync
        market_regime = ''
        try:
            from scripts.screeners.holly_kr.filters.market_filter import get_market_regime
            regime_info = get_market_regime()
            market_regime = regime_info.get('regime', '')
        except Exception:
            pass

        total_strats = len(PROVEN_STRATEGIES) if args.proven else 32
        active_strats = len(set(s.strategy_name for s in signals))

        if signals:
            print("\n텔레그램 알림 전송 중...")
            send_holly_signals_sync(
                signals, market_regime=market_regime,
                active_strategies=active_strats,
                total_strategies=total_strats,
                strong_strategies=STRONG_STRATEGIES,
                watch_strategies=WATCH_STRATEGIES,
            )
        else:
            from scripts.telegram_alert import send_message
            import asyncio
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            no_signal_msg = (
                f"HollyKR ({today})\n"
                f"시장 레짐: {market_regime or '확인중'}\n"
                f"---\n"
                f"오늘은 시그널이 없습니다."
            )
            print("\n텔레그램 알림 (시그널 없음)...")
            asyncio.run(send_message(no_signal_msg))

    from scripts.ohlcv_data import flush_cache
    flush_cache()

    print(f"\n실행 시간: {elapsed:.1f}초")


if __name__ == '__main__':
    main()
