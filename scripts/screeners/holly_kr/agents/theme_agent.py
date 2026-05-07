"""
Phase 10-3: Theme Agent (테마 평가 + 알고픽 발굴)

룰 기반 (LLM X). KIS 섹터 데이터로 오늘의 핫 테마 식별.
시그널 종목 ↔ 핫 테마 매칭 → confidence_multiplier 보정.
또한 알고픽 Top 3 종목 발굴 (테마 모멘텀 기반).

출력 (시그널 평가):
    {
        'hot_themes': List[str],          # Top 3-5 핫 테마
        'cold_themes': List[str],         # 약세 테마
        'theme_returns': Dict[str, float], # 섹터별 등락률
        'confidence_multiplier': Dict[str, float]  # ticker → multiplier
    }

출력 (알고픽 발굴):
    {
        'top3_picks': List[Dict],  # 테마별 Top 종목 (예: 반도체-SK하이닉스)
    }
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# 섹터 데이터 fetch
# ============================================================================

def _load_sector_returns_today() -> Optional[pd.DataFrame]:
    """오늘의 섹터별 등락률 로드.

    KIS sector 캐시 + 종목별 OHLCV로 섹터 평균 등락률 계산.
    """
    try:
        from scripts.kis_sector_data import load_kis_sectors
        sectors_df = load_kis_sectors()
        if sectors_df is None or sectors_df.empty:
            return None

        from scripts.ohlcv_data import get_ohlcv

        # 종목별 오늘 등락률 + 섹터 매핑
        sector_data = {}
        for _, row in sectors_df.iterrows():
            ticker = row.get('Code')
            sector = row.get('Sector')
            if not ticker or not sector:
                continue

            df = get_ohlcv(ticker, days=5, use_cache=True)
            if df is None or len(df) < 2:
                continue

            # 오늘 등락률
            today_ret = (df['Close'].iloc[-1] / df['Close'].iloc[-2]) - 1
            # 거래대금 (시총 비례 가중치 위함)
            today_value = float(df['Close'].iloc[-1] * df['Volume'].iloc[-1])

            if sector not in sector_data:
                sector_data[sector] = []
            sector_data[sector].append({
                'ticker': ticker,
                'return': today_ret,
                'value': today_value,
            })

        # 섹터별 가중평균 등락률 (거래대금 가중)
        sector_summary = []
        for sector, stocks in sector_data.items():
            if len(stocks) < 3:
                continue  # 최소 3종목 필요
            total_value = sum(s['value'] for s in stocks)
            if total_value <= 0:
                continue
            weighted_ret = sum(s['return'] * s['value'] for s in stocks) / total_value
            sector_summary.append({
                'sector': sector,
                'avg_return': weighted_ret,
                'total_value': total_value,
                'num_stocks': len(stocks),
                'stocks': stocks,
            })

        if not sector_summary:
            return None

        df = pd.DataFrame(sector_summary)
        df = df.sort_values('avg_return', ascending=False)
        return df

    except Exception as e:
        logger.warning(f"[theme_agent] 섹터 데이터 로드 실패: {e}")
        return None


# ============================================================================
# Theme Agent 본체
# ============================================================================

class ThemeAgent:
    """오늘 핫 테마 식별 + 시그널 종목 매칭."""

    HOT_THEME_TOP_N = 3   # 상위 N개 테마 = 핫
    COLD_THEME_BOTTOM_N = 3  # 하위 N개 = 콜드
    HOT_BOOST = 1.30      # 핫 테마 종목 multiplier
    WARM_BOOST = 1.15     # 중간 핫 (4-5위)
    COLD_PENALTY = 0.70   # 콜드 테마 종목 multiplier
    NEUTRAL = 1.00

    def __init__(self):
        self._cache = None

    def evaluate(self) -> Dict[str, Any]:
        """오늘의 테마 평가."""
        result = {
            'hot_themes': [],
            'warm_themes': [],
            'cold_themes': [],
            'theme_returns': {},
            'top3_picks': [],
        }

        sector_df = _load_sector_returns_today()
        if sector_df is None or sector_df.empty:
            logger.warning("[theme_agent] 섹터 데이터 없음")
            return result

        # 핫/콜드 테마 식별
        sorted_sectors = sector_df.to_dict('records')
        result['hot_themes'] = [s['sector'] for s in sorted_sectors[:self.HOT_THEME_TOP_N]]
        result['warm_themes'] = [
            s['sector'] for s in sorted_sectors[self.HOT_THEME_TOP_N:self.HOT_THEME_TOP_N + 2]
        ]
        result['cold_themes'] = [
            s['sector'] for s in sorted_sectors[-self.COLD_THEME_BOTTOM_N:]
        ]
        result['theme_returns'] = {
            s['sector']: round(s['avg_return'] * 100, 2)
            for s in sorted_sectors
        }

        # 알고픽 Top 3 발굴 (핫 테마별 1종목)
        top3_picks = []
        for theme_data in sorted_sectors[:self.HOT_THEME_TOP_N]:
            sector = theme_data['sector']
            stocks = theme_data['stocks']
            # 종목별 점수: 거래대금 50% + 당일 등락률 50%
            scored = []
            for s in stocks:
                # 정규화
                value_score = min(s['value'] / 1e10, 1.0)  # 100억 기준
                return_score = min(s['return'] / 0.10, 1.0) if s['return'] > 0 else 0  # 10% 기준
                composite = 0.5 * value_score + 0.5 * return_score
                scored.append({**s, 'score': composite})

            # 상위 1종목
            scored.sort(key=lambda x: -x['score'])
            if scored:
                top = scored[0]
                top3_picks.append({
                    'sector': sector,
                    'sector_return': round(theme_data['avg_return'] * 100, 1),
                    'ticker': top['ticker'],
                    'today_return': round(top['return'] * 100, 1),
                    'trading_value_billion': round(top['value'] / 1e8, 0),
                    'score': round(top['score'], 3),
                })

        result['top3_picks'] = top3_picks
        self._cache = result
        return result

    def get_ticker_multiplier(self, ticker: str, sector: str = None) -> float:
        """특정 종목의 테마 매칭 multiplier.

        섹터를 못 찾으면 NEUTRAL (1.0).
        """
        if self._cache is None:
            return self.NEUTRAL

        if not sector:
            # KIS sector에서 조회
            try:
                from scripts.kis_sector_data import load_kis_sectors
                sectors_df = load_kis_sectors()
                if sectors_df is not None:
                    row = sectors_df[sectors_df['Code'] == ticker]
                    if not row.empty:
                        sector = row.iloc[0].get('Sector', '')
            except Exception:
                pass

        if not sector:
            return self.NEUTRAL

        if sector in self._cache['hot_themes']:
            return self.HOT_BOOST
        if sector in self._cache['warm_themes']:
            return self.WARM_BOOST
        if sector in self._cache['cold_themes']:
            return self.COLD_PENALTY
        return self.NEUTRAL

    def adjust_signals(self, signals: List) -> List:
        """시그널 리스트의 confidence를 테마 매칭으로 보정.

        Args:
            signals: List[Signal]

        Returns:
            보정된 signals (in-place 수정)
        """
        if self._cache is None:
            return signals

        for sig in signals:
            mult = self.get_ticker_multiplier(sig.ticker, getattr(sig, 'sector', None))
            old_conf = sig.confidence
            new_conf = min(0.95, old_conf * mult)
            sig.confidence = new_conf
            # 로그 (debug 용)
            if mult != self.NEUTRAL:
                logger.debug(f"  Theme adjust: {sig.ticker} {old_conf:.2f} → {new_conf:.2f} (×{mult})")

        return signals


# ============================================================================
# 테스트
# ============================================================================

if __name__ == '__main__':
    agent = ThemeAgent()
    r = agent.evaluate()

    print("=" * 60)
    print("  Theme Agent - 오늘의 테마 평가")
    print("=" * 60)
    print(f"  핫 테마 Top {len(r['hot_themes'])}: {r['hot_themes']}")
    print(f"  중간 핫: {r['warm_themes']}")
    print(f"  콜드 테마: {r['cold_themes']}")
    print()

    if r['theme_returns']:
        print("  [섹터별 등락률 Top 10]")
        sorted_returns = sorted(r['theme_returns'].items(), key=lambda x: -x[1])
        for sector, ret in sorted_returns[:10]:
            print(f"    {sector:<25s}: {ret:+.2f}%")

    if r['top3_picks']:
        print("\n  [알고픽 Top 3]")
        for i, p in enumerate(r['top3_picks'], 1):
            print(f"    {i}. [{p['sector']} +{p['sector_return']}%] "
                  f"{p['ticker']} +{p['today_return']}% "
                  f"거래대금 {p['trading_value_billion']:.0f}억")
