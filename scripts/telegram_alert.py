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
    """시그널 리스트 -> 텔레그램 메시지 (강력/관심 2단계 포맷)"""
    if not signals:
        return "HollyKR: 시그널 없음"

    strong_strategies = strong_strategies or []
    watch_strategies = watch_strategies or []

    today = datetime.now().strftime('%Y-%m-%d')

    # 진입 모드
    mode = getattr(signals[0], 'entry_mode', 'open') if signals else 'open'
    entry_mode_str = '당일 종가' if mode == 'close' else '다음날 시가'

    if active_strategies == 0:
        active_strategies = len(set(s.strategy_name for s in signals))

    # 강력/관심 분류
    strong_sigs = [s for s in signals if s.strategy_name in strong_strategies]
    watch_sigs = [s for s in signals if s.strategy_name in watch_strategies]
    other_sigs = [s for s in signals if s.strategy_name not in strong_strategies
                  and s.strategy_name not in watch_strategies]

    # 각 그룹 내 신뢰도 순 정렬
    strong_sigs.sort(key=lambda s: -s.confidence)
    watch_sigs.sort(key=lambda s: -s.confidence)

    lines = [
        f"HollyKR ({today})",
    ]
    if market_regime:
        lines.append(f"시장: {market_regime}")
    lines.extend([
        f"강력 {len(strong_sigs)}개 | 관심 {len(watch_sigs)}개",
        f"진입: {entry_mode_str}",
        "",
    ])

    # --- 강력 매수 (PF 1.2+) ---
    if strong_sigs:
        lines.append("== 강력 매수 ==")
        for s in strong_sigs[:10]:
            lines.extend(_format_one_signal(s))

    # --- 관심 종목 (PF 1.0~1.2) ---
    if watch_sigs:
        lines.append("== 관심 종목 ==")
        for s in watch_sigs[:15]:
            lines.extend(_format_one_signal(s))

    # --- 기타 (분류 안 된 시그널) ---
    if other_sigs and not strong_strategies:
        for s in sorted(other_sigs, key=lambda s: -s.confidence)[:10]:
            lines.extend(_format_one_signal(s))

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
