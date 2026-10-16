@echo off
title PM4 -- add the English keyboard
echo ============================================================
echo   Add the English name-entry keyboard
echo ============================================================
echo.
echo   This changes the character table inside PrincessMaker4.exe
echo   AND paints the letters onto the on-screen keys, because those
echo   two only make sense together: keys showing A while the game
echo   types a kana would be worse than leaving them in Japanese.
echo.
echo   Editing the program file is why this is separate from the
echo   main install.
echo.
echo   Princess Maker 4 came with copy protection that checks the
echo   program against itself before the game starts. If that
echo   protection is still active on your copy, changing the file
echo   stops the game from starting -- so this will look at your
echo   copy first and refuse rather than risk it.
echo.
echo   If anything goes wrong, Undo.bat puts the file back exactly
echo   as it was.
echo.
echo   Close the game first if it is running, then press a key.
echo.
pause >nul

if exist "PM4 full translation+UI.exe" (
    "PM4 full translation+UI.exe" --keyboard --no-story
) else (
    python pm4_full_translate.py --keyboard --no-story
)

echo.
pause
