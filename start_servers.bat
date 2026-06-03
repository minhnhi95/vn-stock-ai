@echo off
title AI Stock Analyzer & Trading Dashboard - Startup Script
echo ==========================================================
echo    KHOI DONG HE THONG PHAN TICH CHUNG KHOAN AI (LOCAL)
echo ==========================================================
echo.

:: Configure environment variables to fix Windows Unicode path bugs for Python/libcurl
set CURL_CA_BUNDLE=C:\Users\minhn\cacert.pem
set REQUESTS_CA_BUNDLE=C:\Users\minhn\cacert.pem
set SSL_CERT_FILE=C:\Users\minhn\cacert.pem
set PYTHONUTF8=1

:: Launch FastAPI Backend
echo [1/2] Dang khoi dong Backend FastAPI...
start cmd /k "title FastAPI Backend && echo [API SERVER] Dang chay tren cong 8000... && cd backend && ..\.venv\Scripts\uvicorn main:app --reload --port 8000"

:: Launch Vite React Frontend
echo [2/2] Dang khoi dong Frontend React + Vite...
start cmd /k "title Vite Frontend && echo [VITE SERVER] Dang khoi dong dev server... && cd frontend && npm run dev"

echo.
echo ==========================================================
echo    KHOI DONG HOAN TAT!
echo    - API Backend: http://127.0.0.1:8000/docs
echo    - Giao dien Web: http://localhost:5180
echo ==========================================================
echo.
pause
