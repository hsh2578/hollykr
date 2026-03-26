"""전략 11: Piotroski F-Score [등급 A] [EOD]
저PBR 종목 중 재무건전성 8~9점 = 진짜 저평가 보석."""

from typing import Optional, Dict, List
import pandas as pd
from scripts.screeners.holly_kr.strategies.base import BaseStrategy
from scripts.screeners.holly_kr.signal_model import Signal


class PiotroskiFScore(BaseStrategy):
    name = "piotroski_fscore"
    category = "legendary"
    exec_timing = "EOD"
    grade = "A"

    def scan(self, df: pd.DataFrame, ticker: str, ticker_name: str,
             sector: str = "", entry_price: float = 0.0,
             financial_data: dict = None) -> Optional[Signal]:
        """F-Score는 재무 데이터 기반. scan_universe에서 일괄 처리."""
        if financial_data is None:
            return None

        # 개별 종목 스캔: PBR 확인 + F-Score 계산
        pbr = financial_data.get('pbr')
        if pbr is None or pbr <= 0:
            return None

        score = self.calc_fscore(financial_data)
        if score < 8:
            return None

        ep = entry_price or financial_data.get('close', 0)
        if ep <= 0:
            return None

        return self._make_signal(
            ticker, ticker_name, sector, ep,
            target_pct=0.10, stop_loss_pct=-0.08,
            hold_min=60, hold_max=90, confidence=0.55 + score * 0.05,
            signal_date='',
        )

    def calc_fscore(self, fin: dict) -> int:
        """9점 만점 F-Score 계산.

        수익성 (F1-F4):
          F1: 당기순이익 > 0
          F2: 영업현금흐름 > 0
          F3: ROA(당기) > ROA(전기)
          F4: 영업현금흐름 > 당기순이익

        재무 안정성 (F5-F7):
          F5: 장기부채비율 감소
          F6: 유동비율 증가
          F7: 신주 발행 없음

        효율성 (F8-F9):
          F8: 매출총이익률 개선
          F9: 자산회전율 개선 (매출/총자산)
        """
        score = 0

        # F1: 당기순이익 > 0
        if fin.get('net_income', 0) > 0:
            score += 1
        # F2: 영업현금흐름 > 0
        if fin.get('cfo', 0) > 0:
            score += 1
        # F3: ROA(당기) > ROA(전기)
        if fin.get('roa', 0) > fin.get('roa_prev', 0):
            score += 1
        # F4: 영업현금흐름 > 당기순이익
        if fin.get('cfo', 0) > fin.get('net_income', 0):
            score += 1
        # F5: 장기부채비율 감소
        if fin.get('lt_debt_ratio', 1) < fin.get('lt_debt_ratio_prev', 1):
            score += 1
        # F6: 유동비율 증가
        if fin.get('current_ratio', 0) > fin.get('current_ratio_prev', 0):
            score += 1
        # F7: 신주 발행 없음 (유상증자 + CB/BW 전환 포함)
        if not fin.get('new_shares_issued', False):
            score += 1
        # F8: 매출총이익률 개선
        if fin.get('gross_margin', 0) > fin.get('gross_margin_prev', 0):
            score += 1
        # F9: 자산회전율 개선 (매출/총자산)
        if fin.get('asset_turnover', 0) > fin.get('asset_turnover_prev', 0):
            score += 1

        return score

    def scan_universe(self, universe_financials: List[dict]) -> List[Signal]:
        """저PBR(하위 20%) + F-Score 8~9점 종목 시그널 생성."""
        # PBR 있는 종목만
        valid = [f for f in universe_financials if f.get('pbr') is not None and f['pbr'] > 0]
        if len(valid) < 20:
            return []

        # PBR 하위 20% 기준선
        pbr_cutoff = pd.Series([f['pbr'] for f in valid]).quantile(0.20)

        signals = []
        for fin in valid:
            if fin['pbr'] > pbr_cutoff:
                continue
            score = self.calc_fscore(fin)
            if score >= 8:
                sig = Signal(
                    strategy_name=self.name,
                    ticker=fin['ticker'],
                    ticker_name=fin.get('name', ''),
                    entry_price=fin.get('close', 0),
                    target_pct=0.10,
                    stop_loss_pct=-0.08,
                    hold_days_min=60,
                    hold_days_max=90,
                    confidence=0.55 + score * 0.05,
                    exec_timing="EOD",
                    category="legendary",
                    grade="A",
                    sector=fin.get('sector', ''),
                )
                sig.calc_rr_ratio()
                signals.append(sig)

        return signals

    def check_exit(self, position: Dict, current_row: pd.Series) -> Optional[str]:
        """분기 리밸런싱 시점에 청산 판단. F-Score 0~3점 → 매수 회피."""
        return None
