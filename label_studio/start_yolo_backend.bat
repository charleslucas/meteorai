@echo off
cd /d C:\Users\charl\meteorai
call .venv\Scripts\activate
set LABEL_STUDIO_URL=http://localhost:8081
set PYTHONUNBUFFERED=1
python label_studio\yolo_backend.py --port 9091
