"""
FnGuide 재무데이터 공유 수집기

전 종목 재무데이터를 1회 수집하여 pickle 캐시로 저장합니다.
증분 수집: 이전 캐시 데이터를 재사용하고, 캐시에 없거나 7일+ 된 종목만 새로 수집합니다.

출력: .cache/fnguide_YYYY-MM-DD.pkl

사용법:
    python collect_data.py             # 증분 수집 (이전 캐시 재사용)
    python collect_data.py --full      # 전체 재수집
"""

import os
import sys
import glob
import pickle
import time
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import CACHE_DIR, MIN_MARKET_CAP, FNGUIDE_MAX_WORKERS, MAX_CACHE_DAYS
from scripts.krx_data import get_stock_master
from scripts.fnguide_data import get_financial_data, save_fnguide_cache

# 증분 수집: N일 이내 캐시 데이터는 재사용
CACHE_REFRESH_DAYS = 7


def get_cache_filepath() -> str:
    """오늘 날짜 기반 캐시 파일 경로"""
    today = datetime.now().strftime('%Y-%m-%d')
    return str(CACHE_DIR / f'fnguide_{today}.pkl')


def cleanup_old_caches():
    """오래된 캐시 파일 정리"""
    pkl_files = sorted(
        glob.glob(str(CACHE_DIR / 'fnguide_*.pkl')),
        reverse=True
    )
    for old_file in pkl_files[MAX_CACHE_DAYS:]:
        try:
            os.remove(old_file)
            print(f"  이전 캐시 삭제: {os.path.basename(old_file)}")
        except Exception:
            pass


def _load_prev_cache():
    """이전 캐시 파일 로드 (오늘 제외, 가장 최근 것)"""
    pkl_files = sorted(
        glob.glob(str(CACHE_DIR / 'fnguide_*.pkl')),
        reverse=True
    )
    today_str = datetime.now().strftime('%Y-%m-%d')

    for pkl_file in pkl_files:
        basename = os.path.basename(pkl_file)
        if today_str in basename:
            continue
        try:
            with open(pkl_file, 'rb') as f:
                prev_data = pickle.load(f)
            cache_date_str = basename.replace('fnguide_', '').replace('.pkl', '')
            cache_date = datetime.strptime(cache_date_str, '%Y-%m-%d')
            cache_age = (datetime.now() - cache_date).days
            print(f"  이전 캐시 로드: {basename} ({len(prev_data)}개 종목, {cache_age}일 전)")
            return prev_data, cache_age
        except Exception:
            continue
    return {}, 999


def collect_fnguide_data(full_refresh=False):
    """FnGuide 재무데이터 증분 수집 → 캐시 저장"""
    print("=" * 60)
    print("FnGuide 재무데이터 공유 수집기")
    print(f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'전체 재수집' if full_refresh else '증분 수집'}")
    print("=" * 60)

    start_time = time.time()

    # 1. KRX 종목 마스터
    print("\n[1/4] KRX 종목 마스터 수집...")
    master = get_stock_master()

    # 2. 필터링
    print("\n[2/4] 종목 필터링...")
    filtered = master[
        (master['시가총액'] >= MIN_MARKET_CAP) &
        (master['is_common'] == True) &
        (master['is_spac'] == False) &
        (master['is_reit'] == False)
    ].copy()
    print(f"  대상 종목: {len(filtered)}개 (시총 {MIN_MARKET_CAP}억+, 보통주, 스팩/리츠 제외)")

    codes = filtered['종목코드'].tolist()
    results = {}
    reused = 0

    # 3. 증분 수집: 이전 캐시에서 재사용 가능한 종목 분리
    print("\n[3/4] 캐시 확인...")
    codes_to_fetch = codes

    if not full_refresh:
        prev_cache, cache_age = _load_prev_cache()
        if prev_cache and cache_age <= CACHE_REFRESH_DAYS:
            codes_to_fetch = []
            for code in codes:
                if code in prev_cache:
                    results[code] = prev_cache[code]
                    reused += 1
                else:
                    codes_to_fetch.append(code)
            print(f"  캐시 재사용: {reused}개, 신규 수집 필요: {len(codes_to_fetch)}개")
        else:
            print(f"  캐시 없음 또는 {CACHE_REFRESH_DAYS}일 초과 → 전체 수집")

    # 4. FnGuide 재무데이터 병렬 수집 (신규/갱신 대상만)
    print(f"\n[4/4] FnGuide 재무데이터 수집 ({len(codes_to_fetch)}개 종목, {FNGUIDE_MAX_WORKERS}스레드)...")

    success = 0
    failed = 0

    if codes_to_fetch:
        def _fetch_one(code):
            return code, get_financial_data(code)

        with ThreadPoolExecutor(max_workers=FNGUIDE_MAX_WORKERS) as executor:
            futures = {executor.submit(_fetch_one, code): code for code in codes_to_fetch}

            for future in as_completed(futures):
                try:
                    code, data = future.result()
                    if data:
                        results[code] = data
                        success += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

                done = success + failed
                if done % 100 == 0 or done == len(codes_to_fetch):
                    elapsed = time.time() - start_time
                    print(f"  진행: {done}/{len(codes_to_fetch)} (성공: {success}, 실패: {failed}, {elapsed:.0f}초)")
    else:
        print("  신규 수집 대상 없음 — 캐시 전체 재사용")

    print(f"\n수집 완료: 재사용 {reused}개 + 신규 {success}개 성공, {failed}개 실패 (총 {len(results)}개)")

    # 캐시 저장
    cache_file = get_cache_filepath()
    save_fnguide_cache(results, cache_file)

    # 이전 캐시 정리
    cleanup_old_caches()

    elapsed = time.time() - start_time
    print(f"\n총 실행 시간: {elapsed:.1f}초 ({elapsed/60:.1f}분)")
    print("=" * 60)

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FnGuide 재무데이터 수집기')
    parser.add_argument('--full', action='store_true', help='전체 재수집 (캐시 무시)')
    args = parser.parse_args()
    collect_fnguide_data(full_refresh=args.full)
