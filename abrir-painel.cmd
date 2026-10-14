@echo off
rem Dois cliques para abrir o painel. Feche esta janela para encerrar.
cd /d "%~dp0"
title Sala de escuta
python -m spotify_assistant ui
if errorlevel 1 pause
