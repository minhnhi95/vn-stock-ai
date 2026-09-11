@echo off
title AI Stock Analyzer ^& Trading Dashboard - Startup Script
echo ==========================================================
echo    KHOI DONG HE THONG PHAN TICH CHUNG KHOAN AI (LOCAL)
echo ==========================================================
echo.

:: Configure environment variables to fix Windows Unicode path bugs for Python/libcurl
set CURL_CA_BUNDLE=C:\Users\minhn\cacert.pem
set REQUESTS_CA_BUNDLE=C:\Users\minhn\cacert.pem
set SSL_CERT_FILE=C:\Users\minhn\cacert.pem
set PYTHONUTF8=1

:: Cong phai khop voi:
::   - resolveApiBase() trong frontend/src/App.jsx  -> 8765
::   - server.port trong frontend/vite.config.js     -> 5273
:: Doi cong o day ma khong doi 2 cho tren = frontend goi vao khoang khong.

:: Mac dinh chi nghe tren may nay. "start_servers.bat lan" mo cho MOI thiet bi
:: cung mang de xem tren dien thoai - ke ca danh muc that cua ban - nen chi dung
:: o Wi-Fi nha hoac hotspot cua chinh ban, khong dung o Wi-Fi cong cong.
set HOST_ARGS=
if /i "%~1"=="lan" set HOST_ARGS=--host 0.0.0.0

:: Launch FastAPI Backend
echo [1/2] Dang khoi dong Backend FastAPI (cong 8765)...
start cmd /k "title FastAPI Backend && echo [API SERVER] Dang chay tren cong 8765... && cd backend && ..\.venv\Scripts\uvicorn main:app --reload --port 8765 %HOST_ARGS%"

:: Launch Vite React Frontend
echo [2/2] Dang khoi dong Frontend React + Vite (cong 5273)...
start cmd /k "title Vite Frontend && echo [VITE SERVER] Dang khoi dong dev server... && cd frontend && npm run dev -- %HOST_ARGS%"

echo.
echo ==========================================================
echo    KHOI DONG HOAN TAT!
echo    - API Backend:   http://127.0.0.1:8765/docs
echo    - Healthcheck:   http://127.0.0.1:8765/api/health
echo    - Giao dien Web: http://localhost:5273
if /i "%~1"=="lan" (
    echo.
    echo    CHE DO LAN - mo tren dien thoai cung mang:
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do for /f "tokens=*" %%b in ("%%a") do echo      http://%%b:5273
    echo    Ai cung mang cung mo duoc app - chi dung o Wi-Fi nha / hotspot cua ban.
)
echo ==========================================================
echo.
pause
