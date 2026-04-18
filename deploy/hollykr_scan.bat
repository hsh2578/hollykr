@echo off
cd /d "C:\Users\hsh\Desktop\vibecoding\주식 관련 프로젝트"
python -m scripts.screeners.holly_kr.run --auto --entry close --telegram >> hollykr.log 2>&1
