"""
페어 트레이딩 결과 시각화

사용법:
    python -m scripts.screeners.pairs_trading.visualize
    python -m scripts.screeners.pairs_trading.visualize --file data/pairs/pairs_2026-03-20.json
"""

import argparse
import glob
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager, rc

from scripts.ohlcv_data import get_ohlcv
from scripts.screeners.pairs_trading.config import OUTPUT_DIR

# 한글 폰트
font_path = 'C:/Windows/Fonts/malgun.ttf'
font_manager.fontManager.addfont(font_path)
rc('font', family='Malgun Gothic')
plt.rcParams['axes.unicode_minus'] = False

SIG_COLORS = {
    'ENTRY_STRONG': '#e74c3c',
    'WATCH': '#f39c12',
    'HOLD': '#3498db',
    'EXIT': '#95a5a6',
    'STOP': '#8e44ad',
}


def visualize(json_path: str = None):
    # 가장 최근 결과 파일 자동 탐색
    if json_path is None:
        files = sorted(glob.glob(str(OUTPUT_DIR / 'pairs_*.json')))
        if not files:
            print("결과 JSON 파일이 없습니다.")
            return
        json_path = files[-1]

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    date = data['date']
    pairs = sorted(data['pairs'], key=lambda p: abs(p['zscore']['main']), reverse=True)

    n = len(pairs)
    if n == 0:
        print("시그널 없음")
        return

    fig, axes = plt.subplots(n, 2, figsize=(18, 4 * n))
    if n == 1:
        axes = axes.reshape(1, -1)
    fig.suptitle(f'페어 트레이딩 — 이탈도(|Z|) 순위  ({date})',
                 fontsize=18, fontweight='bold', y=1.002)

    for idx, p in enumerate(pairs):
        code_a = p['stock_a']['code']
        code_b = p['stock_b']['code']
        name_a = p['stock_a']['name']
        name_b = p['stock_b']['name']
        beta = p['cointegration']['beta']
        signal = p['signal']
        z_main = p['zscore']['main']
        half_life = p['stability']['half_life']
        sig_color = SIG_COLORS.get(signal, '#999')

        ohlcv_a = get_ohlcv(code_a, days=250)
        ohlcv_b = get_ohlcv(code_b, days=250)

        if ohlcv_a is None or ohlcv_b is None:
            axes[idx, 0].text(0.5, 0.5, '데이터 없음', ha='center', va='center')
            axes[idx, 1].text(0.5, 0.5, '데이터 없음', ha='center', va='center')
            continue

        common_idx = ohlcv_a.index.intersection(ohlcv_b.index)
        close_a = ohlcv_a.loc[common_idx, 'Close']
        close_b = ohlcv_b.loc[common_idx, 'Close']
        norm_a = close_a / close_a.iloc[0] * 100
        norm_b = close_b / close_b.iloc[0] * 100

        # 왼쪽: 정규화 가격
        ax_l = axes[idx, 0]
        ax_l.plot(norm_a.index, norm_a.values, color='#e74c3c', linewidth=1.5, label=name_a)
        ax_l.plot(norm_b.index, norm_b.values, color='#3498db', linewidth=1.5, label=name_b)
        ax_l.fill_between(norm_a.index, norm_a.values, norm_b.values, alpha=0.12, color='gray')
        ax_l.legend(fontsize=9, loc='upper left')
        ax_l.grid(True, alpha=0.3)
        ax_l.set_ylabel('정규화 가격')
        ax_l.set_title(f'{name_a} vs {name_b}  [{p["sector"]}]', fontsize=11, fontweight='bold')
        ax_l.text(0.01, 0.97, f'#{idx+1}  {signal}  |Z|={abs(z_main):.2f}',
                  transform=ax_l.transAxes, fontsize=10, va='top', fontweight='bold',
                  color='white', bbox=dict(boxstyle='round,pad=0.3', facecolor=sig_color, alpha=0.85))

        if p['direction'] == 'LONG_A':
            ax_l.text(0.99, 0.97, f'→ {name_a} 매수', transform=ax_l.transAxes,
                      fontsize=9, va='top', ha='right', fontweight='bold', color='#e74c3c',
                      bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffeaea', alpha=0.9))
        elif p['direction'] == 'LONG_B':
            ax_l.text(0.99, 0.97, f'→ {name_b} 매수', transform=ax_l.transAxes,
                      fontsize=9, va='top', ha='right', fontweight='bold', color='#2980b9',
                      bbox=dict(boxstyle='round,pad=0.3', facecolor='#e8f4fd', alpha=0.9))

        # 오른쪽: Z-Score
        log_a = np.log(close_a)
        log_b = np.log(close_b)
        spread = log_a.values - beta * log_b.values
        spread_s = pd.Series(spread, index=common_idx)
        z_60 = (spread_s - spread_s.rolling(60).mean()) / spread_s.rolling(60).std()

        ax_r = axes[idx, 1]
        ax_r.plot(z_60.index, z_60.values, color='#2c3e50', linewidth=1.2)
        z_vals = z_60.values
        ax_r.fill_between(z_60.index, z_vals, 2.0, where=z_vals > 2.0, color='red', alpha=0.25)
        ax_r.fill_between(z_60.index, z_vals, -2.0, where=z_vals < -2.0, color='red', alpha=0.25)
        ax_r.fill_between(z_60.index, z_vals, 1.5,
                          where=(z_vals > 1.5) & (z_vals <= 2.0), color='orange', alpha=0.15)
        ax_r.fill_between(z_60.index, z_vals, -1.5,
                          where=(z_vals < -1.5) & (z_vals >= -2.0), color='orange', alpha=0.15)
        ax_r.axhline(y=2.0, color='red', linestyle='--', alpha=0.6, linewidth=0.8)
        ax_r.axhline(y=-2.0, color='red', linestyle='--', alpha=0.6, linewidth=0.8)
        ax_r.axhline(y=1.5, color='orange', linestyle=':', alpha=0.6, linewidth=0.8)
        ax_r.axhline(y=-1.5, color='orange', linestyle=':', alpha=0.6, linewidth=0.8)
        ax_r.axhline(y=0, color='gray', alpha=0.3, linewidth=0.8)
        ax_r.grid(True, alpha=0.3)
        ax_r.set_title(f'Z-Score (60일)  |  β={beta:.2f}  반감기={half_life:.0f}일',
                       fontsize=11, fontweight='bold')
        ax_r.set_ylabel('Z-Score')

        if len(z_60.dropna()) > 0:
            last_z = z_60.dropna().iloc[-1]
            ax_r.annotate(f'Z={z_main:+.2f}',
                          xy=(z_60.dropna().index[-1], last_z),
                          fontsize=10, fontweight='bold', color=sig_color,
                          xytext=(-70, 15 if last_z > 0 else -25),
                          textcoords='offset points',
                          arrowprops=dict(arrowstyle='->', color=sig_color, lw=1.5))

    plt.tight_layout()
    out_path = OUTPUT_DIR / f'pairs_ranking_{date}.png'
    plt.savefig(out_path, dpi=130, bbox_inches='tight')
    print(f'저장: {out_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=str, default=None, help='결과 JSON 파일 경로')
    args = parser.parse_args()
    visualize(args.file)
