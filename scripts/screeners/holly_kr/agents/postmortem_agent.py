"""
Phase 10-5: Postmortem Agent (자동 결과 추적 + 주간 리포트)

매일 어제 송출 시그널 → 오늘 결과 자동 추적 → 누적 저장.
주간 금요일 종합 리포트 텔레그램 송출.

옵션 B (사용자 합의): 자동 추적 + 수동 적용 (자동 조정 X, 정직성)

저장:
- data/holly_kr/signals_log.csv: 매일 송출 시그널 누적
- data/holly_kr/trades_log.csv: 결과 추적 (가상 PnL)
- data/holly_kr/weekly_report.csv: 주간 요약

매일 19:00 nightly 직전 실행.
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import csv
import logging

import pandas as pd

from config import DATA_DIR

logger = logging.getLogger(__name__)

SIGNALS_LOG = DATA_DIR / 'holly_kr' / 'signals_log.csv'
TRADES_LOG = DATA_DIR / 'holly_kr' / 'trades_log.csv'
WEEKLY_REPORT = DATA_DIR / 'holly_kr' / 'weekly_report.csv'


class PostmortemAgent:
    """매일 어제 시그널 → 오늘 결과 추적."""

    def __init__(self):
        SIGNALS_LOG.parent.mkdir(parents=True, exist_ok=True)

    def log_signals(self, signals: List, regime: str = '') -> None:
        """오늘 송출 시그널을 signals_log.csv에 누적 저장.

        매일 daily-scan 완료 후 호출.
        """
        if not signals:
            return

        today = datetime.now().strftime('%Y-%m-%d')
        rows = []
        for sig in signals:
            rows.append({
                'date': today,
                'strategy': sig.strategy_name,
                'ticker': sig.ticker,
                'name': sig.ticker_name,
                'sector': getattr(sig, 'sector', ''),
                'entry_price': sig.entry_price,
                'target_price': sig.target_price,
                'stop_loss_price': sig.stop_loss_price,
                'target_pct': sig.target_pct,
                'stop_loss_pct': sig.stop_loss_pct,
                'confidence': sig.confidence,
                'regime': regime,
                'tier': getattr(sig, 'signal_tier', ''),
            })

        # 파일 헤더 점검
        file_exists = SIGNALS_LOG.exists()
        with open(SIGNALS_LOG, 'a', newline='', encoding='utf-8') as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerows(rows)

        logger.info(f"[postmortem] {len(rows)}개 시그널 로그 저장 ({today})")

    def update_outcomes(self) -> Dict:
        """어제 시그널의 오늘 결과 추적.

        매일 19:00 (nightly 직전) 실행.

        Returns:
            {
                'date': str,
                'updated_count': int,
                'avg_1d_pnl': float,
                'win_rate_1d': float,
            }
        """
        if not SIGNALS_LOG.exists():
            return {'date': '', 'updated_count': 0}

        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        # 어제 시그널 로드
        df = pd.read_csv(SIGNALS_LOG, encoding='utf-8')
        yesterday_sigs = df[df['date'] == yesterday]
        if yesterday_sigs.empty:
            return {'date': today, 'updated_count': 0}

        # 오늘 종가 조회 → PnL 계산
        from scripts.ohlcv_data import get_ohlcv

        outcomes = []
        for _, sig in yesterday_sigs.iterrows():
            ticker = str(sig['ticker']).zfill(6)
            try:
                ohlcv = get_ohlcv(ticker, days=5, use_cache=True)
                if ohlcv is None or len(ohlcv) < 2:
                    continue

                # 오늘 종가
                today_close = float(ohlcv['Close'].iloc[-1])
                today_open = float(ohlcv['Open'].iloc[-1])
                today_low = float(ohlcv['Low'].iloc[-1])
                today_high = float(ohlcv['High'].iloc[-1])

                entry = float(sig['entry_price'])
                target = float(sig['target_price'])
                stop = float(sig['stop_loss_price'])

                # 1일 결과 (오늘 종가 vs 진입가)
                pnl_1d = (today_close - entry) / entry

                # 6단계 청산 simulation
                exit_reason = 'open'
                if today_open <= stop:
                    exit_reason = 'gap_down'
                    exit_price = today_open
                elif today_low <= stop:
                    exit_reason = 'stop_loss'
                    exit_price = stop
                elif today_high >= target:
                    exit_reason = 'target_50pct'
                    exit_price = target  # 50% 익절 가정
                else:
                    exit_reason = 'holding'
                    exit_price = today_close

                outcomes.append({
                    'date': today,
                    'signal_date': yesterday,
                    'strategy': sig['strategy'],
                    'ticker': ticker,
                    'name': sig.get('name', ''),
                    'entry_price': entry,
                    'today_close': today_close,
                    'pnl_1d_pct': round(pnl_1d, 4),
                    'exit_reason': exit_reason,
                    'tier': sig.get('tier', ''),
                })
            except Exception as e:
                logger.warning(f"[postmortem] {ticker} 결과 추적 실패: {e}")

        # 결과 저장
        if outcomes:
            file_exists = TRADES_LOG.exists()
            with open(TRADES_LOG, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=outcomes[0].keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerows(outcomes)

        avg_pnl = sum(o['pnl_1d_pct'] for o in outcomes) / len(outcomes) if outcomes else 0
        win_rate = sum(1 for o in outcomes if o['pnl_1d_pct'] > 0) / len(outcomes) if outcomes else 0

        return {
            'date': today,
            'updated_count': len(outcomes),
            'avg_1d_pnl': round(avg_pnl, 4),
            'win_rate_1d': round(win_rate, 3),
            'outcomes': outcomes,
        }

    def generate_weekly_report(self) -> Optional[str]:
        """주간 종합 리포트 (금요일 송출용)."""
        if not TRADES_LOG.exists():
            return None

        df = pd.read_csv(TRADES_LOG, encoding='utf-8')
        if df.empty:
            return None

        # 최근 7일
        df['date'] = pd.to_datetime(df['date'])
        week_ago = datetime.now() - timedelta(days=7)
        recent = df[df['date'] >= week_ago]

        if recent.empty:
            return None

        # 전체 통계
        total = len(recent)
        wins = (recent['pnl_1d_pct'] > 0).sum()
        win_rate = wins / total if total else 0
        avg_pnl = recent['pnl_1d_pct'].mean()
        total_pnl = recent['pnl_1d_pct'].sum()

        # 전략별 통계
        strategy_stats = (
            recent.groupby('strategy')
            .agg(trades=('pnl_1d_pct', 'count'),
                 win_rate=('pnl_1d_pct', lambda x: (x > 0).mean()),
                 avg_pnl=('pnl_1d_pct', 'mean'),
                 total_pnl=('pnl_1d_pct', 'sum'))
            .sort_values('total_pnl', ascending=False)
        )

        # Tier별 통계
        if 'tier' in recent.columns:
            tier_stats = (
                recent.groupby('tier')
                .agg(trades=('pnl_1d_pct', 'count'),
                     win_rate=('pnl_1d_pct', lambda x: (x > 0).mean()),
                     avg_pnl=('pnl_1d_pct', 'mean'))
            )
        else:
            tier_stats = pd.DataFrame()

        # 메시지 작성
        today = datetime.now().strftime('%Y-%m-%d')
        lines = [
            f"📊 HollyKR 주간 복기 ({today})",
            f"",
            f"[전체]",
            f"  거래: {total}건",
            f"  승률: {win_rate:.0%}",
            f"  평균 PnL: {avg_pnl*100:+.2f}%",
            f"  누적 PnL: {total_pnl*100:+.2f}%",
            f"",
            f"[전략별 Top 5]",
        ]
        for strat, row in strategy_stats.head(5).iterrows():
            lines.append(f"  {strat}: {row['trades']:.0f}건, 승률 {row['win_rate']:.0%}, "
                         f"PnL {row['total_pnl']*100:+.1f}%")

        if not tier_stats.empty:
            lines.append("")
            lines.append("[Tier별]")
            for tier, row in tier_stats.iterrows():
                lines.append(f"  {tier}: {row['trades']:.0f}건, 승률 {row['win_rate']:.0%}, "
                             f"평균 {row['avg_pnl']*100:+.2f}%")

        # 주간 리포트 CSV 저장
        WEEKLY_REPORT.parent.mkdir(parents=True, exist_ok=True)
        recent_summary = pd.DataFrame([{
            'week_ending': today,
            'total_trades': total,
            'win_rate': round(win_rate, 3),
            'avg_pnl_pct': round(avg_pnl, 4),
            'total_pnl_pct': round(total_pnl, 4),
        }])
        recent_summary.to_csv(WEEKLY_REPORT, mode='a',
                              header=not WEEKLY_REPORT.exists(),
                              index=False, encoding='utf-8')

        return '\n'.join(lines)


if __name__ == '__main__':
    agent = PostmortemAgent()

    # 테스트: 오늘 결과 업데이트
    result = agent.update_outcomes()
    print(f"업데이트: {result['updated_count']}개 시그널 결과")
    if result['updated_count'] > 0:
        print(f"  평균 1일 PnL: {result['avg_1d_pnl']*100:+.2f}%")
        print(f"  1일 승률: {result['win_rate_1d']:.0%}")

    # 주간 리포트
    report = agent.generate_weekly_report()
    if report:
        print(f"\n{report}")
    else:
        print("\n주간 리포트 데이터 부족")
