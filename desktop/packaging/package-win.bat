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
echo [1/6] Installing UI deps (first run 2-3 min)...
pushd ui
call npm install --no-audit --no-fund --foreground-scripts
if errorlevel 1 goto :fail
popd

echo.
echo [2/6] Building UI (personal edition)...
pushd ui
call npm run build
if errorlevel 1 (
  echo   .. build failed, trying esbuild recovery (npm 11 allowScripts gate)
  call npm install-scripts approve esbuild >nul 2>&1
  call npm rebuild esbuild
  call npm run build
)
if errorlevel 1 (
  echo   .. still failing, clean reinstall of ui deps (node_modules will be removed)
  if exist "node_modules" rmdir /s /q "node_modules"
  call npm ci --no-audit --no-fund --foreground-scripts
  call npm run build
)
popd
if not exist "ui\dist\index.html" goto :no_dist
echo   OK  ui\dist

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
echo [4/6] Preparing isolated build venv (keeps Anaconda packages out)...
REM ★ PyInstaller 会在「当前解释器」的环境里分析依赖：直接拿 Anaconda 全局
REM   环境打包，pkg_resources 的 entry_points 会把 Jupyter / Sphinx / PyQt5
REM   (含 QtWebEngine) / MKL / scipy 全拉进来，产物能到 500MB+。
REM   用一个只装 requirements.txt 的干净 venv，体积能回到正常。
if not exist ".venv-build\Scripts\python.exe" (
  python -m venv .venv-build
  if errorlevel 1 goto :no_venv
)
call .venv-build\Scripts\python.exe -m pip install --upgrade pip --quiet
call .venv-build\Scripts\python.exe -m pip install -r packaging\requirements.txt
if errorlevel 1 goto :fail

echo.
echo [5/6] Packaging Python sidecar...
call .venv-build\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath packaging\out --workpath packaging\work packaging\sidecar.spec
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

:no_venv
echo   [X] python -m venv failed - the interpreter has no venv module.
echo       Reinstall Python 3.12 64-bit (it ships venv), or delete
echo       .venv-build and rerun.
goto :fail

:no_dist
echo   [X] UI build missing: ui\dist\index.html
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
