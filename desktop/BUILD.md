# 个人版打包（绿色版）

目标产物：一个文件夹，朋友解压后双击 `Astrolabe.exe` 就能用，**不需要装 Python / Node / WebView2**。

```
Astrolabe/
├─ Astrolabe.exe
├─ resources/
│  ├─ app.asar                 前端 + 主进程代码
│  ├─ dist/                    前端构建产物
│  ├─ sidecar/astrolabe-sidecar .exe   Python 边车（解析器 + SQLite）
│  └─ THIRD-PARTY-NOTICES.txt  许可证声明（⚠ 必须随包分发）
├─ locales/                    只留 zh-CN / en-US
└─ data/                       用户数据（首次启动自动创建）
```

## 三条命令

```bash
# ① 前端（个人版构建，产物在 frontend/dist-personal）
npm run build:web

# ② Python 边车（PyInstaller 单文件，约 10–25MB）
npm run build:sidecar

# ③ 打绿色版目录
npm run dist:win      # Windows
npm run dist:linux    # Linux（仅用于验证配置）
```

产物在 `dist_electron/win-unpacked/`（Windows）。**没有安装器，也没有快捷方式** —— 要的话自己建。

## Linux 上打不了 Windows 包

```
electron-builder --win 需要 wine（改 exe 资源、图标）
⇒ Windows 的包必须在 Windows 上打（或 CI 的 windows-latest）
```

## 已知的体积（实测）

| 项 | 数值 |
|---|---|
| Python 边车（单文件） | 10 MB |
| 整个目录（解包） | 约 240 MB |
| 打成 zip | 约 104 MB |
| 打成 7z (`-mx=9`) | **约 69 MB** ← 建议发这个 |

⚠ 发 zip 比 7z 大 35MB，纯粹是压缩算法差别。朋友用 7-Zip / WinRAR 解压即可。

## 首次运行会发生什么

```
① 在 exe 同目录创建 data/（绿色版的关键：不写注册表、不写 %APPDATA%）
② 启动 Python 边车（stdio，⛔ 不监听端口）
③ 加载 app://local/app/（自定义协议，⛔ 不是 localhost）
```

## 常见问题

**Q：双击没反应？**
边车启动失败时窗口会显示错误；也可以命令行运行看输出。

**Q：朋友电脑提示"无法验证发布者"？**
未签名。右键 → 属性 → 解除锁定，或"更多信息 → 仍要运行"。

**Q：数据在哪？**
exe 同目录的 `data/`。整个文件夹拷走就是搬家。

**Q：能升级吗？**
直接覆盖 exe 和 resources/，**不要覆盖 data/**。
