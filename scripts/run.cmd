@echo off
rem Runs the hunter for one candidate forever. Log: data\<name>.log (rotated at 5 MB); anything printed
rem outside the log, such as a crash, goes to data\<name>.out.log. Usage: scripts\run.cmd alex
cd /d "%~dp0.."
if not exist data mkdir data
set PYTHONUTF8=1
python -m hunter --who %1 --log "data\%1.log" loop --every 60 >> "data\%1.out.log" 2>&1
