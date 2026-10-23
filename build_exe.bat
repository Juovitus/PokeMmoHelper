@echo off
REM Builds PokeMmoHelper.exe as ONE file with the Elite Four guide data
REM packed inside. Run this on Windows in the folder that contains
REM PokeMmoHelper.py AND the "e4" folder. Requires Python on PATH.
REM Closes the running app first and starts the new one when done.
REM Pass "nopause" (build_exe.bat nopause) to skip the pauses.
cd /d "%~dp0"
set NOPAUSE=%1
if not exist e4\teams.json (
  echo Could not find e4\teams.json. Put the "e4" folder next to this file.
  if /i not "%NOPAUSE%"=="nopause" pause
  exit /b 1
)
REM Run the tests first (if the tests folder is here); stop if any fail.
if exist tests\ (
  python -m pytest tests -q --no-header
  if errorlevel 1 (
    echo.
    echo Tests FAILED. Nothing was built and the app was not restarted.
    if /i not "%NOPAUSE%"=="nopause" pause
    exit /b 1
  )
)
REM The running exe locks the file, so close it before building.
taskkill /im PokeMmoHelper.exe /f >nul 2>&1
python -m PyInstaller --version >nul 2>&1 || python -m pip install pyinstaller
set SPR=
if exist sprites\ set SPR=--add-data "sprites;sprites"
python -m PyInstaller --onefile --noconsole --distpath . --name PokeMmoHelper --add-data "e4;e4" %SPR% PokeMmoHelper.py
if errorlevel 1 (
  echo.
  echo Build FAILED. The app was not restarted.
  if /i not "%NOPAUSE%"=="nopause" pause
  exit /b 1
)
echo.
echo Done. Your program is PokeMmoHelper.exe
REM Launched through Explorer so the app doesn't hold this window's output
REM open (otherwise whatever ran this script waits until the app closes).
explorer.exe "%~dp0PokeMmoHelper.exe"
if /i not "%NOPAUSE%"=="nopause" pause
