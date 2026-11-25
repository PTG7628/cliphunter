@echo off
title ClipHunter (keep this window open)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed or not on PATH.
  echo Install it from https://www.python.org/downloads/ and TICK "Add Python to PATH".
  pause
  exit /b
)

rem --- install anything missing (first run, or if a package failed before)
python -c "import flask, numpy, streamlink, yt_dlp" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages, please wait...
  python -m pip install --upgrade pip
  python -m pip install flask numpy streamlink yt-dlp chat-downloader
)
python -c "import cv2" >nul 2>nul
if errorlevel 1 (
  echo Installing webcam detection (optional)...
  python -m pip install opencv-python
  if errorlevel 1 echo [!] Webcam detection not available. You can still set the webcam area by hand in the editor.
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo Installing ffmpeg...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  echo.
  echo ffmpeg installed. CLOSE this window and open START.bat again.
  pause
  exit /b
)

python app.py
echo.
echo ClipHunter stopped. If you see an error above, screenshot it and send it to Claude.
pause
