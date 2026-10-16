@echo off
title PM4 full translation + UI -- undo
echo ============================================================
echo   Putting Princess Maker 4 back the way it was
echo ============================================================
echo.
echo   This removes the English story, the English menus and the
echo   Latin keyboard, and leaves your saves alone.
echo.
echo   Close the game first if it is running, then press a key.
echo.
pause >nul

if exist "PM4 full translation+UI.exe" (
    "PM4 full translation+UI.exe" --undo
) else (
    python pm4_full_translate.py --undo
)

echo.
pause
