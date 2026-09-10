@echo off
REM ===================================================================
REM  Tinh lai trung vi chi so co ban theo nganh (P/E, P/B, ROE... ).
REM
REM  Ket qua ghi vao backend\data\sector_benchmarks.json, dung cho phan
REM  "Co ban doanh nghiep" de so mot ma voi cac doanh nghiep cung nganh.
REM
REM  Chi so co ban chi doi moi quy nen KHONG can chay hang ngay.
REM  Dat lich chay tu dong (Task Scheduler):
REM    1. Mo "Task Scheduler" -> Create Basic Task
REM    2. Trigger: Weekly, Chu nhat 07:00
REM    3. Action: Start a program -> tro toi file .bat nay
REM
REM  Mat khoang 16 phut: vnstock free tier chi cho 20 request/phut nen
REM  job co nghi 4 giay giua moi ma. Khong tat may giua chung.
REM  Quet hong (mat mang) se KHONG ghi de bang cu.
REM ===================================================================

cd /d "%~dp0backend"

set PYTHONUTF8=1
set PYTHONUNBUFFERED=1

echo [%date% %time%] Bat dau quet chi so co ban theo nganh...
"..\.venv\Scripts\python.exe" -X utf8 -m jobs.sector_benchmarks

if errorlevel 1 (
    echo [%date% %time%] THAT BAI - bang cu duoc giu nguyen.
    REM Chay tay thi dung man hinh de con doc duoc loi. Task Scheduler PHAI
    REM truyen tham so "auto" - khong thi pause treo vinh vien trong mot cua so
    REM cmd an, va lan chay tuan sau se bi bo qua vi task truoc chua ket thuc.
    if "%~1"=="" pause
    exit /b 1
)

echo [%date% %time%] Xong.
exit /b 0
