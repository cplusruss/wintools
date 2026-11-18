@echo off
cd /d "%~dp0"
start "" pythonw "wintools.py" %*
exit