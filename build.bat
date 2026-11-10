@echo off
rem Build music-tag-filler.exe (single file, no console) with PyInstaller.
rem Usage: build.bat          -> dist\music-tag-filler.exe
rem third_party\fpcalc.exe (Chromaprint) is bundled when present.
setlocal
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>&1 || python -m pip install pyinstaller
python -m pip install -r requirements.txt

set FPCALC=
if exist "third_party\fpcalc.exe" set FPCALC=--add-binary "third_party\fpcalc.exe;third_party"
rem acoustid_key.txt (git-ignored) holds the AcoustID application key for the exe.
set KEYFILE=
if exist "acoustid_key.txt" set KEYFILE=--add-data "acoustid_key.txt;."

rem --splash: assets\splash.png is shown while the one-file exe unpacks (a few seconds on a
rem cold start); gui.launch() takes it down once the window is painted (startup.close_splash).
rem --hidden-import: requests and Pillow are imported by name at run time (startup.lazy), which
rem PyInstaller's analysis cannot see; without these the exe lacked certifi and PIL._imagingft
rem (LESSONS D12). tests/test_startup.py checks this list against startup.lazy() calls.
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name music-tag-filler ^
  --icon "assets\icon.ico" ^
  --splash "assets\splash.png" ^
  --hidden-import "requests" ^
  --hidden-import "PIL.Image" ^
  --hidden-import "PIL.ImageDraw" ^
  --hidden-import "PIL.ImageTk" ^
  --add-data "assets\icon.ico;assets" ^
  --add-data "assets\icon.png;assets" ^
  --add-data "lang;lang" ^
  --add-data "third_party\LICENSE-chromaprint;third_party" ^
  %FPCALC% ^
  %KEYFILE% ^
  --collect-data tkinterdnd2 ^
  main.py

if errorlevel 1 (
  echo Build failed.
  exit /b 1
)
echo.
echo Done: dist\music-tag-filler.exe
endlocal
