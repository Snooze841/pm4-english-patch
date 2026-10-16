@echo off
title PM4 full translation + UI
echo ============================================================
echo   PM4 full translation + UI
echo   Princess Maker 4 in English
echo ============================================================
echo.
echo   Close the game first if it is running, then press a key.
echo.
pause >nul

rem Prefer the packaged program, so nobody needs Python installed. Fall
rem back to the Python file if the .exe is not here -- some people delete
rem it, and some virus scanners quarantine unsigned executables.
if exist "PM4 full translation+UI.exe" (
    "PM4 full translation+UI.exe"
) else (
    python pm4_full_translate.py
)

echo.
pause
