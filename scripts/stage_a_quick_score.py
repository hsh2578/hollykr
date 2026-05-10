"""
Stage A 빠른 정량 스코어러 (Phase G-9 환각 방지 최종)

Haiku sub-agent 종목명 환각 문제 발견 → Python으로 대체.
- sub_agent_input.json (사전 수집된 30+ 지표) 기반 점수 계산
- ALPHA pool 가산점
- Top 15 선정
- 종목명/티커 KRX CSV 그대로 (환각 0%)

목적:
- 기존 Stage A Haiku (6분 + 환각) → Python (0.5초 + 환각 0)
- 사용자 룰 준수: "모든 시그널 평가" (31개 모두 점수)
- Stage B Opus 깊은 분석은 Top 15만 (정성)
"""

import json
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = ROOT / 'data' / 'holly_kr' / 'sub_agent_input.json'
ALPHA_POOL_FILE = ROOT / 'data' / 'holly_kr' / 'alpha_pool.json'
OUTPUT_FILE = ROOT / 'data' / 'holly_kr' / 'stage_a_result.json'

TOP_N = 15


def load_alpha_pool():
    if ALPHA_POOL_FILE.exists():
        with open(ALPHA_POOL_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {s['name']: s for s in data.get('alpha_strategies', [])}
    return {}


def score_signal(sig: dict, alpha_pool: dict) -> dict:
    """
    한 종목 점수 계산 (0-100점).
    Returns: {score, reasons, breakdown}
    """
    ind = sig.get('indicators', {})
    if 'error' in ind:
        return {
            'score': 0,
            'reasons': [f"indicators error: {ind['error']}"],
            'breakdown': {}
        }

    score = 0.0
    reasons = []
    breakdown = {}

    # ============ 1. 정량 자동 평가 (0~50점) ============
    quant = 0

    # Stage 2 통과 (Weinstein/Minervini)
    if ind.get('stage_2_pass'):
        quant += 10
        reasons.append('Stage2 ✓')

    # 추세 강도
    r = ind.get('returns_pct', {})
    if r.get('252d') is not None:
        if r['252d'] > 30:
            quant += 5
            reasons.append(f'1Y +{r["252d"]:.0f}%')
    if r.get('60d') is not None and r['60d'] > 10:
        quant += 3
        reasons.append(f'3M +{r["60d"]:.0f}%')

    # SMA200 기울기
    sma = ind.get('sma', {})
    slope200 = sma.get('slope_200_20d_pct')
    if slope200 is not None and slope200 > 0:
        quant += 2

    # RSI 건강
    rsi = ind.get('volatility', {}).get('rsi14')
    if rsi is not None:
        if 60 <= rsi <= 75:
            quant += 3
            reasons.append(f'RSI{rsi:.0f} healthy')
        elif rsi > 80:
            quant -= 3
            reasons.append(f'RSI{rsi:.0f} 과매수')
        elif rsi < 30:
            quant += 2
            reasons.append(f'RSI{rsi:.0f} 과매도반등')

    # 유동성
    liq = ind.get('liquidity', {})
    daily_value = liq.get('daily_value_eok_30d_avg')
    if daily_value is not None:
        if daily_value > 100:
            quant += 5
        elif daily_value < 30:
            quant -= 10
            reasons.append(f'유동성↓ {daily_value:.0f}억')

    # 가격 위치
    pos = ind.get('position', {})
    vs200 = pos.get('vs_sma200_pct')
    vs50 = pos.get('vs_sma50_pct')
    if vs200 is not None and vs50 is not None:
        if vs200 > 0 and vs50 > 0:
            quant += 5

    pos_52w = pos.get('pos_52w_pct')
    if pos_52w is not None:
        if pos_52w > 80:
            quant += 3
        elif pos_52w < 20:
            quant += 2

    # 변동성
    vol_20d = ind.get('volatility', {}).get('vol_20d_annual_pct')
    if vol_20d is not None:
        if vol_20d < 50:
            quant += 3
        elif vol_20d > 80:
            quant -= 3

    # Buying Climax 경계 (Phase G-9 환경 — 강세 시장 고려, 보수)
    if r.get('252d') is not None and r['252d'] > 200:
        quant -= 5  # -10 → -5 (강세장 정상 모멘텀 고려)
        reasons.append(f'1Y +{r["252d"]:.0f}% climax 경계')
    if r.get('5d') is not None and r['5d'] > 50:
        quant -= 10
        reasons.append(f'5d +{r["5d"]:.0f}% 단기급등')

    breakdown['quant'] = quant
    score += quant

    # ============ 2. 전략 가산점 (0~15점) ============
    strat_score = 0
    strat = sig['strategy_name']

    if strat in alpha_pool:
        # ALPHA pool tier 확인
        tier = alpha_pool[strat].get('tier', '')
        if tier == 'ALPHA':
            strat_score += 15
        elif tier == 'CONSISTENT':
            strat_score += 10
        else:
            strat_score += 8
        reasons.append(f'★ALPHA pool ({tier})')
    elif strat in ('clenow_momentum', 'bottom_breakout', 'tailwind'):
        # 시장 적응 Top 3
        strat_score += 3
    elif strat == 'new_high_52w_approach':
        # ALPHA pool 백업
        strat_score += 10
        reasons.append('★ALPHA pool')

    breakdown['strategy'] = strat_score
    score += strat_score

    # ============ 3. 빠른 정성 (0~35점) ============
    qual_score = 0

    sector = sig.get('sector', '')

    # 섹터 health
    if any(k in sector for k in ('의약', '바이오', '제약')):
        qual_score += 5
        reasons.append('섹터: 바이오 헤지')
    elif any(k in sector for k in ('방산', '에너지', '항공우주')):
        qual_score += 5
        reasons.append('섹터: 방산/에너지 헤지')
    elif any(k in sector for k in ('전기', '전자', '반도체')):
        # 외인 매도 위험 환경
        qual_score -= 3

    # 시총 추정 (current_price × ?  근데 데이터 없음 — 대신 거래대금으로 추정)
    if daily_value and daily_value > 1000:
        qual_score += 3  # 대형주
    if daily_value and daily_value < 10:
        qual_score -= 15  # 작전 의심
        reasons.append(f'거래대금 {daily_value:.0f}억 작전 위험')

    # RR 비율
    rr = sig.get('rr_ratio', 0)
    if rr >= 3.0:
        qual_score += 3
    elif rr < 2.0:
        qual_score -= 3

    # 신호 신뢰도
    conf = sig.get('confidence', 0)
    if conf >= 0.95:
        qual_score += 2

    breakdown['qualitative'] = qual_score
    score += qual_score

    return {
        'score': round(score, 1),
        'reasons': reasons,
        'breakdown': breakdown,
    }


def main():
    print(f"[{datetime.now()}] Stage A 빠른 정량 스코어러 시작")

    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} 없음. sub_agent_data_prep.py 먼저 실행.")
        sys.exit(1)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    alpha_pool = load_alpha_pool()
    print(f"  ALPHA pool 로드: {len(alpha_pool)}개 전략 ({list(alpha_pool.keys())})")

    # 모든 시그널 점수 계산
    results = []
    for sig in data['signals']:
        scoring = score_signal(sig, alpha_pool)
        results.append({
            'ticker': sig['ticker'],
            'name': sig['name'],
            'sector': sig['sector'],
            'strategy_name': sig['strategy_name'],
            'category': sig['category'],
            'entry_price': sig['entry_price'],
            'current_price': sig['current_price'],
            'target_pct': sig['target_pct'],
            'stop_loss_pct': sig['stop_loss_pct'],
            'rr_ratio': sig['rr_ratio'],
            'confidence': sig['confidence'],
            'score': scoring['score'],
            'reasons': scoring['reasons'],
            'breakdown': scoring['breakdown'],
        })

    # 점수 내림차순
    results.sort(key=lambda x: x['score'], reverse=True)

    # 사용자 룰: ALPHA pool 종목은 무조건 Top 15 진입 (cut 면제)
    alpha_strategy_names = set(alpha_pool.keys())
    alpha_signals = [r for r in results if r['strategy_name'] in alpha_strategy_names]
    non_alpha = [r for r in results if r['strategy_name'] not in alpha_strategy_names]

    # ALPHA pool 강제 진입 (점수 무관)
    forced_alpha = alpha_signals
    n_alpha = len(forced_alpha)
    n_remain = TOP_N - n_alpha

    # 나머지는 점수순으로 채움
    remain_top = non_alpha[:n_remain] if n_remain > 0 else []

    top_n = forced_alpha + remain_top
    # Top 안에서 점수 순 재정렬
    top_n.sort(key=lambda x: x['score'], reverse=True)

    # 탈락 = 전체 - top_n
    top_tickers = {r['ticker'] for r in top_n}
    dropped = [r for r in results if r['ticker'] not in top_tickers]

    # 통계
    avg_score = sum(r['score'] for r in results) / len(results) if results else 0
    avg_top = sum(r['score'] for r in top_n) / len(top_n) if top_n else 0
    avg_drop = sum(r['score'] for r in dropped) / len(dropped) if dropped else 0

    strategy_counts_top = {}
    for r in top_n:
        s = r['strategy_name']
        strategy_counts_top[s] = strategy_counts_top.get(s, 0) + 1

    output = {
        'date': data['date'],
        'generated_at': datetime.now().isoformat(),
        'total_signals': len(results),
        'top_n': TOP_N,
        'avg_score_total': round(avg_score, 1),
        'avg_score_top': round(avg_top, 1),
        'avg_score_dropped': round(avg_drop, 1),
        'strategy_distribution_top': strategy_counts_top,
        'top': top_n,
        'dropped': dropped,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 콘솔 출력
    print(f"\n[Top {TOP_N} 통과] avg {avg_top:.1f}")
    print(f"{'순위':<4} {'티커':<8} {'종목':<14} {'전략':<22} {'점수':<6} 핵심 사유")
    print('-' * 100)
    for i, r in enumerate(top_n, 1):
        reasons_str = ' / '.join(r['reasons'][:3])[:60]
        print(f"{i:<4} {r['ticker']:<8} {r['name']:<14} {r['strategy_name']:<22} {r['score']:<6.1f} {reasons_str}")

    print(f"\n[탈락 {len(dropped)}] avg {avg_drop:.1f}")
    for r in dropped:
        reasons_str = ' / '.join(r['reasons'][:2])[:50]
        print(f"  {r['ticker']:<8} {r['name']:<14} {r['strategy_name']:<22} {r['score']:<6.1f} {reasons_str}")

    print(f"\n[전략 분산 — Top {TOP_N}]")
    for s, n in sorted(strategy_counts_top.items(), key=lambda x: -x[1]):
        print(f"  {s:<25} {n}개")

    print(f"\n[완료] {datetime.now()}")
    print(f"  → {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
