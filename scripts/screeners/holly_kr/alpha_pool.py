"""
Phase F-3: ALPHA Pool 관리 (5년 검증 마스터 풀)

분기 1회 5년 백테스트 결과로 ALPHA 풀 식별/저장/로드.
일별 nightly_selector는 이 풀 안에서만 60일/180일 듀얼 평가.

저장 형식 (data/holly_kr/alpha_pool.json):
{
  "updated_at": "2026-04-01T00:00:00",
  "lookback_days": 1500,
  "num_windows": 12,
  "alpha_strategies": [
    {
      "name": "box_range_watch",
      "category": "breakout",
      "tier": "ALPHA",  // ALPHA, CONSISTENT, BORDERLINE
      "windows_passed": 9,  // 12 윈도우 중 PASS 횟수
      "total_trades": 1240,
      "win_rate": 0.51,
      "profit_factor": 2.14,
      "pf_ci_lower": 1.65,
      "pf_ci_upper": 3.05,
      "sharpe_ratio": 1.92,
      "sortino_ratio": 5.43,
      "max_drawdown": -0.28,
      "calmar_ratio": 6.85,
      "deflated_sharpe": 0.97,
      "fitness_score": 1.4,
      "optimal_target_mult": 5.0,    // 그리드 서치 결과
      "optimal_stop_mult": 2.0,
      "regimes_passed": ["bull", "sideways"],  // 작동 레짐
    },
    ...
  ],
  "pbo": 0.06,  // 전체 시스템 과적합 확률
  "metadata": {
    "total_strategies_tested": 37,
    "alpha_count": 1,
    "consistent_count": 3,
    "borderline_count": 2
  }
}
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import DATA_DIR

ALPHA_POOL_FILE = DATA_DIR / 'holly_kr' / 'alpha_pool.json'


def save_alpha_pool(strategies: List[Dict], pbo: float = 0.0,
                     lookback_days: int = 1500, num_windows: int = 12) -> None:
    """ALPHA 풀 저장 (분기 1회 5년 백테스트 결과)."""
    ALPHA_POOL_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        'updated_at': datetime.now().isoformat(),
        'lookback_days': lookback_days,
        'num_windows': num_windows,
        'alpha_strategies': strategies,
        'pbo': round(pbo, 3),
        'metadata': {
            'total_strategies_tested': 37,
            'alpha_count': sum(1 for s in strategies if s['tier'] == 'ALPHA'),
            'consistent_count': sum(1 for s in strategies if s['tier'] == 'CONSISTENT'),
            'borderline_count': sum(1 for s in strategies if s['tier'] == 'BORDERLINE'),
        }
    }

    with open(ALPHA_POOL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ALPHA 풀 저장: {ALPHA_POOL_FILE}")
    print(f"  - ALPHA: {data['metadata']['alpha_count']}")
    print(f"  - CONSISTENT: {data['metadata']['consistent_count']}")
    print(f"  - BORDERLINE: {data['metadata']['borderline_count']}")
    print(f"  - PBO: {pbo:.0%}")


def load_alpha_pool() -> Optional[Dict]:
    """ALPHA 풀 로드 (nightly_selector + daily-scan에서 호출)."""
    if not ALPHA_POOL_FILE.exists():
        return None
    try:
        with open(ALPHA_POOL_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception:
        return None


def get_alpha_strategy_names(min_tier: str = 'BORDERLINE') -> List[str]:
    """ALPHA 풀에서 전략명 리스트 반환.

    Args:
        min_tier: 최소 등급 (ALPHA / CONSISTENT / BORDERLINE)
    """
    data = load_alpha_pool()
    if not data:
        return []

    tier_order = {'ALPHA': 3, 'CONSISTENT': 2, 'BORDERLINE': 1}
    min_level = tier_order.get(min_tier, 1)

    return [
        s['name'] for s in data['alpha_strategies']
        if tier_order.get(s['tier'], 0) >= min_level
    ]


def get_alpha_metadata(strategy_name: str) -> Optional[Dict]:
    """특정 전략의 5년 메타데이터 반환 (nightly_selector 점수 가중용)."""
    data = load_alpha_pool()
    if not data:
        return None
    for s in data['alpha_strategies']:
        if s['name'] == strategy_name:
            return s
    return None


def classify_strategy(report_4w: Dict) -> str:
    """워크포워드 4 윈도우 (또는 12 윈도우) 결과로 tier 분류.

    기준 (Phase A+B 강화):
    - ALPHA: 4중 3+ PASS + PF CI 하한 > 1.0 + Sharpe ≥ 1.5 + MDD > -50%
    - CONSISTENT: 4중 3+ PASS + Sharpe ≥ 1.0
    - BORDERLINE: 누적 PF ≥ 1.2 + 거래 ≥ 30
    - FAIL: 그 외
    """
    windows_passed = report_4w.get('windows_passed', 0)
    num_windows = report_4w.get('num_windows', 4)
    pass_threshold = (num_windows * 3) // 4  # 75% 이상

    pf = report_4w.get('profit_factor', 0)
    ci_lower = report_4w.get('pf_ci_lower', 0)
    sharpe = report_4w.get('sharpe_ratio', 0)
    mdd = report_4w.get('max_drawdown', 0)
    trades = report_4w.get('total_trades', 0)

    if (windows_passed >= pass_threshold
            and ci_lower > 1.0
            and sharpe >= 1.5
            and mdd > -0.50
            and trades >= 30):
        return 'ALPHA'
    if (windows_passed >= pass_threshold
            and sharpe >= 1.0
            and trades >= 30):
        return 'CONSISTENT'
    if pf >= 1.2 and trades >= 30:
        return 'BORDERLINE'
    return 'FAIL'


if __name__ == '__main__':
    # 테스트: 현재 ALPHA 풀 로드
    pool = load_alpha_pool()
    if pool:
        print(f"ALPHA 풀 ({pool['updated_at']}):")
        for s in pool['alpha_strategies']:
            print(f"  [{s['tier']}] {s['name']:<25s} "
                  f"PF={s['profit_factor']:.2f} "
                  f"Sharpe={s['sharpe_ratio']:.2f} "
                  f"MDD={s['max_drawdown']:.0%}")
        print(f"\nPBO: {pool['pbo']:.0%}")
    else:
        print("ALPHA 풀 미생성. 5년 백테스트 후 자동 생성됨.")
