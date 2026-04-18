# CLAUDE.md

## Project Overview

HollyKR - Trade Ideas Holly AI의 한국 시장 적응 버전.
32개 전략, ATR 기반 백테스트, 매일 자동 텔레그램 시그널 전송.
사용자가 시그널 보고 직접 매수/매도 판단 (자동매매 아님).

## How to Run

```bash
pip install -r requirements.txt

# 실전 모드 (검증된 10개 전략, 종가매매, 텔레그램)
python -m scripts.screeners.holly_kr.run --proven --entry close --telegram

# 야간 전략 선정 (18:00 실행, 내일 쓸 전략 자동 선별)
python -m scripts.screeners.holly_kr.run --nightly --entry close --csv

# 자동 모드 (야간 선정 결과 사용, 14:40 실행)
python -m scripts.screeners.holly_kr.run --auto --entry close --telegram

# 전체 32개 전략 스캔
python -m scripts.screeners.holly_kr.run --entry close --telegram

# 백테스트
python -m scripts.screeners.holly_kr.backtest --days 200 --sample 200 --entry close --csv

# 데이터 수집
python collect_data.py             # 증분 수집
python -m scripts.investor_data    # 수급 데이터 테스트
python -m scripts.telegram_alert   # 텔레그램 테스트
```

## Architecture

```
config.py                     # 공통 설정 (경로, 네트워크, FnGuide, 수급)
collect_data.py               # 전종목 재무데이터 배치 수집기 (증분 수집)
scripts/
  krx_data.py                 # [공통] KRX 종목 마스터 (캐시)
  fnguide_data.py             # [공통] FnGuide 재무제표
  ohlcv_data.py               # [공통] OHLCV (증분 캐시, 영구 파일)
  investor_data.py            # [공통] 외국인/기관 수급 (네이버 금융)
  telegram_alert.py           # [공통] 텔레그램 알림 (강력/관심 2단계)
  utils/indicators.py         # [공통] 기술적 지표
  screeners/
    holly_kr/                 # HollyKR 스크리너
      config.py               # 유니버스/비용/포지션 설정
      run.py                  # CLI (--proven/--auto/--nightly)
      scanner.py              # 오케스트레이터 (전략 순회 + 수급 + 레짐)
      backtest.py             # 백테스트 엔진 (OOS, 슬리피지, 거래비용)
      signal_model.py         # Signal 데이터 클래스
      indicators.py           # RS Rating, 캔들 패턴, RSI
      universe.py             # 유니버스 필터 (시총 1000억+)
      output.py               # 터미널 + CSV/JSON
      confidence.py           # 종합 신뢰도 (수급+레짐+시장필터)
      exit_manager.py         # 통일 청산 규칙
      nightly_selector.py     # 야간 전략 선정 (PF 1.05+ AND 총수익 10%+)
      active_strategies.py    # 야간 선정 결과 저장/로드
      strategies/             # 32개 전략
        base.py               # BaseStrategy (ATR 목표/손절 헬퍼)
        # Phase 1 EOD 12개
        pushing_the_spring.py, engulfing.py, yesterday_hammer.py,
        snap_back_long.py, horseshoe_up.py, volume_doesnt_lie.py,
        minervini_trend.py, darvas_box.py, weinstein_stage.py,
        livermore_pivot.py, magic_formula.py, piotroski_fscore.py
        # Phase 2 HYBRID 20개
        bullish_trend_change.py, float_on.py, wake_up_call.py,
        staggering_volume.py, close_to_a_cross.py, alpha_predators.py,
        bullish_pullback.py, strong_stock_pulling_back.py,
        quarterback.py, tailwind.py, trend_play.py, the_continuation.py,
        got_dough.py, guiding_hand.py, nice_chart.py, the_vault.py,
        pulling_the_arrow.py, balloon_under_water.py,
        neo_breakout.py, neo_pullback.py
      filters/
        theme_filter.py       # 테마주/작전주 제외
        market_filter.py      # 시장 레짐 판별 (상승/횡보/하락)
        dedup.py              # 중복 시그널 (단계별 부스트)
    pairs_trading/            # 페어 트레이딩 스크리너 (별도)
deploy/
  hollykr_scan.bat            # 14:40 스캔 (Windows 스케줄러)
  hollykr_nightly.bat         # 18:00 야간 선정
  setup.sh                    # 서버 세팅 스크립트
```

## 실전 전략 (백테스트 검증, ATR 기반, 종가매매)

강력 (PF 1.2+):
- close_to_a_cross: 골든크로스 + 거래량 2배 + 당일 2%+ 상승
- weinstein_stage: Stage 1->2 전환 + 거래량 폭발 (추세추종, 목표 없음)
- tailwind: 이평 정배열 + MA20 터치 반등
- wake_up_call: 20일 신고가 + 이평 정배열

관심 (PF 1.05~1.2):
- darvas_box, volume_doesnt_lie, staggering_volume,
  quarterback, trend_play, nice_chart

## 핵심 설정

- 유니버스: 시총 1,000억+, 보통주, 스팩/리츠 제외
- 거래비용: 0.21% (매수 0.015% + 매도 0.015% + 세금 0.18%)
- 슬리피지: 대형주 0.1%, 중형주 0.2%, 소형주 0.5%
- ATR 목표/손절: 목표 ATR x 3, 손절 ATR x 2 (종목별 동적)
- 신뢰도: base x 수급(1.1) x 레짐 x 다중부스트(1.1~1.25), 상한 0.95
- 야간 선정: PF 1.05+ AND 총수익 10%+ (60일 룩백)
- 시그널 캡: 강력 10개 + 관심 15개

## 텔레그램

- 봇: @hollykr_sig_bot (토큰: 8247602973)
- Chat ID: 8060934494
- 포맷: 강력/관심 2단계, ATR 목표/손절, 수급등급, 전략중복수

## 스케줄 (Windows 작업 스케줄러)

- 14:40 (월~금): --auto --entry close --telegram
- 18:00 (월~금): --nightly --entry close --csv
- PC 켜져 있어야 작동

## Known Limitations

- FDR: Yahoo Finance 기반, 장중 실시간 안 됨
- 수급: 네이버 금융 스크래핑, HTML 변경 시 파싱 수정 필요
- Phase 3 INTRADAY 12개: 분봉 필요, 미구현
- Magic Formula/Piotroski: 스캐너 미연동 (별도 분기 리밸런싱 필요)
