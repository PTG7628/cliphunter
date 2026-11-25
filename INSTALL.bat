@echo off
title ClipHunter installer
echo ============================================
echo   ClipHunter - one-time setup
echo ============================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed.
  echo Install it from https://www.python.org/downloads/  and TICK "Add Python to PATH".
  echo Then run INSTALL.bat again.
  pause
  exit /b
)
python --version
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo Installing ffmpeg...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
)
echo.
echo Installing Python packages (a few minutes)...
python -m pip install --upgrade pip
python -m pip install flask numpy streamlink yt-dlp chat-downloader
if errorlevel 1 echo [!] Main packages failed - screenshot this window and send it to Claude.
echo.
echo Installing webcam detection (optional)...
python -m pip install opencv-python
if errorlevel 1 echo [!] Webcam detection failed to install. You can set the webcam area by hand in the editor.
echo.
echo Installing PC speech-to-text (optional; Groq cloud transcription works without it)...
python -m pip install faster-whisper
if errorlevel 1 echo [!] PC speech-to-text not available on this Python. Use Groq cloud transcription in Settings.
echo.
echo ============================================
echo   Done! Close this window, then double-click START.bat
echo   (If ffmpeg was just installed, restart your PC once.)
echo ============================================
pause
