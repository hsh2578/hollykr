"""전략별 매도 룰 텍스트 자동 생성 — 텔레그램 + signals_today.json 표시용.

백테스팅 청산 룰 (exit_manager.py 6단계)을 사용자가 보기 쉽게 텍스트로.
카테고리별 기본 + 전략별 특수 룰 매핑.
"""
from typing import Optional


# 카테고리별 매도 룰 (base.py CATEGORY_ATR_PRESETS 기반)
CATEGORY_RULES = {
    'breakout': {
        'target_text': "5×ATR",
        'stop_text': "2×ATR",
        'hold_days': 10,
        'desc': "돌파 추세 추종",
    },
    'trend_following': {
        'target_text': "5×ATR",
        'stop_text': "2×ATR",
        'hold_days': 10,
        'desc': "추세 추종",
    },
    'trend': {
        'target_text': "5×ATR",
        'stop_text': "2×ATR",
        'hold_days': 10,
        'desc': "추세",
    },
    'momentum': {
        'target_text': "4.5×ATR",
        'stop_text': "2×ATR",
        'hold_days': 7,
        'desc': "모멘텀 추종",
    },
    'gap_momentum': {
        'target_text': "4×ATR",
        'stop_text': "1.6×ATR",
        'hold_days': 5,
        'desc': "갭 모멘텀 (빠른 청산)",
    },
    'accumulation': {
        'target_text': "5×ATR",
        'stop_text': "2×ATR",
        'hold_days': 15,
        'desc': "물량 누적 (장기)",
    },
    'multi_factor': {
        'target_text': "4.5×ATR",
        'stop_text': "2×ATR",
        'hold_days': 10,
        'desc': "복합 요인",
    },
    'pullback': {
        'target_text': "3×ATR",
        'stop_text': "1.5×ATR",
        'hold_days': 7,
        'desc': "눌림목 진입",
    },
    'support_bounce': {
        'target_text': "3×ATR",
        'stop_text': "1.5×ATR",
        'hold_days': 5,
        'desc': "지지 반등",
    },
    'mean_reversion': {
        'target_text': "2.5×ATR",
        'stop_text': "1.25×ATR",
        'hold_days': 5,
        'desc': "평균 회귀 (빠른 회복)",
    },
    'reversal': {
        'target_text': "3×ATR",
        'stop_text': "1.5×ATR",
        'hold_days': 7,
        'desc': "반전",
    },
    'legendary': {
        'target_text': "4-5×ATR",
        'stop_text': "1.5-2×ATR",
        'hold_days': 15,
        'desc': "거장 검증 패턴",
    },
}

# 전략별 특수 매도 룰 (legendary + ALPHA pool + 기타 특수)
STRATEGY_SPECIAL_RULES = {
    # ALPHA pool (5년 검증)
    'ma_convergence': "200일 SMA 하향 이탈 시 즉시 청산 (정배열 붕괴)",
    'new_high_52w_approach': "52주 고점 ×0.95 트레일링 (회귀 위험)",

    # Legendary
    'darvas_box': "박스 하단 = stop (구조적), 박스 너비 트레일링",
    'weinstein_stage': "Stage 4 진입 (200SMA 하향) → 즉시 청산",
    'minervini_trend': "stop = max(50SMA, -8%), first-day -3% 엄격",
    'minervini_trend_template': "SEPA 룰 위반 시 청산",
    'livermore_pivot': "stop = max(-3%, ATR), Livermore -3% pivot 룰",

    # 기타 특수 (구조적 stop)
    'box_range_watch': "박스 하단 = stop (구조적)",
    'bottom_breakout': "박스 하단 이탈 → 즉시 청산",
    'volume_dry_up': "거래량 회복 X 시 (5일) 청산",
    'horseshoe_up': "지지선 하향 이탈 시 청산",

    # Phase H (학술 거장)
    'clenow_momentum': "100일 SMA 하향 이탈 → 청산 (Clenow rule)",
    'donchian_breakout': "10일 Donchian 하단 이탈 → 청산 (Seykota)",
    'aqr_tsmom': "12개월 모멘텀 음수 전환 → 청산 (Moskowitz)",
    'bollinger_squeeze': "Bollinger 중심선 (20SMA) 하향 → 청산",
    'elder_triple_screen': "주봉 추세 변경 → 청산 (Elder)",
    'turn_of_month': "월말 효과 종료 (5일) → 청산",
    'adx_trend': "ADX 25 하회 → 추세 약화 → 청산 (Wilder)",
}


def generate_exit_rules_text(signal) -> str:
    """전략별 매도 룰 텍스트 생성.

    Args:
        signal: Signal 객체 (strategy_name, category, target_price, stop_loss_price,
                target_pct, stop_loss_pct, hold_days_max 등)

    Returns:
        매도 룰 텍스트 (텔레그램 + JSON에 사용)
    """
    cat = getattr(signal, 'category', 'breakout')
    name = signal.strategy_name
    cat_rule = CATEGORY_RULES.get(cat, CATEGORY_RULES['breakout'])
    special = STRATEGY_SPECIAL_RULES.get(name, '')
    hold = getattr(signal, 'hold_days_max', cat_rule['hold_days'])

    target_price = float(signal.target_price)
    stop_price = float(signal.stop_loss_price)
    target_pct = float(signal.target_pct) * 100
    stop_pct = float(signal.stop_loss_pct) * 100

    lines = [
        f"⏱ 매도 룰 — {name} ({cat}, {cat_rule['desc']}):",
        f"",
        f"🎯 목표가: ₩{target_price:,.0f} ({target_pct:+.1f}% = {cat_rule['target_text']})",
        f"   → 도달 시 50% 부분익절 → 잔량 트레일링 5%",
        f"",
        f"🛑 손절가: ₩{stop_price:,.0f} ({stop_pct:+.1f}% = {cat_rule['stop_text']})",
        f"   → 종가 손절 도달 시 즉시 청산",
        f"",
        f"📉 갭다운: 시초가 ≤ 손절가 → 시초가 즉시 청산",
        f"⚠️ 첫날 -3%: 진입 다음날 종가 -3% → 시가 청산",
        f"⏰ 시간 청산: {hold}일 초과 → 종가 청산",
    ]

    if special:
        lines.append(f"")
        lines.append(f"🔻 [전략 특수]: {special}")

    return "\n".join(lines)


def generate_exit_rules_summary(signal) -> str:
    """짧은 1줄 요약 (Top 10 1차 메시지용)."""
    cat = getattr(signal, 'category', 'breakout')
    cat_rule = CATEGORY_RULES.get(cat, CATEGORY_RULES['breakout'])
    return f"{cat_rule['target_text']}/{cat_rule['stop_text']} {cat_rule['hold_days']}일"


if __name__ == '__main__':
    # 테스트
    from types import SimpleNamespace
    sig = SimpleNamespace(
        strategy_name='ma_convergence',
        category='trend_following',
        target_price=185460,
        stop_loss_price=162900,
        target_pct=0.10,
        stop_loss_pct=-0.034,
        hold_days_max=10,
    )
    print(generate_exit_rules_text(sig))
    print()
    print("[요약]:", generate_exit_rules_summary(sig))
