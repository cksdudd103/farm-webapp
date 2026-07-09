@echo off
chcp 65001 >nul
title Smart Farm Web App Server
setlocal enabledelayedexpansion

echo ============================================================
echo   스마트 영농관리 웹앱 서버 시작 스크립트
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/3] 필요한 패키지를 설치합니다 (requirements.txt)...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [오류] 패키지 설치에 실패했습니다. Python 및 pip 설치 상태를 확인하세요.
    pause
    exit /b 1
)

echo.
echo [2/3] 이 PC의 IP 주소를 확인합니다...
echo ------------------------------------------------------------
echo   같은 Wi-Fi(공유기)에 연결된 스마트폰에서 아래 IP로 접속하세요.
echo   예) http://192.168.0.10:5000
echo ------------------------------------------------------------
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /i "IPv4"') do (
    set ip=%%A
    set ip=!ip: =!
    echo   로컬 IP 주소  : !ip!
)
echo.
echo   포트          : 5000
echo   공인(외부) IP 확인: https://www.myip.com 또는 아래 명령 참고
echo     PowerShell: (Invoke-WebRequest -uri "https://api.ipify.org").Content
echo ------------------------------------------------------------
echo.
echo   [모바일 데이터(LTE/5G)로 접속하려면]
echo   - ngrok 사용: start_ngrok.bat 실행 후 표시되는 https 주소로 접속
echo   - 또는 공유기 포트포워딩 설정 후 "공인 IP:5000"으로 접속
echo   자세한 방법은 README.md 를 참고하세요.
echo ------------------------------------------------------------
echo.

echo [3/3] Flask 서버를 0.0.0.0:5000 으로 시작합니다...
echo ------------------------------------------------------------
python app.py

pause
