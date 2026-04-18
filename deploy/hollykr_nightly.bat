@echo off
cd /d "C:\Users\hsh\Desktop\vibecoding\주식 관련 프로젝트"
python -m scripts.screeners.holly_kr.run --nightly --entry close --csv >> hollykr_nightly.log 2>&1
