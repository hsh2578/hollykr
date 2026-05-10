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
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows cp949 → UTF-8 강제 (한글 + 유니코드 특수문자 출력 안정성)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.screeners.holly_kr.scanner import run_scanner
from scripts.screeners.holly_kr.output import print_signals, save_csv, save_json

# Phase 7: 37개 전략 모두 영구 후보. 매일 nightly_selector가 ACTIVE 자동 선정.
# 워크포워드 검증된 진짜 알파 (4 윈도우 누적, PF 95% CI 하한 > 1.0):
#   - wake_up_call:    4/4 PASS, 거래 330, PF 1.55 [CI 1.17~2.03]
#   - close_to_a_cross: 3/4 PASS, 거래  80, PF 1.89 [CI 1.06~3.22]
#   - box_range_watch:  4/4 PASS, 거래 203, PF 2.27 [CI 1.65~3.11] ⭐ 최강
#
# BORDERLINE (CI는 좋지만 윈도우 일관성 부족):
#   - ma_convergence:        2/4 PASS, PF 1.56 [CI 1.09~2.24]
#   - new_high_52w_approach: 2/4 PASS, PF 1.84 [CI 0.79~3.67]
#
# STRONG/WATCH 분류는 텔레그램 표시용 fallback (nightly 결과 + alpha_pool 모두 없을 때만 사용)
# Phase G-4 갱신 2026-05-08: 5년 strict (학습 2년 + Hold-out 3년) 검증 후 ALPHA pool
# 4년 baseline의 tailwind ALPHA는 5년 strict에서 PF 1.04 (강세장 운빨) → 제외
WORKFLOW_PROVEN = ['ma_convergence', 'new_high_52w_approach']
FALLBACK_STRONG = WORKFLOW_PROVEN
FALLBACK_WATCH = ['close_to_a_cross', 'tailwind', 'quarterback',
                  'clenow_momentum', 'donchian_breakout', 'aqr_tsmom',
                  'weinstein_stage', 'wake_up_call', 'darvas_box', 'volume_doesnt_lie']

# 호환성 유지 (legacy 코드용 — 실제 사용 X)
STRONG_STRATEGIES = FALLBACK_STRONG
WATCH_STRATEGIES = FALLBACK_WATCH
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
        # Phase G-7 야간 모드: 전체 ALL_STRATEGIES 평가 → ALPHA pool 보존 + 시장 적응 Top 3
        # 스캔 X (시그널 송출 X). 다음날 14:20 daily-scan이 ACTIVE 사용.
        from scripts.screeners.holly_kr.nightly_selector import select_strategies
        from scripts.screeners.holly_kr.active_strategies import save_active
        from scripts.screeners.holly_kr.scanner import ALL_STRATEGIES
        from scripts.screeners.holly_kr.universe import get_universe
        from scripts.ohlcv_data import get_ohlcv

        all_strategies = list(ALL_STRATEGIES)
        print(f"\n[Phase G-7 Nightly] {len(all_strategies)}개 전략 평가 → ALPHA + 시장 적응 Top 3")

        # 유니버스 + OHLCV 로드 (시총 상위 1500 종목 — Phase F 정통)
        universe = get_universe()
        sample_size = 1500
        if len(universe) > sample_size:
            universe = universe.nlargest(sample_size, 'MarketCap').reset_index(drop=True)
        print(f"  유니버스: 시총 상위 {len(universe)}개")

        # Stage 2 필터(200일 SMA 필요) + 180일 lookback → 최소 500일 데이터
        # Phase G-6 fix: 220일 → 500일 (180일 lookback 위해)
        ohlcv_dict = {}
        for _, row in universe.iterrows():
            ticker = row['Code']
            df = get_ohlcv(ticker, days=500, use_cache=True)
            if df is not None and len(df) > 250:
                ohlcv_dict[ticker] = df
        print(f"  OHLCV 로드: {len(ohlcv_dict)}개 종목 (500일 = 200 Stage2 + 180 lookback + 120 buffer)")

        # 전체 전략 평가 → ALPHA 풀 보존 + 시장 적응 Top 3 (max_active=5 cap)
        selected, metrics = select_strategies(
            all_strategies, ohlcv_dict, universe,
            lookback=60, max_active=5, min_active=2,
        )
        active_names = [s.name for s in selected]
        save_active(active_names, metrics_summary={
            m.strategy_name: {
                'score': round(m.composite_score, 3),
                'pf': round(m.profit_factor, 2),
                'wr': round(m.win_rate, 3),
                'n': m.signal_count,
            } for m in metrics
        })
        print(f"\n[완료] ACTIVE 저장: {len(active_names)}개 → 다음날 14:20 daily-scan 사용")
        signals = []  # 스캔 안 함

    elif args.auto:
        # 자동 모드 (Phase 5): 야간 ACTIVE 결과 로드 → 해당 전략만 스캔
        # 32개 전체 후보 → 일별 점수 기반 Top 10 선정 → 그것만 스캔
        from scripts.screeners.holly_kr.active_strategies import load_active
        active_names = load_active()
        if not active_names:
            print("  야간 ACTIVE 결과 없음 → 워크포워드 검증 PROVEN 사용")
            active_names = WORKFLOW_PROVEN + FALLBACK_WATCH
        else:
            print(f"  야간 ACTIVE 사용: {active_names}")

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
    # Phase 5: ACTIVE 상위 30% = STRONG, 나머지 = WATCH (동적)
    if args.auto:
        # 야간 ACTIVE는 점수순 정렬되어 있음. 상위 30% = STRONG
        from scripts.screeners.holly_kr.active_strategies import load_active
        active_names_ordered = load_active() or (WORKFLOW_PROVEN + FALLBACK_WATCH)
        strong_cutoff = max(2, len(active_names_ordered) * 3 // 10)
        dynamic_strong = set(active_names_ordered[:strong_cutoff])
        dynamic_watch = set(active_names_ordered[strong_cutoff:])
    else:
        # 자동 모드 아닐 때는 fallback 사용
        dynamic_strong = set(FALLBACK_STRONG)
        dynamic_watch = set(FALLBACK_WATCH)

    # Phase G-9: 전략별 시그널 Top N cutoff
    # - clenow_momentum: Top 10 (사용자 명시 — 너무 헐렁함)
    # - 기타: Top 40 (40개 이상 추천 = 신뢰도 ↓, 사용자 정확)
    SPECIFIC_STRATEGY_CAP = {
        'clenow_momentum': 10,
    }
    DEFAULT_STRATEGY_CAP = 40
    from collections import Counter
    strategy_counts = Counter(s.strategy_name for s in signals)
    for strategy_name, n in strategy_counts.items():
        max_n = SPECIFIC_STRATEGY_CAP.get(strategy_name, DEFAULT_STRATEGY_CAP)
        if n > max_n:
            strat_sigs = sorted(
                [s for s in signals if s.strategy_name == strategy_name],
                key=lambda s: -s.confidence,
            )
            keep_tickers = set(s.ticker for s in strat_sigs[:max_n])
            removed = n - max_n
            signals = [s for s in signals
                       if s.strategy_name != strategy_name or s.ticker in keep_tickers]
            print(f"  [{strategy_name}] {n}개 → Top {max_n} ({removed}개 제거)")

    # 신뢰도 정렬만 (전체 시그널 cutoff X — sub-agent 평가용)
    signals.sort(key=lambda s: -s.confidence)

    for sig in signals:
        if sig.strategy_name in dynamic_strong:
            sig.signal_tier = 'STRONG'
        elif sig.strategy_name in dynamic_watch:
            sig.signal_tier = 'WATCH'
        else:
            sig.signal_tier = 'WATCH'  # 분류 외 모두 WATCH

    # ========================================================================
    # Phase G-9: 4 룰 에이전트 완전 제거 + cutoff 제거
    # 사용자 명시:
    # - 4 룰 에이전트 (Macro/Theme/Risk/Postmortem) 모두 제거
    # - cutoff X — ACTIVE 5 전략에서 나온 모든 시그널 sub-agent 평가
    # - 부서장 reasoning → Top 10 (sub-agent 평가 결과 기반)
    # ========================================================================
    algopick_picks = []  # backward compat (텔레그램 형식)

    # 신뢰도 정렬만 (cutoff X — 모든 시그널 sub-agent 평가)
    signals.sort(key=lambda s: -s.confidence)

    # 최종 시그널에 KIS 실시간 현재가 붙이기
    try:
        from scripts.kis_price import get_current_price
        for sig in signals:
            cp = get_current_price(sig.ticker)
            if cp:
                sig.current_price = cp
    except Exception as e:
        print(f"  [현재가 조회 실패] {e}")

    print_signals(signals)

    if args.csv:
        save_csv(signals)
    if args.json:
        save_json(signals)

    # Phase G-9: signals_today.json 자동 저장 (sub-agent 입력용)
    # Claude Code에서 sub-agent + 부서장이 이 JSON을 읽어 평가
    try:
        import json as _json
        from scripts.screeners.holly_kr.exit_rules_text import (
            generate_exit_rules_text, generate_exit_rules_summary,
        )
        signals_today_path = 'data/holly_kr/signals_today.json'
        os.makedirs(os.path.dirname(signals_today_path), exist_ok=True)
        signals_data = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'count': len(signals),
            'signals': [
                {
                    'ticker': s.ticker,
                    'name': getattr(s, 'ticker_name', s.ticker),
                    'sector': getattr(s, 'sector', ''),
                    'strategy_name': s.strategy_name,
                    'category': getattr(s, 'category', ''),
                    'entry_price': float(s.entry_price),
                    'current_price': float(getattr(s, 'current_price', s.entry_price) or s.entry_price),
                    'target_price': float(s.target_price),
                    'stop_loss_price': float(s.stop_loss_price),
                    'target_pct': float(s.target_pct),
                    'stop_loss_pct': float(s.stop_loss_pct),
                    'rr_ratio': float(s.rr_ratio),
                    'confidence': float(s.confidence),
                    'signal_tier': getattr(s, 'signal_tier', 'WATCH'),
                    'reason': getattr(s, 'reason', ''),
                    'hold_days_max': int(getattr(s, 'hold_days_max', 10)),
                    # 매도 룰 (전략별 동적 생성)
                    'exit_rules_text': generate_exit_rules_text(s),
                    'exit_rules_summary': generate_exit_rules_summary(s),
                } for s in signals
            ],
        }
        with open(signals_today_path, 'w', encoding='utf-8') as f:
            _json.dump(signals_data, f, ensure_ascii=False, indent=2)
        print(f"  [signals_today.json] {len(signals)}개 시그널 저장 → {signals_today_path}")
    except Exception as e:
        print(f"  [signals_today.json 저장 오류] {e}")

    if args.telegram:
        from scripts.telegram_alert import send_holly_signals_sync, send_message
        import asyncio
        market_regime = ''
        kill_switch_active = False
        kill_reasons = []
        try:
            from scripts.screeners.holly_kr.filters.market_filter import get_market_regime
            regime_info = get_market_regime()
            market_regime = regime_info.get('regime', '')
            kill_switch_active = regime_info.get('kill_switch', False)
            kill_reasons = regime_info.get('kill_reasons', [])
        except Exception:
            pass

        # Phase 6+: Kill Switch 발동 시 경고 메시지 먼저 송출 (시그널은 별도로 계속 송출)
        if kill_switch_active:
            today = datetime.now().strftime('%Y-%m-%d')
            warn_msg = (
                f"[!] HollyKR Kill Switch 발동 ({today})\n"
                f"시장 레짐: {market_regime}\n"
                f"---\n"
                f"발동 사유:\n"
                + "\n".join(f"  - {r}" for r in kill_reasons) + "\n"
                f"---\n"
                f"※ 아래 시그널은 *참고용*입니다. 매수 비권장.\n"
                f"   강한 하락/패닉 추세에서 매수는 통계적으로 손해입니다.\n"
                f"   보유 포지션 손절 점검 권장."
            )
            print("\n[Kill Switch ACTIVE — 경고 + 시그널 참고용 송출]")
            for r in kill_reasons:
                print(f"  - {r}")
            asyncio.run(send_message(warn_msg))

        total_strats = len(PROVEN_STRATEGIES) if args.proven else 32
        active_strats = len(set(s.strategy_name for s in signals))

        # 시그널 송출 (Kill Switch 활성 여부 무관, 항상 보냄)
        if signals:
            # Kill Switch 활성 시 레짐에 [참고용] 태그 추가
            display_regime = (
                f"{market_regime} [참고용 / 매수 비권장]"
                if kill_switch_active else market_regime
            )
            print("\n텔레그램 알림 전송 중...")
            send_holly_signals_sync(
                signals, market_regime=display_regime,
                active_strategies=active_strats,
                total_strategies=total_strats,
                strong_strategies=list(dynamic_strong),
                watch_strategies=list(dynamic_watch),
            )
        else:
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
