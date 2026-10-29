@echo off
REM ★★ 个人版 Windows 绿色版打包（在你自己的 Windows 上跑）
REM    产物：dist_electron\win-unpacked\
setlocal

echo [1/3] 构建前端（个人版）
pushd ..\frontend
call npm run build:personal || goto :fail
popd

echo [2/3] 构建 Python 边车
call npm run build:sidecar || goto :fail

echo [3/3] 打绿色版目录
call npx electron-builder --win dir || goto :fail

echo.
echo 完成：dist_electron\win-unpacked\
echo 建议用 7z 压缩后发给朋友（zip 会大 35MB）
exit /b 0

:fail
echo.
echo 打包失败，看上面的日志。
exit /b 1
