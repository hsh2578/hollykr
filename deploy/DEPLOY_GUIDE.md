# HollyKR 구글 클라우드 배포 가이드

## 1. 서버 접속
Google Cloud Console > Compute Engine > VM > SSH 버튼 클릭

## 2. 코드 업로드
방법 A: git (추천)
```bash
cd ~
git clone [repo_url] hollykr
cd hollykr
```

방법 B: 직접 업로드
SSH 창 우상단 기어 > "파일 업로드"로 프로젝트 zip 업로드 후:
```bash
cd ~
unzip hollykr.zip -d hollykr
cd hollykr
```

## 3. 세팅 실행
```bash
bash deploy/setup.sh
```

## 4. .env 파일 생성
```bash
cat > ~/hollykr/.env << 'EOF'
TELEGRAM_BOT_TOKEN=8247602973:AAFkBfTqANPH63zaCEgX3ViTjoTiAacbRZU
TELEGRAM_CHAT_ID=8060934494
EOF
```

## 5. 수동 테스트
```bash
cd ~/hollykr
source venv/bin/activate
python -m scripts.screeners.holly_kr.run --proven --entry close --telegram
```
텔레그램에 시그널이 오면 성공!

## 6. 자동 실행 확인
```bash
# crontab 확인 (매일 15:15 월~금)
crontab -l

# 로그 확인
tail -f ~/hollykr/hollykr.log
```

## 7. 서버 시간대 확인
```bash
# KST(한국시간)인지 확인
date
timedatectl

# KST가 아니면 변경
sudo timedatectl set-timezone Asia/Seoul
```

## 실행 스케줄
- 매일 15:15 (월~금) 자동 실행
- 종가매매 모드 (당일 종가 기준 시그널)
- 검증된 9개 전략 (강력 3 + 관심 6)
- 텔레그램으로 시그널 전송
