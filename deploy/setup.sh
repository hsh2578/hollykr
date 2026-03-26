#!/bin/bash
# HollyKR 서버 초기 세팅 스크립트
# 사용법: bash setup.sh

set -e

echo "=== 1. 시스템 업데이트 ==="
sudo apt update && sudo apt upgrade -y

echo "=== 2. Python 3.11+ 설치 ==="
sudo apt install -y python3 python3-pip python3-venv git

echo "=== 3. 프로젝트 디렉토리 생성 ==="
mkdir -p ~/hollykr/.cache/ohlcv
mkdir -p ~/hollykr/.cache/investor
mkdir -p ~/hollykr/data/holly_kr
cd ~/hollykr

echo "=== 4. 가상환경 생성 ==="
python3 -m venv venv
source venv/bin/activate

echo "=== 5. 패키지 설치 ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 6. crontab 등록 (매일 15:15 KST) ==="
# 기존 hollykr 관련 cron 삭제 후 재등록
crontab -l 2>/dev/null | grep -v "hollykr" > /tmp/crontab_tmp || true
echo "40 14 * * 1-5 cd /home/\$(whoami)/hollykr && /home/\$(whoami)/hollykr/venv/bin/python -m scripts.screeners.holly_kr.run --proven --entry close --telegram >> /home/\$(whoami)/hollykr/hollykr.log 2>&1" >> /tmp/crontab_tmp
crontab /tmp/crontab_tmp
rm /tmp/crontab_tmp

echo ""
echo "=== 세팅 완료! ==="
echo ""
echo "다음 단계:"
echo "1. .env 파일을 ~/hollykr/.env 에 생성하세요"
echo "   TELEGRAM_BOT_TOKEN=8247602973:AAFkBfTqANPH63zaCEgX3ViTjoTiAacbRZU"
echo "   TELEGRAM_CHAT_ID=8060934494"
echo "2. 수동 테스트: cd ~/hollykr && source venv/bin/activate && python -m scripts.screeners.holly_kr.run --proven --entry close --telegram"
echo "3. crontab -l 로 스케줄 확인"
echo "4. 로그 확인: tail -f ~/hollykr/hollykr.log"
