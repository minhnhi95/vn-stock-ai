@echo off
REM ===================================================================
REM  Sinh ban tin chung khoan buoi sang.
REM
REM  Dat lich chay tu dong (Task Scheduler):
REM    1. Mo "Task Scheduler" -> Create Basic Task
REM    2. Trigger: Daily, 06:30
REM    3. Action: Start a program -> tro toi file .bat nay
REM    4. Trong tab Conditions, BO chon "Start the task only if the
REM       computer is on AC power" neu dung laptop.
REM
REM  Yeu cau: da dang nhap Antigravity CLI (mo app Antigravity mot lan).
REM  Job mat khoang 1-2 phut va ghi ket qua vao DB; app web chi doc lai.
REM ===================================================================

cd /d "%~dp0backend"

REM Duong dan du an co dau tieng Viet lam libcurl khong nap duoc CA bundle.
REM ssl_bootstrap.py da tu xu ly, nhung dat san day cho chac.
set PYTHONUTF8=1

echo [%date% %time%] Bat dau sinh ban tin...
if /i "%~1"=="auto" (
    REM Chay theo lich: khong ai ngoi xem man hinh, nen ghi het ra file log.
    if not exist "logs" mkdir "logs"
    echo [%date% %time%] Bat dau >> "logs\daily_brief.log"
    "..\.venv\Scripts\python.exe" -X utf8 -m jobs.daily_brief >> "logs\daily_brief.log" 2>&1
) else (
    "..\.venv\Scripts\python.exe" -X utf8 -m jobs.daily_brief
)

if errorlevel 1 (
    echo [%date% %time%] THAT BAI - xem thong bao loi ben tren.
    REM Chay tay thi dung man hinh de con doc duoc loi. Task Scheduler PHAI
    REM truyen tham so "auto" - khong thi pause treo vinh vien trong mot cua so
    REM cmd an, va lan chay tuan sau se bi bo qua vi task truoc chua ket thuc.
    if "%~1"=="" pause
    exit /b 1
)

echo [%date% %time%] Xong.
exit /b 0
