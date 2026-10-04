@echo off
REM Load new data into bank_sales (for Windows Task Scheduler or a double-click).
REM Uses the conda env `homelab`, like the other homelab-postgres jobs.
cd /d "%~dp0"
if not exist logs mkdir logs
"D:\Dynamic\Miniforge3Conda\envs\homelab\python.exe" src\load.py >> logs\load.log 2>&1
