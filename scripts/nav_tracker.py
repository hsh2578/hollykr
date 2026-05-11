"""
NAV 추적 + KOSPI 대비 성과 측정 (Phase G-11 — 알고픽 인사이트)

알고픽: "최근 2개월 NAV를 시장과 나란히 두고, 미세한 긴장감과 자기점검 감각"

매주 weekly_review에서 호출:
- BUY 종목 평균 수익률 = HollyKR 가상 NAV
- 같은 기간 KOSPI 변화 = 벤치마크
- Alpha = NAV - KOSPI (시장 초과 수익)
"""

import json
import sys
import pickle
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data' / 'holly_kr'
MEMORY_DIR = DATA_DIR / 'memory'
OHLCV_CACHE = ROOT / '.cache' / 'ohlcv' / 'ohlcv_cache.pkl'
NAV_FILE = MEMORY_DIR / 'nav_history.json'


def load_ohlcv(ticker: str):
    if not OHLCV_CACHE.exists():
        return None
    with open(OHLCV_CACHE, 'rb') as f:
        cache = pickle.load(f)
    for days in (1500, 500, 250, 200):
        key = f'{ticker}_{days}'
        if key in cache:
            return cache[key]
    return None


def get_kospi_return(start_date: str, end_date: str) -> Optional[float]:
    """KOSPI 200 ETF (069500)로 KOSPI 수익률 대체 계산"""
    df = load_ohlcv('069500')
    if df is None or len(df) == 0:
        return None
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        df_period = df[(df.index >= start) & (df.index <= end)]
        if len(df_period) < 2:
            return None
        return float((df_period.iloc[-1]['Close'] / df_period.iloc[0]['Close'] - 1) * 100)
    except Exception:
        return None


def calculate_nav_for_buys(buys: List[Dict], target_date: str) -> Dict:
    """BUY 종목 가중평균 수익률 vs KOSPI"""
    if not buys:
        return {'nav_return_pct': 0, 'kospi_return_pct': 0, 'alpha_pct': 0, 'count': 0, 'period': ''}

    total_weighted = 0
    total_weight = 0
    earliest_date = min(b.get('entry_date', target_date) for b in buys)
    valid_count = 0

    for b in buys:
        df = load_ohlcv(b['ticker'])
        if df is None:
            continue
        try:
            entry_dt = datetime.strptime(b.get('entry_date', target_date), '%Y-%m-%d')
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')
            df_period = df[(df.index >= entry_dt) & (df.index <= target_dt)]
            if len(df_period) < 1:
                continue
            current_price = float(df_period.iloc[-1]['Close'])
            entry_price = b.get('entry_price', current_price)
            if entry_price <= 0:
                continue
            ret_pct = (current_price - entry_price) / entry_price * 100
            weight = b.get('weight_pct', 1)
            total_weighted += ret_pct * weight
            total_weight += weight
            valid_count += 1
        except Exception:
            continue

    nav_return = (total_weighted / total_weight) if total_weight > 0 else 0
    kospi_return = get_kospi_return(earliest_date, target_date) or 0
    alpha = nav_return - kospi_return

    return {
        'nav_return_pct': round(nav_return, 2),
        'kospi_return_pct': round(kospi_return, 2),
        'alpha_pct': round(alpha, 2),
        'count': valid_count,
        'period': f'{earliest_date} ~ {target_date}',
    }


def append_nav_history(entry: Dict):
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    history = []
    if NAV_FILE.exists():
        try:
            with open(NAV_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []
    entry['recorded_at'] = datetime.now().isoformat()
    history.append(entry)
    with open(NAV_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def format_nav_summary(nav_data: Dict) -> str:
    nav = nav_data['nav_return_pct']
    kospi = nav_data['kospi_return_pct']
    alpha = nav_data['alpha_pct']
    if alpha > 0:
        verdict = f"✓ KOSPI 초과 수익 {alpha:+.2f}%pt"
    elif alpha < 0:
        verdict = f"✗ KOSPI 미달 {alpha:+.2f}%pt"
    else:
        verdict = "○ KOSPI 수준"

    return f"""━ 시장 대비 성과 (NAV vs KOSPI) ━
기간:        {nav_data['period']}
HollyKR NAV: {nav:+.2f}%
KOSPI 수익률: {kospi:+.2f}%
Alpha:       {alpha:+.2f}%pt {verdict}
종목 수:     {nav_data['count']}개"""


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"[{datetime.now()}] NAV 추적 테스트")
    test_buys = [
        {'ticker': '141080', 'name': '리가켐바이오', 'entry_price': 180000, 'entry_date': '2026-04-20', 'weight_pct': 12},
        {'ticker': '039200', 'name': '오스코텍', 'entry_price': 48000, 'entry_date': '2026-04-20', 'weight_pct': 5},
        {'ticker': '042700', 'name': '한미반도체', 'entry_price': 250000, 'entry_date': '2026-04-20', 'weight_pct': 8},
    ]
    result = calculate_nav_for_buys(test_buys, today)
    print(format_nav_summary(result))
    append_nav_history(result)
    print(f"\n  → {NAV_FILE} (누적 저장)")
