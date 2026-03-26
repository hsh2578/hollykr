"""
통일 청산 관리자 (v4.0 Section 0 수정 7)

우선순위:
  1순위: 손절가 도달 -> 즉시 청산
  2순위: 목표가 도달 -> 50% 익절, 나머지 트레일링 스탑
  3순위: 최대 보유일 초과 -> 다음날 시가 청산
  4순위: 전략 조건 이탈 -> 다음날 시가 청산

트레일링 스탑 (목표가 도달 후):
  trail_stop = MAX(종가, 보유 기간 중) x 0.95
  매일 장 마감 후 업데이트
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import date

import pandas as pd

from scripts.screeners.holly_kr.config import TRAILING_STOP_PCT


@dataclass
class Position:
    """보유 포지션."""
    ticker: str
    ticker_name: str
    strategy_name: str
    entry_date: str            # YYYY-MM-DD
    entry_price: float
    quantity: int              # 보유 수량
    target_price: float
    stop_loss_price: float
    hold_days_max: int
    hold_days_current: int = 0

    # 트레일링 스탑 관련
    target_hit: bool = False           # 목표가 도달 여부
    partial_exit_done: bool = False    # 50% 익절 완료 여부
    max_close_during_hold: float = 0.0 # 보유 기간 중 최고 종가
    trail_stop_price: float = 0.0      # 트레일링 스탑 가격

    # 전략 참조
    category: str = ""
    sector: str = ""


@dataclass
class ExitSignal:
    """청산 시그널."""
    ticker: str
    ticker_name: str
    strategy_name: str
    exit_type: str             # stop_loss, target_partial, trailing_stop, time, condition
    exit_price: float          # 청산 가격 (추정)
    exit_quantity_pct: float   # 청산 비율 (0.5 = 50%, 1.0 = 100%)
    pnl_pct: float             # 추정 손익률
    priority: int              # 우선순위 (1~4)
    reason: str = ""


class ExitManager:
    """
    통일 청산 규칙 관리자.

    매일 장 마감 후 보유 포지션 점검 -> ExitSignal 생성.
    """

    def __init__(self, trailing_stop_pct: float = TRAILING_STOP_PCT):
        self.trailing_stop_pct = trailing_stop_pct  # 기본 5%

    def check_exits(
        self,
        positions: List[Position],
        current_data: Dict[str, pd.Series],
        strategies: Optional[Dict[str, object]] = None,
    ) -> List[ExitSignal]:
        """
        전체 포지션 청산 조건 확인.

        Args:
            positions: 보유 포지션 리스트
            current_data: {ticker: 당일 OHLCV Series (Open, High, Low, Close, Volume)}
            strategies: {strategy_name: strategy object} (전략 조건 이탈 확인용)

        Returns:
            청산 시그널 리스트 (우선순위 순 정렬)
        """
        exit_signals: List[ExitSignal] = []

        for pos in positions:
            row = current_data.get(pos.ticker)
            if row is None:
                continue

            today_high = row.get('High', 0)
            today_low = row.get('Low', 0)
            today_close = row.get('Close', 0)

            # 보유일 증가
            pos.hold_days_current += 1

            # 최고 종가 업데이트
            pos.max_close_during_hold = max(pos.max_close_during_hold, today_close)

            # -----------------------------------------------------------
            # Priority 1: 손절가 도달 -> 즉시 청산
            # -----------------------------------------------------------
            if today_low <= pos.stop_loss_price:
                pnl = (pos.stop_loss_price - pos.entry_price) / pos.entry_price
                exit_signals.append(ExitSignal(
                    ticker=pos.ticker,
                    ticker_name=pos.ticker_name,
                    strategy_name=pos.strategy_name,
                    exit_type='stop_loss',
                    exit_price=pos.stop_loss_price,
                    exit_quantity_pct=1.0,
                    pnl_pct=pnl,
                    priority=1,
                    reason=f"손절가 {pos.stop_loss_price:,.0f}원 도달",
                ))
                continue  # 손절 시 다른 조건 무시

            # -----------------------------------------------------------
            # Priority 2: 목표가 도달 -> 50% 익절 + 나머지 트레일링
            # -----------------------------------------------------------
            if today_high >= pos.target_price and not pos.target_hit:
                pos.target_hit = True
                pnl = (pos.target_price - pos.entry_price) / pos.entry_price

                if not pos.partial_exit_done:
                    # 50% 익절
                    exit_signals.append(ExitSignal(
                        ticker=pos.ticker,
                        ticker_name=pos.ticker_name,
                        strategy_name=pos.strategy_name,
                        exit_type='target_partial',
                        exit_price=pos.target_price,
                        exit_quantity_pct=0.5,
                        pnl_pct=pnl,
                        priority=2,
                        reason=f"목표가 {pos.target_price:,.0f}원 도달 -> 50% 익절",
                    ))
                    pos.partial_exit_done = True

                # 트레일링 스탑 설정/업데이트
                pos.trail_stop_price = pos.max_close_during_hold * (1 - self.trailing_stop_pct)

            # 이미 목표가 도달 후 트레일링 스탑 확인
            if pos.target_hit and pos.partial_exit_done:
                # 트레일링 스탑 업데이트
                new_trail = pos.max_close_during_hold * (1 - self.trailing_stop_pct)
                pos.trail_stop_price = max(pos.trail_stop_price, new_trail)

                if today_low <= pos.trail_stop_price:
                    pnl = (pos.trail_stop_price - pos.entry_price) / pos.entry_price
                    exit_signals.append(ExitSignal(
                        ticker=pos.ticker,
                        ticker_name=pos.ticker_name,
                        strategy_name=pos.strategy_name,
                        exit_type='trailing_stop',
                        exit_price=pos.trail_stop_price,
                        exit_quantity_pct=1.0,  # 나머지 전량
                        pnl_pct=pnl,
                        priority=2,
                        reason=f"트레일링 스탑 {pos.trail_stop_price:,.0f}원 도달 "
                               f"(최고가 {pos.max_close_during_hold:,.0f}원 x "
                               f"{1-self.trailing_stop_pct:.0%})",
                    ))
                    continue

            # -----------------------------------------------------------
            # Priority 3: 최대 보유일 초과 -> 다음날 시가 청산
            # -----------------------------------------------------------
            if pos.hold_days_current >= pos.hold_days_max:
                pnl = (today_close - pos.entry_price) / pos.entry_price
                exit_signals.append(ExitSignal(
                    ticker=pos.ticker,
                    ticker_name=pos.ticker_name,
                    strategy_name=pos.strategy_name,
                    exit_type='time',
                    exit_price=today_close,  # 다음날 시가 추정
                    exit_quantity_pct=1.0,
                    pnl_pct=pnl,
                    priority=3,
                    reason=f"최대 보유일({pos.hold_days_max}일) 초과 -> 다음날 시가 청산",
                ))
                continue

            # -----------------------------------------------------------
            # Priority 4: 전략 조건 이탈 -> 다음날 시가 청산
            # -----------------------------------------------------------
            if strategies:
                strategy = strategies.get(pos.strategy_name)
                if strategy is not None:
                    try:
                        exit_reason = strategy.check_exit(
                            {
                                'ticker': pos.ticker,
                                'entry_price': pos.entry_price,
                                'hold_days': pos.hold_days_current,
                                'max_close': pos.max_close_during_hold,
                            },
                            row,
                        )
                        if exit_reason == 'condition':
                            pnl = (today_close - pos.entry_price) / pos.entry_price
                            exit_signals.append(ExitSignal(
                                ticker=pos.ticker,
                                ticker_name=pos.ticker_name,
                                strategy_name=pos.strategy_name,
                                exit_type='condition',
                                exit_price=today_close,
                                exit_quantity_pct=1.0,
                                pnl_pct=pnl,
                                priority=4,
                                reason="전략 조건 이탈 -> 다음날 시가 청산",
                            ))
                    except Exception:
                        pass

        # 우선순위 순 정렬
        exit_signals.sort(key=lambda s: s.priority)
        return exit_signals

    def format_exit_signals(self, signals: List[ExitSignal]) -> str:
        """청산 시그널을 텔레그램/터미널 출력용 문자열로 포맷."""
        if not signals:
            return "청산 시그널 없음"

        lines = ["[청산 시그널]", "=" * 50]
        for sig in signals:
            emoji_map = {
                'stop_loss': '[손절]',
                'target_partial': '[익절50%]',
                'trailing_stop': '[트레일링]',
                'time': '[보유일초과]',
                'condition': '[조건이탈]',
            }
            tag = emoji_map.get(sig.exit_type, '[청산]')
            pnl_str = f"+{sig.pnl_pct:.1%}" if sig.pnl_pct > 0 else f"{sig.pnl_pct:.1%}"

            lines.append(
                f"{tag} {sig.ticker_name}({sig.ticker}) | "
                f"{sig.strategy_name} | {pnl_str} | "
                f"청산가 {sig.exit_price:,.0f}원 ({sig.exit_quantity_pct:.0%})"
            )
            lines.append(f"  -> {sig.reason}")

        return "\n".join(lines)
