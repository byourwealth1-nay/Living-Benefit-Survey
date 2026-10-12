#!/bin/zsh
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo 'ไม่พบ Python 3 กรุณาติดตั้ง Python 3.10 ขึ้นไป'
  read '?กด Enter เพื่อปิด...'
  exit 1
fi
if [ ! -f data/living_benefits.sqlite3 ]; then
  echo 'ครั้งแรก: กรุณาตั้งค่าบัญชีผู้ดูแลระบบ'
  python3 server.py setup || exit 1
fi
python3 server.py
read '?กด Enter เพื่อปิด...'
