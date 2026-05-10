"""
Sub-agent 사전 데이터 수집 (Phase G-9 최적화)

signals_today.json (31개 시그널) 읽어서 각 종목 가격/거래량/기술적 지표를
일괄 계산 → sub_agent_input.json 으로 저장.

Sub-agent (Stage A Haiku, Stage B Opus)는 이 JSON을 prompt에 받아서
Web 검색 + DART만 추가 호출 → 가격 데이터 재조회 시간 절감.

목적:
- 각 sub-agent가 OHLCV 로드/계산 반복 시간 제거 (-3~5분)
- 통일된 정량 지표 (sub-agent마다 다른 계산 방지)
- daily-orchestrate slash command 5단계 중 2단계
"""

import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Windows console UTF-8
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / '.cache' / 'ohlcv' / 'ohlcv_cache.pkl'
SIGNALS_FILE = ROOT / 'data' / 'holly_kr' / 'signals_today.json'
OUTPUT_FILE = ROOT / 'data' / 'holly_kr' / 'sub_agent_input.json'


def load_ohlcv_cache():
    """OHLCV 영구 캐시 로드 (1500일 키 우선)"""
    with open(CACHE_FILE, 'rb') as f:
        return pickle.load(f)


def find_ohlcv(cache: dict, ticker: str) -> pd.DataFrame:
    """ticker에 맞는 OHLCV 검색 (1500 → 500 → 250 우선순위)"""
    for days in (1500, 500, 250, 200):
        key = f'{ticker}_{days}'
        if key in cache:
            return cache[key]
    # fallback: 모든 키 검색
    for k, v in cache.items():
        if k.startswith(f'{ticker}_'):
            return v
    return None


def compute_indicators(df: pd.DataFrame) -> dict:
    """가격/거래량/기술적 지표 일괄 계산"""
    if df is None or len(df) < 60:
        return {'error': 'insufficient_data', 'rows': 0 if df is None else len(df)}

    close = df['Close']
    high = df['High']
    low = df['Low']
    volume = df['Volume']
    last = close.iloc[-1]

    # 가격 모멘텀 (수익률)
    def ret(days):
        if len(close) <= days:
            return None
        return float((close.iloc[-1] / close.iloc[-1 - days] - 1) * 100)

    # SMA
    sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
    sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
    sma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else None
    sma100 = close.rolling(100).mean().iloc[-1] if len(close) >= 100 else None

    # SMA 기울기 (1개월 전 대비, % 변화)
    def sma_slope(window, days_back=20):
        if len(close) < window + days_back:
            return None
        sma_now = close.rolling(window).mean().iloc[-1]
        sma_then = close.rolling(window).mean().iloc[-1 - days_back]
        if pd.isna(sma_now) or pd.isna(sma_then) or sma_then == 0:
            return None
        return float((sma_now / sma_then - 1) * 100)

    # 52주 위치
    if len(close) >= 252:
        high_52w = high.iloc[-252:].max()
        low_52w = low.iloc[-252:].min()
        pos_52w = float((last - low_52w) / (high_52w - low_52w) * 100) if high_52w > low_52w else 50.0
    else:
        high_52w = high.max()
        low_52w = low.min()
        pos_52w = float((last - low_52w) / (high_52w - low_52w) * 100) if high_52w > low_52w else 50.0

    # ATR(14)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else None
    atr_pct = float(atr / last * 100) if atr else None

    # 거래대금 (30일 평균, 단위: 억)
    value = (close * volume / 1e8)
    daily_value_eok_30d = float(value.rolling(30).mean().iloc[-1]) if len(value) >= 30 else None
    daily_value_eok_today = float(value.iloc[-1])
    value_surge = (
        float(daily_value_eok_today / daily_value_eok_30d)
        if daily_value_eok_30d else None
    )

    # 최근 5일 + 20일 변동성 (연율화)
    daily_ret = close.pct_change()
    vol_5d = float(daily_ret.iloc[-5:].std() * np.sqrt(252) * 100) if len(daily_ret) >= 5 else None
    vol_20d = float(daily_ret.iloc[-20:].std() * np.sqrt(252) * 100) if len(daily_ret) >= 20 else None

    # RSI(14) — 모멘텀 보조
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = float((100 - 100 / (1 + rs.iloc[-1]))) if not pd.isna(rs.iloc[-1]) else None

    # Stage 2 검증 (Weinstein/Minervini)
    stage2 = (
        last is not None
        and sma200 is not None
        and sma50 is not None
        and last > sma200
        and last > sma50
        and sma50 > sma200
        and sma_slope(200, 20) is not None
        and sma_slope(200, 20) > 0
    )

    return {
        'last_close': float(last),
        'last_date': str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1]),
        'returns_pct': {
            '1d': ret(1),
            '5d': ret(5),
            '20d': ret(20),
            '60d': ret(60),
            '120d': ret(120),
            '252d': ret(252),
        },
        'sma': {
            '20': float(sma20) if sma20 else None,
            '50': float(sma50) if sma50 else None,
            '100': float(sma100) if sma100 else None,
            '200': float(sma200) if sma200 else None,
            'slope_50_20d_pct': sma_slope(50, 20),
            'slope_200_20d_pct': sma_slope(200, 20),
        },
        'position': {
            'vs_sma20_pct': float((last / sma20 - 1) * 100) if sma20 else None,
            'vs_sma50_pct': float((last / sma50 - 1) * 100) if sma50 else None,
            'vs_sma100_pct': float((last / sma100 - 1) * 100) if sma100 else None,
            'vs_sma200_pct': float((last / sma200 - 1) * 100) if sma200 else None,
            'pos_52w_pct': pos_52w,
            'high_52w': float(high_52w),
            'low_52w': float(low_52w),
        },
        'volatility': {
            'atr14_pct': atr_pct,
            'vol_5d_annual_pct': vol_5d,
            'vol_20d_annual_pct': vol_20d,
            'rsi14': rsi,
        },
        'liquidity': {
            'daily_value_eok_today': daily_value_eok_today,
            'daily_value_eok_30d_avg': daily_value_eok_30d,
            'value_surge_ratio': value_surge,
        },
        'stage_2_pass': bool(stage2),
    }


def main():
    print(f"[{datetime.now()}] Sub-agent 사전 데이터 수집 시작")

    if not SIGNALS_FILE.exists():
        print(f"ERROR: {SIGNALS_FILE} 없음. daily-scan 먼저 실행 필요.")
        sys.exit(1)

    with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
        signals_data = json.load(f)

    print(f"  signals_today.json 로드: {signals_data['count']}개 시그널")

    cache = load_ohlcv_cache()
    print(f"  OHLCV 캐시 로드: {len(cache)} 종목")

    # ========== DART 공시 + FnGuide 재무 병렬 수집 ==========
    tickers = [sig['ticker'] for sig in signals_data['signals']]

    print(f"\n[{datetime.now()}] DART + FnGuide 사전 수집 시작 ({len(tickers)}개)")
    try:
        from sub_agent_dart_fnguide import collect_for_tickers
        # 시총 매핑: current_price * shares (signals_today.json에 shares 없으면 None)
        market_caps_eok = {}  # ticker → 시총 (억원)
        # ⚠️ 시총은 universe.py에서 계산하므로 일단 None (PER 직접 계산 X)
        df_data = collect_for_tickers(tickers, market_caps=market_caps_eok, max_workers=6)
    except Exception as e:
        print(f"  WARNING: DART/FnGuide 수집 실패 {e}, OHLCV indicators만 진행")
        df_data = {}
    print(f"[{datetime.now()}] DART + FnGuide 수집 완료\n")

    output = {
        'date': signals_data['date'],
        'generated_at': datetime.now().isoformat(),
        'count': signals_data['count'],
        'signals': []
    }

    for sig in signals_data['signals']:
        ticker = sig['ticker']
        df = find_ohlcv(cache, ticker)
        indicators = compute_indicators(df)

        merged = {
            # 시그널 원본
            'ticker': ticker,
            'name': sig['name'],
            'sector': sig.get('sector', ''),
            'strategy_name': sig['strategy_name'],
            'category': sig['category'],
            'entry_price': sig['entry_price'],
            'current_price': sig['current_price'],
            'target_price': sig['target_price'],
            'stop_loss_price': sig['stop_loss_price'],
            'target_pct': sig['target_pct'],
            'stop_loss_pct': sig['stop_loss_pct'],
            'rr_ratio': sig['rr_ratio'],
            'confidence': sig['confidence'],
            'signal_tier': sig['signal_tier'],
            'reason': sig['reason'],
            'hold_days_max': sig['hold_days_max'],
            'exit_rules_summary': sig.get('exit_rules_summary', ''),
            # 사전 계산 지표
            'indicators': indicators,
            # DART 공시 + FnGuide 재무 (사전 수집)
            'dart': df_data.get(ticker, {}).get('dart', {'error': 'not_collected'}),
            'fnguide': df_data.get(ticker, {}).get('fnguide', {'error': 'not_collected'}),
        }
        output['signals'].append(merged)
        ind_str = (
            f"PF stage2={indicators.get('stage_2_pass', False)}"
            if 'error' not in indicators else f"ERROR {indicators['error']}"
        )
        print(f"  ✓ {ticker} {sig['name']:12s} [{sig['strategy_name']:25s}] {ind_str}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[{datetime.now()}] 완료")
    print(f"  → {OUTPUT_FILE}")
    print(f"  → {output['count']}개 종목, 평균 30+ 지표")


if __name__ == '__main__':
    main()
