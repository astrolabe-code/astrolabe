@echo off
setlocal
cd /d "%~dp0.."

REM ============================================================
REM  Astrolabe personal edition - Windows portable build
REM  Usage: run from desktop\  (or double-click this file)
REM  Output: desktop\dist_electron\win-unpacked\
REM  Requires: Node.js 20+ , Python 3.12 64-bit (Add to PATH)
REM  Docs: desktop\BUILD.md
REM ============================================================

REM ---- China mirrors (comment out if you have a private registry)
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
set npm_config_registry=https://registry.npmmirror.com
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo ============================================================
echo  Astrolabe - build (portable)
echo ============================================================
echo   workdir: %CD%
echo.

echo [0/6] Checking toolchain...
where node >nul 2>&1
if errorlevel 1 goto :no_node
where python >nul 2>&1
if errorlevel 1 goto :no_python
node -v
python --version

echo.
echo [1/6] Installing frontend deps (first run 2-3 min)...
pushd ..\frontend
call npm install --no-audit --no-fund
if errorlevel 1 goto :fail
popd

echo.
echo [2/6] Building frontend (personal edition)...
pushd ..\frontend
call npm run build:personal
if errorlevel 1 goto :fail
popd
if not exist "..\frontend\dist-personal\index.html" goto :no_dist
echo   OK  ..\frontend\dist-personal

echo.
echo [3/6] Installing desktop deps (electron ~110MB on first run)...
call npm install --no-audit --no-fund
if errorlevel 1 goto :fail
if not exist "node_modules\electron-builder" goto :no_eb
echo   OK  node_modules

REM ---- npm 11+ blocks install scripts until approved (allowScripts).
REM      electron's postinstall downloads the binary; if blocked,
REM      node_modules\electron exists but dist\electron.exe does not.
REM      Run it explicitly so `npm start` works too.
if not exist "node_modules\electron\dist\electron.exe" (
  echo   .. electron binary missing, running its install script
  node node_modules\electron\install.js
  if errorlevel 1 goto :no_electron
)
echo   OK  electron binary

echo.
echo [4/6] Installing sidecar deps (tree-sitter x4 + pyinstaller)...
python -m pip install -r packaging\requirements.txt
if errorlevel 1 goto :fail

echo.
echo [5/6] Packaging Python sidecar...
python -m PyInstaller --clean --noconfirm --distpath packaging\out --workpath packaging\work packaging\sidecar.spec
if errorlevel 1 goto :fail
if not exist "packaging\out\astrolabe-sidecar.exe" goto :no_sidecar
for %%f in (packaging\out\astrolabe-sidecar.exe) do echo   OK  %%~ff  %%~zf bytes

echo.
echo [6/6] Packaging desktop shell...
call npx electron-builder --win dir
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  DONE
echo ============================================================
echo   output: %CD%\dist_electron\win-unpacked\
echo.
echo   self-check:
echo     1. open dist_electron\win-unpacked, run Astrolabe.exe
echo     2. a white window shows 'choose a source directory'
echo     3. a data\ folder appears next to the exe
echo.
echo   ship:
echo     rename win-unpacked to Astrolabe, compress with 7-Zip (.7z)
echo     tell friends: 'More info - Run anyway' if SmartScreen warns
echo.
exit /b 0

:no_node
echo   [X] node not found - install Node.js 20+ from https://nodejs.org
goto :fail

:no_python
echo   [X] python not found - install Python 3.12 64-bit and tick 'Add to PATH'
goto :fail

:no_dist
echo   [X] frontend build missing: ..\frontend\dist-personal\index.html
goto :fail

:no_eb
echo   [X] electron-builder not installed in desktop\node_modules
goto :fail

:no_electron
echo   [X] electron binary download failed - check network or ELECTRON_MIRROR
goto :fail

:no_sidecar
echo   [X] sidecar exe not produced: packaging\out\astrolabe-sidecar.exe
goto :fail

:fail
echo.
echo ============================================================
echo  BUILD FAILED - read the last lines above
echo ============================================================
echo   common causes:
echo     - tree-sitter packages missing  -^> rerun step [4/6]
echo     - npm install interrupted       -^> delete node_modules and retry
echo     - electron download timeout     -^> check access to npmmirror.com
echo.
exit /b 1
