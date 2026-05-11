"""
매주 토요일 복기 시스템 (Phase G-10 — 알고픽 인사이트)

지난 7일 analysis_YYYY-MM-DD.json을 모두 로드하여:
- 한 주 BUY 추천 종목 추적
- 실제 결과 (손절 발동 / 목표 도달 / 보유 중)
- 부서장 판단 vs 실제 결과 비교
- 텔레그램 주간 리포트 송출

알고픽 인사이트:
"감정도 흔적으로 들어와야. 매주 토요일 판단 로그/매매 로그/매크로 분석 DB 복기"

목적:
- 시스템 학습 (postmortem 부재 해결)
- 부서장 판단 품질 검증
- 매수 후 결과 추적
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data' / 'holly_kr'
OHLCV_CACHE = ROOT / '.cache' / 'ohlcv' / 'ohlcv_cache.pkl'


def load_recent_analysis(days: int = 30) -> List[Dict]:
    """최근 N일 analysis_YYYY-MM-DD.json 로드 (default 30일 — 과거 분석 누적)"""
    today = datetime.now()
    results = []
    for i in range(days):
        d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        f = DATA_DIR / f'analysis_{d}.json'
        if f.exists():
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
                data['_filename'] = f.name
                results.append(data)
    results.sort(key=lambda x: x.get('date', ''))
    return results


def load_ohlcv_for_ticker(ticker: str):
    """OHLCV 캐시에서 종목 가격 데이터 로드"""
    import pickle
    if not OHLCV_CACHE.exists():
        return None
    with open(OHLCV_CACHE, 'rb') as f:
        cache = pickle.load(f)
    for days in (1500, 500, 250, 200):
        key = f'{ticker}_{days}'
        if key in cache:
            return cache[key]
    return None


def track_buy_result(ticker: str, entry_date: str, entry_price: float, target: float, stop: float, hold_days: int) -> Dict:
    """매수 후 N일 결과 추적 (목표/손절/보유)"""
    df = load_ohlcv_for_ticker(ticker)
    if df is None or len(df) == 0:
        return {'status': 'no_data', 'ticker': ticker}

    try:
        entry_dt = datetime.strptime(entry_date, '%Y-%m-%d')
    except Exception:
        return {'status': 'date_parse_error', 'date': entry_date}

    # entry_date 이후 데이터
    after = df[df.index >= entry_dt]
    if len(after) == 0:
        return {'status': 'no_post_entry', 'entry_date': entry_date}

    # 가능한 한 hold_days 만큼만 추적
    after = after.iloc[:hold_days]

    triggered_target = False
    triggered_stop = False
    trigger_date = None
    trigger_price = None
    final_price = None

    for idx, row in after.iterrows():
        if row['Low'] <= stop:
            triggered_stop = True
            trigger_date = idx.strftime('%Y-%m-%d')
            trigger_price = stop
            break
        if row['High'] >= target:
            triggered_target = True
            trigger_date = idx.strftime('%Y-%m-%d')
            trigger_price = target
            break

    final_close = after.iloc[-1]['Close']
    final_date = after.index[-1].strftime('%Y-%m-%d')
    days_held = len(after)

    if triggered_stop:
        status = 'stop_triggered'
        pnl_pct = (stop - entry_price) / entry_price * 100
        exit_price = stop
    elif triggered_target:
        status = 'target_reached'
        pnl_pct = (target - entry_price) / entry_price * 100
        exit_price = target
    else:
        status = 'holding'
        pnl_pct = (final_close - entry_price) / entry_price * 100
        exit_price = final_close

    return {
        'ticker': ticker,
        'entry_date': entry_date,
        'entry_price': entry_price,
        'target': target,
        'stop': stop,
        'status': status,
        'trigger_date': trigger_date,
        'exit_price': float(exit_price),
        'pnl_pct': round(pnl_pct, 2),
        'days_held': days_held,
        'final_date': final_date,
    }


def generate_weekly_review() -> str:
    """주간 리포트 생성"""
    analyses = load_recent_analysis(days=30)
    if not analyses:
        return "주간 리포트: 최근 7일 analysis 데이터 없음"

    report_lines = []
    report_lines.append("━" * 30)
    report_lines.append(f"◆ HollyKR 주간 복기 ({datetime.now().strftime('%Y-%m-%d %A')})")
    report_lines.append("━" * 30)
    report_lines.append("")
    report_lines.append(f"분석 기간: {analyses[0].get('date', 'N/A')} ~ {analyses[-1].get('date', 'N/A')}")
    report_lines.append(f"부서장 의사결정 일수: {len(analyses)}건")
    report_lines.append("")

    # 한 주 BUY 종목 추적
    all_buys = []
    for a in analyses:
        date = a.get('date', '')
        for stock in a.get('top10', []):
            decision = str(stock.get('decision', ''))
            if 'BUY' in decision:
                all_buys.append({
                    'date': date,
                    'ticker': stock.get('ticker'),
                    'name': stock.get('name'),
                    'decision': decision,
                    'weight_pct': stock.get('weight_pct', 0),
                    'entry_price': stock.get('entry_price', 0),
                    'target': stock.get('target_price', stock.get('target', 0)),
                    'stop': stock.get('stop_price', stock.get('stop', 0)),
                    'hold_days': stock.get('hold_days', 30),
                    'reasoning': str(stock.get('reasoning', ''))[:80],
                })

    report_lines.append(f"━ BUY 추천 누적: {len(all_buys)}건 ━")
    report_lines.append("")

    if not all_buys:
        report_lines.append("BUY 추천 없음")
        return "\n".join(report_lines)

    # 결과 추적
    results = []
    for buy in all_buys:
        result = track_buy_result(
            ticker=buy['ticker'],
            entry_date=buy['date'],
            entry_price=buy['entry_price'],
            target=buy['target'],
            stop=buy['stop'],
            hold_days=buy['hold_days'],
        )
        result['name'] = buy['name']
        result['weight_pct'] = buy['weight_pct']
        results.append(result)

    # 결과별 분류
    target_reached = [r for r in results if r.get('status') == 'target_reached']
    stop_triggered = [r for r in results if r.get('status') == 'stop_triggered']
    holding = [r for r in results if r.get('status') == 'holding']
    no_data = [r for r in results if r.get('status') in ('no_data', 'no_post_entry', 'date_parse_error')]

    report_lines.append(f"🎯 목표 도달: {len(target_reached)}건")
    report_lines.append(f"🛑 손절 발동: {len(stop_triggered)}건")
    report_lines.append(f"⏳ 보유 중: {len(holding)}건")
    report_lines.append(f"❓ 추적 불가: {len(no_data)}건")
    report_lines.append("")

    # 상세 (각 종목)
    if target_reached:
        report_lines.append("━ 🎯 목표 도달 ━")
        for r in target_reached:
            report_lines.append(f"  ✓ {r['name']} ({r['ticker']}) {r['weight_pct']}% — +{r['pnl_pct']}% ({r['days_held']}일)")
        report_lines.append("")

    if stop_triggered:
        report_lines.append("━ 🛑 손절 발동 ━")
        for r in stop_triggered:
            report_lines.append(f"  ✗ {r['name']} ({r['ticker']}) {r['weight_pct']}% — {r['pnl_pct']}% ({r['days_held']}일)")
        report_lines.append("")

    if holding:
        report_lines.append("━ ⏳ 보유 중 (현재 평가) ━")
        for r in holding:
            sign = '+' if r['pnl_pct'] >= 0 else ''
            report_lines.append(f"  • {r['name']} ({r['ticker']}) {r['weight_pct']}% — {sign}{r['pnl_pct']}% ({r['days_held']}일째)")
        report_lines.append("")

    # 통계 요약
    valid_results = target_reached + stop_triggered + holding
    if valid_results:
        avg_pnl = sum(r['pnl_pct'] for r in valid_results) / len(valid_results)
        win_rate = (len(target_reached) + sum(1 for r in holding if r['pnl_pct'] > 0)) / len(valid_results) * 100
        report_lines.append("━ 통계 ━")
        report_lines.append(f"평균 손익: {avg_pnl:+.2f}%")
        report_lines.append(f"승률 (목표+양봉보유): {win_rate:.1f}%")
        report_lines.append("")

    # 부서장 판단 품질
    report_lines.append("━ 부서장 판단 품질 ━")
    report_lines.append(f"BUY 결정 → 손절 비율: {len(stop_triggered)}/{len(valid_results) if valid_results else 1} = {len(stop_triggered)/(len(valid_results) or 1)*100:.1f}%")
    if len(stop_triggered) > len(target_reached) + len(holding) // 2:
        report_lines.append("⚠️ 손절 비율 높음 → 부서장 BUY 격상 기준 재검토 필요")
    elif len(target_reached) >= len(stop_triggered):
        report_lines.append("✓ 부서장 판단 양호 (목표 도달 ≥ 손절)")
    else:
        report_lines.append("○ 보통 (보유 중 결과 대기)")

    report_lines.append("")
    report_lines.append("━" * 30)
    report_lines.append("— HollyKR 주간 복기 (CIO 시스템 학습)")

    return "\n".join(report_lines)


def main():
    print(f"[{datetime.now()}] HollyKR 주간 복기 시작")
    report = generate_weekly_review()
    print(report)

    # 파일 저장
    out_file = DATA_DIR / f'weekly_review_{datetime.now().strftime("%Y-%m-%d")}.md'
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n  → {out_file}")

    # 텔레그램 송출 (옵션)
    if '--telegram' in sys.argv:
        import asyncio
        sys.path.insert(0, str(ROOT / 'scripts'))
        from telegram_alert import send_message, _split_message

        async def send():
            for part in _split_message(report):
                await send_message(part)
        asyncio.run(send())
        print("✓ 텔레그램 송출 완료")


if __name__ == '__main__':
    main()
