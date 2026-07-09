@echo off
chcp 65001 >nul
title Ngrok Tunnel - Smart Farm Web App
setlocal

echo ============================================================
echo   ngrok 터널 시작 스크립트 (모바일 데이터로 외부 접속)
echo ============================================================
echo.

where ngrok >nul 2>nul
if errorlevel 1 (
    echo [오류] ngrok 이 설치되어 있지 않습니다.
    echo.
    echo 아래 방법으로 설치하세요:
    echo   1^) https://ngrok.com/download 에서 Windows용 ngrok.zip 다운로드
    echo   2^) 압축을 풀고 ngrok.exe 를 이 폴더 또는 PATH 에 위치
    echo   3^) https://dashboard.ngrok.com/get-started/your-authtoken 에서
    echo      인증토큰 발급 후 아래 명령 실행:
    echo        ngrok config add-authtoken ^<발급받은토큰^>
    echo.
    echo ngrok 없이도 사용하려면 README.md 의 "포트포워딩" 안내를 참고하세요.
    pause
    exit /b 1
)

echo Flask 서버(포트 5000)가 먼저 실행 중이어야 합니다.
echo start_server.bat 을 별도 창에서 먼저 실행해 두세요.
echo.
echo ngrok 터널을 시작합니다... (종료하려면 이 창에서 Ctrl+C)
echo 실행 후 표시되는 "Forwarding" 줄의 https://xxxx.ngrok-free.dev 주소가
echo 모바일 데이터(LTE/5G)에서 접속 가능한 공개 URL 입니다.
echo ------------------------------------------------------------
echo.

ngrok http 5000

pause
