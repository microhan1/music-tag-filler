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

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name music-tag-filler ^
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
