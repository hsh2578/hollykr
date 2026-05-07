"""
텔레그램 알림 모듈

HollyKR 시그널 발생 시 텔레그램으로 알림을 보냅니다.
텔레그램 요약 프로그램의 패턴을 참고 (python-telegram-bot, 메시지 분할, 비동기).

설정:
    .env 파일에 아래 값을 추가:
    TELEGRAM_BOT_TOKEN=123456:ABC-...
    TELEGRAM_CHAT_ID=123456789              # 단일 사용자
    TELEGRAM_CHAT_IDS=123,456,789           # 복수 사용자 (쉼표 구분)

사용법:
    from scripts.telegram_alert import send_holly_signals

    # 시그널 리스트를 텔레그램으로 전송
    await send_holly_signals(signals)

    # 또는 동기 래퍼
    send_holly_signals_sync(signals)

    # 모듈 테스트
    python -m scripts.telegram_alert
"""

import asyncio
import os
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# 설정
# ============================================================================

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
CHAT_IDS = os.getenv('TELEGRAM_CHAT_IDS', '')  # 복수 사용자

TELEGRAM_MAX_LEN = 4096


def _get_chat_ids() -> List[str]:
    """수신자 chat_id 리스트"""
    ids = []
    if CHAT_IDS:
        ids.extend([x.strip() for x in CHAT_IDS.split(',') if x.strip()])
    if CHAT_ID and CHAT_ID not in ids:
        ids.append(CHAT_ID)
    return ids


# ============================================================================
# 메시지 포맷
# ============================================================================

def _split_message(text: str, max_len: int = TELEGRAM_MAX_LEN) -> List[str]:
    """4096자 제한에 맞춰 메시지 분할 (줄바꿈 경계)"""
    if len(text) <= max_len:
        return [text]

    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        # 줄바꿈 기준으로 분할
        cut = text.rfind('\n', 0, max_len)
        if cut <= 0:
            cut = max_len
        parts.append(text[:cut])
        text = text[cut:].lstrip('\n')
    return parts


def format_signal_message(signals, market_regime: str = '',
                          active_strategies: int = 0,
                          total_strategies: int = 32,
                          strong_strategies: list = None,
                          watch_strategies: list = None) -> str:
    """시그널 리스트 -> 텔레그램 메시지.

    Phase F: ALPHA 풀 메타데이터 활용한 Tier 차별화
    - Tier 1 (5년 ALPHA): 영구 검증된 알파 (별도 표시)
    - Tier 2 (CONSISTENT/BORDERLINE): 5년 일관성 있음
    - Tier 3 (그 외): 60일 단기 적응
    """
    if not signals:
        return "HollyKR: 시그널 없음"

    strong_strategies = strong_strategies or []
    watch_strategies = watch_strategies or []

    today = datetime.now().strftime('%Y-%m-%d')
    mode = getattr(signals[0], 'entry_mode', 'open') if signals else 'open'
    entry_mode_str = '당일 종가' if mode == 'close' else '다음날 시가'

    if active_strategies == 0:
        active_strategies = len(set(s.strategy_name for s in signals))

    # ALPHA 풀에서 tier 정보 로드 (있으면)
    tier_map = {}
    try:
        from scripts.screeners.holly_kr.alpha_pool import load_alpha_pool
        pool = load_alpha_pool()
        if pool:
            tier_map = {s['name']: s for s in pool['alpha_strategies']}
    except Exception:
        pass

    # Tier 분류
    tier1_sigs = []  # 5년 ALPHA
    tier2_sigs = []  # 5년 CONSISTENT/BORDERLINE
    tier3_sigs = []  # 60일 단기 적응 (5년 미검증)

    for s in signals:
        meta = tier_map.get(s.strategy_name)
        if meta and meta.get('tier') == 'ALPHA':
            tier1_sigs.append((s, meta))
        elif meta and meta.get('tier') in ('CONSISTENT', 'BORDERLINE'):
            tier2_sigs.append((s, meta))
        else:
            tier3_sigs.append((s, None))

    # 신뢰도 순
    tier1_sigs.sort(key=lambda x: -x[0].confidence)
    tier2_sigs.sort(key=lambda x: -x[0].confidence)
    tier3_sigs.sort(key=lambda x: -x[0].confidence)

    lines = [f"HollyKR ({today})"]
    if market_regime:
        lines.append(f"시장: {market_regime}")
    lines.append(f"진입: {entry_mode_str}")

    # ALPHA 풀 표시
    if tier_map:
        n_tier1 = len(tier1_sigs)
        n_tier2 = len(tier2_sigs)
        n_tier3 = len(tier3_sigs)
        lines.append(f"5년 ALPHA {n_tier1}개 | 일관성 {n_tier2}개 | 단기적응 {n_tier3}개")
    else:
        lines.append(f"시그널 {len(signals)}개 (5년 ALPHA 풀 미생성)")

    lines.append("")

    # Tier 1: 5년 ALPHA (가장 신뢰)
    if tier1_sigs:
        lines.append("=== 🏆 5년 검증 ALPHA ===")
        for s, meta in tier1_sigs[:5]:
            sig_lines = _format_one_signal(s)
            # ALPHA 메타 추가
            if meta:
                sig_lines.insert(-1, f"  [5년 PF {meta['holdout_pf']:.2f} | "
                                     f"Sharpe {meta['holdout_sharpe']:.2f} | "
                                     f"Hold-out 검증 ✓]")
            lines.extend(sig_lines)

    # Tier 2: CONSISTENT/BORDERLINE
    if tier2_sigs:
        lines.append("=== 🟢 5년 일관성 PASS ===")
        for s, meta in tier2_sigs[:5]:
            sig_lines = _format_one_signal(s)
            if meta:
                sig_lines.insert(-1, f"  [5년 PF {meta['holdout_pf']:.2f} | "
                                     f"Sharpe {meta['holdout_sharpe']:.2f}]")
            lines.extend(sig_lines)

    # Tier 3: 단기 적응 (5년 미검증)
    if tier3_sigs:
        if tier_map:
            lines.append("=== 🟡 60일 단기 적응 ===")
        for s, _ in tier3_sigs[:8]:
            lines.extend(_format_one_signal(s))

    lines.append("─────────────────────")
    if tier_map:
        lines.append("※ 🏆 = 5년 cross-regime + Hold-out 1년 검증")
        lines.append("※ 🟢 = 5년 일관성 (Sharpe 1.0+)")
        lines.append("※ 🟡 = 최근 60일 시장 적응 (5년 미검증)")
    lines.append("투자 결정은 본인의 판단과 책임입니다.")
    return '\n'.join(lines)


def _format_one_signal(s) -> list:
    """개별 시그널 포맷 (3~4줄)"""
    supply = getattr(s, 'supply_demand_grade', '')
    sig_mode = getattr(s, 'entry_mode', 'open')
    entry_label = '종가' if sig_mode == 'close' else '시가'
    sector_str = f" | {s.sector}" if s.sector else ''

    target_price = s.entry_price * (1 + s.target_pct)
    stop_price = s.entry_price * (1 + s.stop_loss_pct)

    # 중복 전략 수 표시
    overlap = ''
    warnings_filtered = []
    for w in (s.risk_warnings or []):
        if '개전략' in w:
            overlap = f" | {w}"
        else:
            warnings_filtered.append(w)

    # 현재가 표시 (있으면 진입가 대비 변동률 함께)
    current_price = getattr(s, 'current_price', 0) or 0
    if current_price > 0 and s.entry_price > 0:
        change_pct = (current_price - s.entry_price) / s.entry_price * 100
        sign = '+' if change_pct >= 0 else ''
        price_line = (f"  진입: {s.entry_price:,.0f}원({entry_label}) | "
                      f"현재: {current_price:,.0f}원 ({sign}{change_pct:.1f}%)")
    else:
        price_line = f"  진입: {s.entry_price:,.0f}원({entry_label})"

    pos_pct = getattr(s, 'position_size_pct', 0) or 0
    pos_line = f" | 권장 포지션 {pos_pct*100:.1f}%" if pos_pct > 0 else ""

    lines = [
        f"[{s.strategy_name}] {s.ticker_name}({s.ticker}){sector_str}",
        price_line,
        f"  목표: {target_price:,.0f}원(+{s.target_pct*100:.1f}%) | 손절: {stop_price:,.0f}원(-{abs(s.stop_loss_pct)*100:.1f}%){pos_line}",
        f"  신뢰도 {s.confidence:.0%} | 수급 {supply or '-'}{overlap}",
    ]

    # 매수 이유 (있으면 표시)
    reason = getattr(s, 'reason', '')
    if reason:
        lines.append(f"  사유: {reason}")

    if warnings_filtered:
        lines.append(f"  [!] {', '.join(warnings_filtered)}")
    lines.append("")
    return lines

    return '\n'.join(lines)


# ============================================================================
# 전송
# ============================================================================

async def send_message(text: str, chat_id: Optional[str] = None):
    """단일 메시지 전송 (비동기)"""
    try:
        from telegram import Bot
    except ImportError:
        print("python-telegram-bot 미설치: pip install python-telegram-bot")
        return False

    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN 미설정")
        return False

    bot = Bot(token=BOT_TOKEN)
    target_ids = [chat_id] if chat_id else _get_chat_ids()

    if not target_ids:
        print("TELEGRAM_CHAT_ID 또는 TELEGRAM_CHAT_IDS 미설정")
        return False

    parts = _split_message(text)
    success = True

    for tid in target_ids:
        for part in parts:
            try:
                await bot.send_message(chat_id=tid, text=part)
            except Exception as e:
                print(f"텔레그램 전송 실패 (chat_id={tid}): {e}")
                success = False

    return success


async def send_holly_signals(signals, market_regime: str = '',
                             active_strategies: int = 0,
                             total_strategies: int = 32,
                             strong_strategies: list = None,
                             watch_strategies: list = None):
    """HollyKR 시그널을 텔레그램으로 전송"""
    msg = format_signal_message(signals, market_regime=market_regime,
                                active_strategies=active_strategies,
                                total_strategies=total_strategies,
                                strong_strategies=strong_strategies,
                                watch_strategies=watch_strategies)
    return await send_message(msg)


def send_holly_signals_sync(signals, market_regime: str = '',
                            active_strategies: int = 0,
                            total_strategies: int = 32,
                            strong_strategies: list = None,
                            watch_strategies: list = None):
    """동기 래퍼"""
    return asyncio.run(send_holly_signals(signals, market_regime=market_regime,
                                          active_strategies=active_strategies,
                                          total_strategies=total_strategies,
                                          strong_strategies=strong_strategies,
                                          watch_strategies=watch_strategies))


# ============================================================================
# 모듈 테스트
# ============================================================================

if __name__ == '__main__':
    print("텔레그램 알림 모듈 테스트")
    print("=" * 40)

    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN 미설정 - .env 파일을 확인하세요")
        print("\n메시지 포맷 테스트:")

        # Mock 시그널로 포맷 테스트
        from dataclasses import dataclass, field

        @dataclass
        class MockSignal:
            grade: str = 'A'
            strategy_name: str = 'engulfing'
            ticker: str = '005930'
            ticker_name: str = '삼성전자'
            sector: str = '반도체'
            category: str = 'breakout'
            entry_price: float = 70500
            target_pct: float = 0.04
            stop_loss_pct: float = -0.03
            rr_ratio: float = 1.33
            confidence: float = 0.65
            hold_days_min: int = 1
            hold_days_max: int = 3
            supply_demand_grade: str = 'A'
            entry_mode: str = 'open'
            risk_warnings: list = field(default_factory=list)

        mock_signals = [
            MockSignal(),
            MockSignal(grade='B', strategy_name='minervini_trend_template',
                       ticker='000660', ticker_name='SK하이닉스',
                       sector='반도체', category='legendary',
                       entry_price=185000, target_pct=0.15, stop_loss_pct=-0.08,
                       rr_ratio=1.88, confidence=0.72, hold_days_min=10, hold_days_max=60,
                       supply_demand_grade='B'),
            MockSignal(grade='A', strategy_name='pushing_the_spring',
                       ticker='035720', ticker_name='카카오',
                       sector='소프트웨어', category='support_bounce',
                       entry_price=52300, target_pct=0.06, stop_loss_pct=-0.04,
                       rr_ratio=1.5, confidence=0.70, hold_days_min=2, hold_days_max=5,
                       supply_demand_grade='A',
                       risk_warnings=['외국인+기관 동반매도']),
        ]

        msg = format_signal_message(mock_signals,
                                    market_regime='상승장_저변동',
                                    active_strategies=8,
                                    total_strategies=32)
        print(msg)
    else:
        print(f"BOT_TOKEN: ...{BOT_TOKEN[-10:]}")
        print(f"CHAT_IDS: {_get_chat_ids()}")
        asyncio.run(send_message("HollyKR 텔레그램 알림 테스트"))
        print("전송 완료")
