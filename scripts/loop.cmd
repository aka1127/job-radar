@echo off
rem Runs the hunter for one candidate forever (used by the scheduled task). When the engine's code changes, the
rem hunter exits with code 3 and starts again here at once with the new code. Log: data\<name>.log; anything
rem printed outside it, such as a crash, goes to data\<name>.out.log. Usage: scripts\loop.cmd alex
cd /d "%~dp0.."
if not exist data mkdir data
set PYTHONUTF8=1
:start
python -m hunter --who %1 --log "data\%1.log" loop --every 60 >> "data\%1.out.log" 2>&1
if %errorlevel%==3 goto start
