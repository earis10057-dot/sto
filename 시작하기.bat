@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem 처음 실행이면 필요한 프로그램을 자동으로 설치합니다.
if not exist ".venv\Scripts\pythonw.exe" (
    echo ============================================
    echo  처음 실행: 필요한 프로그램을 설치합니다 ^(1~3분^)
    echo ============================================
    where py > nul 2>&1 && (py -3 -m venv .venv) || (python -m venv .venv)
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [오류] 파이썬을 찾지 못했습니다.
        echo https://www.python.org/downloads/ 에서 설치하고
        echo 설치 첫 화면의 "Add python.exe to PATH" 를 꼭 체크하세요.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip > nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [오류] 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 실행하세요.
        rmdir /s /q .venv
        pause
        exit /b 1
    )
)

if not exist ".env" copy ".env.example" ".env" > nul
start "" ".venv\Scripts\pythonw.exe" -m blogauto.gui
