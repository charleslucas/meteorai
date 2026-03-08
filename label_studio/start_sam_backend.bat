@echo off
cd /d C:\cygwin64\home\charl\meteorai
set LABEL_STUDIO_URL=http://localhost:8080
set PYTHONUNBUFFERED=1
python label_studio\sam_backend.py --port 9090
