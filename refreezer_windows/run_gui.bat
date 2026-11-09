@echo off
rem Double-click to open ReFreezer for Windows.
cd /d "%~dp0"
start "" pythonw -m rfw || python -m rfw
