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

:: Ba che do:
::   (khong tham so)  chi nghe tren may nay - an toan o moi mang.
::   lan              mo cho MOI thiet bi cung mang, ke ca danh muc that cua ban.
::                    Chi dung o Wi-Fi nha hoac hotspot cua chinh ban.
::   tailscale        chi nghe tren dia chi Tailscale: dung duoc o bat ky mang nao,
::                    nhung chi thiet bi dang nhap Tailscale cua ban vao duoc.
::                    Day la che do dung khi ra ngoai.
set MODE=%~1
set HOST_ARGS=
if /i "%MODE%"=="lan" set HOST_ARGS=--host 0.0.0.0
if /i not "%MODE%"=="tailscale" goto :start
set TS_IP=
for /f %%i in ('tailscale ip -4 2^>nul') do set TS_IP=%%i
if not defined TS_IP (
    echo [LOI] Tailscale chua ket noi tren may nay. Mo app Tailscale, dang nhap, roi chay lai.
    echo       Khong tu chuyen sang che do lan: o Wi-Fi cong cong, lam vay la lo danh muc that.
    pause
    exit /b 1
)
set HOST_ARGS=--host %TS_IP%

:start
:: Launch FastAPI Backend
echo [1/2] Dang khoi dong Backend FastAPI (cong 8765)...
start cmd /k "title FastAPI Backend && echo [API SERVER] Dang chay tren cong 8765... && cd backend && ..\.venv\Scripts\uvicorn main:app --reload --port 8765 %HOST_ARGS%"

:: Launch Vite React Frontend
echo [2/2] Dang khoi dong Frontend React + Vite (cong 5273)...
start cmd /k "title Vite Frontend && echo [VITE SERVER] Dang khoi dong dev server... && cd frontend && npm run dev -- %HOST_ARGS%"

echo.
echo ==========================================================
echo    KHOI DONG HOAN TAT!
if /i "%MODE%"=="tailscale" goto :info_tailscale
echo    - API Backend:   http://127.0.0.1:8765/docs
echo    - Healthcheck:   http://127.0.0.1:8765/api/health
echo    - Giao dien Web: http://localhost:5273
if /i "%MODE%"=="lan" (
    echo.
    echo    CHE DO LAN - mo tren dien thoai cung mang:
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do for /f "tokens=*" %%b in ("%%a") do echo      http://%%b:5273
    echo    Ai cung mang cung mo duoc app - chi dung o Wi-Fi nha / hotspot cua ban.
)
goto :end

:info_tailscale
echo    CHE DO TAILSCALE - mo o bat ky mang nao, tren may nay lan dien thoai:
echo      http://%TS_IP%:5273
echo    Dien thoai phai BAT app Tailscale. Tren may nay localhost khong dung duoc.

:end
echo ==========================================================
echo.
pause
