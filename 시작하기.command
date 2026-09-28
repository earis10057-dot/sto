#!/bin/bash
# 맥: 이 파일을 더블클릭하면 프로그램이 열립니다. (처음 한 번은 우클릭 → 열기)
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "처음 실행: 필요한 프로그램을 설치합니다 (1~3분)"
    if ! command -v python3 >/dev/null; then
        echo "[오류] 파이썬을 찾지 못했습니다. https://www.python.org/downloads/ 에서 설치하세요."
        read -r -p "엔터를 누르면 닫힙니다."
        exit 1
    fi
    python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt || {
        echo "[오류] 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 실행하세요."
        rm -rf .venv
        read -r -p "엔터를 누르면 닫힙니다."
        exit 1
    }
fi

[ -f .env ] || cp .env.example .env
.venv/bin/python -m blogauto.gui
