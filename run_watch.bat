@echo off
REM Wrapper for Windows Task Scheduler. Runs the internship watcher and logs output.
title Internship Watcher - scheduled posting check
cd /d "%~dp0"

REM Uses the py launcher on PATH. Override if python lives elsewhere.
set "PY=py"
set "TMPOUT=%TEMP%\internship_watcher_out.txt"

cls
echo.
echo   ============================================================
echo      INTERNSHIP WATCHER  --  scheduled run, not malware
echo   ============================================================
echo.
echo      What it does : checks the SimplifyJobs Summer 2027 repo
echo                     for new software engineering internships.
echo      Launched by  : Windows Task Scheduler, task "InternshipWatcher"
echo      Script       : %~dp0watch.py
echo      Results log  : %~dp0run.log
echo      Postings list: %~dp0tracker.md
echo.
echo      It does NOT submit applications and installs nothing.
echo      This window closes by itself in a few seconds.
echo.
echo   ------------------------------------------------------------
echo.

"%PY%" "%~dp0watch.py" > "%TMPOUT%" 2>&1
"%PY%" "%~dp0enrich.py" >> "%TMPOUT%" 2>&1
"%PY%" "%~dp0tailor.py" --all-apply --quiet >> "%TMPOUT%" 2>&1
REM digest before opening tabs, so it can link the resumes tailor.py just built
"%PY%" "%~dp0enrich.py" --digest-only >> "%TMPOUT%" 2>&1
REM open only postings never opened before, capped -- so a busy morning
REM doesn't bury the desktop and a quiet one opens nothing at all
"%PY%" "%~dp0open_apps.py" --new-only --max 3 >> "%TMPOUT%" 2>&1
type "%TMPOUT%"

echo. >> run.log
echo ===== %DATE% %TIME% ===== >> run.log
type "%TMPOUT%" >> run.log
del "%TMPOUT%" >nul 2>&1

echo.
echo   ------------------------------------------------------------
echo      Done. Closing automatically...
echo.
REM ping-based pause: works even when stdin is redirected (timeout /t does not)
ping -n 13 127.0.0.1 >nul 2>&1
