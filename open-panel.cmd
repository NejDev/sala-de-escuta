@echo off
rem Double-click to open the panel. Close this window to stop it.
cd /d "%~dp0"
title Sala de escuta
python -m spotify_assistant ui
if errorlevel 1 pause
