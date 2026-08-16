@echo off
chcp 65001 >nul
title Discord Vending Bot
cd /d "%~dp0"

if not exist ".env" (
  echo [ERROR] .env がありません。
  echo .env.example をコピーして .env を作り、各キーを設定してください。
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo 初回セットアップ: npm install
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install に失敗しました。
    pause
    exit /b 1
  )
)

echo Botを起動します...
call npm start
pause
