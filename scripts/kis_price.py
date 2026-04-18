"""
KIS 실시간 현재가 조회 (inquire-price).

주말/장외엔 최근 종가, 장중엔 현재가를 반환.
"""

from typing import Optional

import requests

from scripts.investor_data import (
    _get_kis_token, _limiter, KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL
)


def get_current_price(ticker: str) -> Optional[float]:
    """KIS inquire-price로 현재가(stck_prpr) 조회."""
    token = _get_kis_token()
    if not token:
        return None

    code6 = str(ticker).zfill(6)
    url = f'{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price'
    headers = {
        'authorization': f'Bearer {token}',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
        'tr_id': 'FHKST01010100',
        'custtype': 'P',
    }
    params = {
        'FID_COND_MRKT_DIV_CODE': 'J',
        'FID_INPUT_ISCD': code6,
    }

    try:
        _limiter.wait()
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get('rt_cd') != '0':
            return None
        price = data.get('output', {}).get('stck_prpr', '').strip()
        return float(price) if price else None
    except Exception:
        return None


if __name__ == '__main__':
    for code, name in [('005930', '삼성전자'), ('000660', 'SK하이닉스')]:
        p = get_current_price(code)
        print(f'{name}({code}): {p:,.0f}원' if p else f'{name}: 실패')
