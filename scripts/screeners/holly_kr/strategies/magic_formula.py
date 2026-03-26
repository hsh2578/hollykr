"""전략 10: Greenblatt Magic Formula [등급 A] [EOD]
ROIC 높고 EY 높은 종목을 기계적으로 매수. 분기 리밸런싱."""

from typing import Optional, Dict, List
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class MagicFormula(BaseStrategy):
    name = "magic_formula"
    category = "legendary"
    exec_timing = "EOD"
    grade = "A"

    # 제외 섹터 (금융 + 유틸리티)
    EXCLUDE_SECTORS = {
        '은행', '증권', '손해보험', '생명보험', '카드',
        '기타금융', '유틸리티', '다각화된금융', '보험',
    }

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0,
             financial_data: dict = None) -> Optional[Signal]:
        """Magic Formula는 개별 종목 스캔이 아니라 유니버스 랭킹으로 동작.
        여기서는 재무 데이터가 있으면 ROIC/EY 기반 점수 계산."""
        if sector in self.EXCLUDE_SECTORS:
            return None
        if financial_data is None:
            return None

        # ROIC, EY가 있는 경우에만 시그널 생성 가능
        roic = financial_data.get('roic')
        ey = financial_data.get('ey')
        if roic is None or ey is None:
            return None

        # 개별 스캔에서는 랭킹 불가 → scan_universe에서 처리
        return None

    def scan_universe(self, universe_financials: List[dict]) -> List[Signal]:
        """유니버스 전체 ROIC + EY 랭킹 기반 시그널 생성."""
        # ROIC, EY 있는 종목만 (금융 섹터 제외)
        valid = [f for f in universe_financials
                 if f.get('roic') is not None and f.get('ey') is not None
                 and f.get('sector') not in self.EXCLUDE_SECTORS]

        if len(valid) < 20:
            return []

        df = pd.DataFrame(valid)
        # ROIC 높을수록 좋음 → ascending=False → rank 1이 최고
        df['roic_rank'] = df['roic'].rank(ascending=False)
        # EY 높을수록 좋음 (싸고 좋음)
        df['ey_rank'] = df['ey'].rank(ascending=False)
        # combined_rank 작을수록 좋음 (1+1=2가 최고)
        df['combined_rank'] = df['roic_rank'] + df['ey_rank']
        df = df.sort_values('combined_rank')

        # 상위 20~30개
        top = df.head(30)
        signals = []
        for _, row in top.iterrows():
            sig = Signal(
                strategy_name=self.name,
                ticker=row['ticker'],
                ticker_name=row.get('name', ''),
                entry_price=row.get('close', 0),
                target_pct=0.10,
                stop_loss_pct=-0.08,
                hold_days_min=60,
                hold_days_max=90,
                confidence=0.60,
                exec_timing="EOD",
                category="legendary",
                grade="A",
                sector=row.get('sector', ''),
            )
            sig.calc_rr_ratio()
            signals.append(sig)

        return signals

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        """분기 리밸런싱 시점에 청산 판단."""
        return None
