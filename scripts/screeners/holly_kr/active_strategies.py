"""
야간 전략 선정 결과 저장/로드

18:00 야간 선정 → active_strategies.json 저장
14:40 실전 스캔 → active_strategies.json 로드
"""

import json
from datetime import datetime
from pathlib import Path

from config import CACHE_DIR

ACTIVE_FILE = CACHE_DIR / 'active_strategies.json'


def save_active(strategy_names: list, metrics_summary: dict = None):
    """야간 선정 결과 저장"""
    data = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'strategies': strategy_names,
        'count': len(strategy_names),
        'metrics': metrics_summary or {},
    }
    with open(ACTIVE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  활성 전략 저장: {ACTIVE_FILE.name} ({len(strategy_names)}개)")


def load_active() -> list:
    """야간 선정 결과 로드 (당일 것만)"""
    if not ACTIVE_FILE.exists():
        return []
    try:
        with open(ACTIVE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 당일 데이터인지 확인
        today = datetime.now().strftime('%Y-%m-%d')
        if data.get('date') == today:
            print(f"  야간 선정 결과 로드: {data['count']}개 전략 ({data['updated_at']})")
            return data['strategies']
        else:
            print(f"  야간 선정 결과 없음 (어제 데이터: {data.get('date')})")
            return []
    except Exception:
        return []
