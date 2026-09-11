@echo off
REM ===================================================================
REM  Tu quet ket luan "Co the can nhac mua / Cho them / Khong nen mua"
REM  cho toan thi truong: loc thanh khoan ca san truoc, roi cham tung ma
REM  (VN100 + ma dang giu + ma dat canh bao luon duoc cham).
REM
REM  Ket qua ghi vao DB (bang verdict_scan), hien o panel "Ket luan ca ro"
REM  va dung cho canh bao "Ket luan: Co the can nhac mua".
REM
REM  Da dat lich tu dong trong Task Scheduler: "VN Stock - Quet ket luan",
REM  15:30 thu 2 den thu 6 (sau gio dong cua, dung gia dong cua phien do).
REM
REM  Mat khoang 40 phut: vnstock free tier chi cho 20 request/phut nen
REM  moi ma cach nhau 9 giay. Luot quet hong (mat mang, qua nua so ma
REM  loi) se KHONG ghi de luot quet cu.
REM ===================================================================

cd /d "%~dp0backend"

set PYTHONUTF8=1
set PYTHONUNBUFFERED=1

echo [%date% %time%] Bat dau quet ket luan ca ro...
if /i "%~1"=="auto" (
    REM Chay theo lich: khong ai ngoi xem man hinh, nen ghi het ra file log.
    if not exist "logs" mkdir "logs"
    echo [%date% %time%] Bat dau >> "logs\verdict_scan.log"
    "..\.venv\Scripts\python.exe" -X utf8 -m jobs.verdict_scan >> "logs\verdict_scan.log" 2>&1
) else (
    "..\.venv\Scripts\python.exe" -X utf8 -m jobs.verdict_scan
)

if errorlevel 1 (
    echo [%date% %time%] THAT BAI - luot quet cu duoc giu nguyen.
    REM Chay tay thi dung man hinh de con doc duoc loi. Task Scheduler PHAI
    REM truyen tham so "auto" - khong thi pause treo vinh vien trong mot cua so
    REM cmd an, va lan chay sau se bi bo qua vi task truoc chua ket thuc.
    if "%~1"=="" pause
    exit /b 1
)

echo [%date% %time%] Xong.
exit /b 0
