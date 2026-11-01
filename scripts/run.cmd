@echo off
rem Runs the hunter for one candidate forever. Log: data\<name>.log (rotated at 5 MB); anything printed
rem outside the log, such as a crash, goes to data\<name>.out.log. Usage: scripts\run.cmd alex
rem Uses the project's own virtualenv (.venv) when there is one, else the python on the PATH.
cd /d "%~dp0.."
if not exist data mkdir data
set PYTHONUTF8=1
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
"%PY%" -m hunter --who %1 --log "data\%1.log" loop --every 60 >> "data\%1.out.log" 2>&1
