@echo off
chcp 65001 > nul
REM ============================================================================
REM  ★★ Astrolabe 个人版 · Windows 绿色版打包
REM
REM  用法：在 desktop\ 目录下双击本文件（或在 cmd 里跑 packaging\package-win.bat）
REM  产物：desktop\dist_electron\win-unpacked\
REM
REM  ⚠ 需要先装：Node.js 20+ · Python 3.12（64 位，勾选 Add to PATH）
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo.
echo ============================================================
echo  Astrolabe 个人版 打包
echo ============================================================
echo   工作目录：%CD%
echo.

REM ---------------------------------------------------------------- 0. 环境检查
echo [0/6] 检查环境...
where node >nul 2>&1 || (
  echo   [X] 找不到 node —— 先装 Node.js 20+：https://nodejs.org
  goto :fail
)
where python >nul 2>&1 || (
  echo   [X] 找不到 python —— 先装 Python 3.12 ^(64 位，安装时勾选 Add to PATH^)
  goto :fail
)
for /f "tokens=*" %%v in ('node -v') do echo   node  %%v
for /f "tokens=*" %%v in ('python -c "import sys;print(sys.version.split()[0], sys.maxsize>2**32 and '64位' or '32位')"') do echo   python %%v

REM ★ 第一次下载 electron 很慢（~110MB），走国内镜像可以快很多
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/

REM ---------------------------------------------------------------- 1. 前端依赖
echo.
echo [1/6] 安装前端依赖（首次约 2-3 分钟）...
pushd ..\frontend
call npm install --no-audit --no-fund || goto :fail
popd

REM ---------------------------------------------------------------- 2. 前端构建
echo.
echo [2/6] 构建个人版前端...
pushd ..\frontend
call npm run build:personal || goto :fail
popd
if not exist "..\frontend\dist-personal\index.html" (
  echo   [X] 前端产物不完整：..\frontend\dist-personal\index.html 不存在
  goto :fail
)
echo   OK  ..\frontend\dist-personal

REM ---------------------------------------------------------------- 3. 桌面依赖
echo.
echo [3/6] 安装桌面壳依赖（首次会下载 electron ~110MB，走镜像）...
call npm install --no-audit --no-fund || goto :fail
if not exist "node_modules\electron-builder" (
  echo   [X] electron-builder 没装上
  goto :fail
)
echo   OK  node_modules

REM ---------------------------------------------------------------- 4. 边车依赖
echo.
echo [4/6] 安装 Python 边车依赖（tree-sitter 四个语法包 + pyinstaller）...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r packaging\requirements.txt || goto :fail

REM ---------------------------------------------------------------- 4. 打边车
echo.
echo [5/6] 打包 Python 边车（单文件）...
python -m PyInstaller --clean --noconfirm ^
  --distpath packaging\out --workpath packaging\work ^
  packaging\sidecar.spec || goto :fail
if not exist "packaging\out\astrolabe-sidecar.exe" (
  echo   [X] 没打出 astrolabe-sidecar.exe
  goto :fail
)
for %%f in (packaging\out\astrolabe-sidecar.exe) do echo   OK  %%~ff  ^(%%~zf 字节^)

REM ---------------------------------------------------------------- 5. 打桌面
echo.
echo [6/6] 打包桌面壳（首次会下载 electron ~110MB）...
call npx electron-builder --win dir || goto :fail

echo.
echo ============================================================
echo  完成
echo ============================================================
echo   产物：%CD%\dist_electron\win-unpacked\
echo.
echo   自检一下：
echo     1. 进 dist_electron\win-unpacked，双击 Astrolabe.exe
echo     2. 应弹出一个白窗口，有「选择一个代码目录」
echo     3. 旁边会生成 data\ 目录（数据都在这，拷走即搬家）
echo.
echo   发给朋友：
echo     把 win-unpacked 改名成 Astrolabe，用 7-Zip 压成 .7z
echo     （zip 会比 7z 大 35MB 左右）
echo     附一句：首次运行如果提示"无法验证发布者"，点「更多信息 - 仍要运行」
echo.
exit /b 0

:fail
echo.
echo ============================================================
echo  打包失败 —— 看上面最后几行报错
echo ============================================================
echo   常见原因：
echo     · python 没装 tree-sitter 语法包  ⇒ 重跑第 3 步
echo     · npm install 中断               ⇒ 删掉 node_modules 重来
echo     · electron 下载超时              ⇒ 确认能访问 npmmirror.com
echo.
exit /b 1
