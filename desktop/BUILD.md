# 个人版打包（Windows 绿色版）

目标：一个文件夹，朋友解压后双击 `Astrolabe.exe` 就能用，
**不需要装 Python / Node / WebView2**。

```
Astrolabe/
├─ Astrolabe.exe
├─ resources/
│  ├─ app.asar                       前端 + 主进程
│  ├─ dist/                          前端构建产物
│  ├─ sidecar/astrolabe-sidecar.exe  Python 边车（解析器 + SQLite）
│  └─ THIRD-PARTY-NOTICES.txt        许可证声明（⚠ 必须随包分发）
├─ locales/                          只留 zh-CN / en-US
└─ data/                             用户数据（首次启动自动创建）
```

---

## 一、准备（只做一次）

| 装什么 | 版本 | 注意 |
|---|---|---|
| **Node.js** | 20 LTS 或更新 | 装完 `node -v` 能看到版本 |
| **Python** | 3.12 **64 位** | ⚠ 安装时勾选 **Add python.exe to PATH** |

装完在 **cmd** 里确认：

```bat
node -v
python --version
```

### 把代码放到 Windows 上

两种都行：

```bat
REM ① 从 git 拉（推荐，以后更新方便）
git clone <仓库地址> astrolabe
cd astrolabe

REM ② 或者把整个 astrolabe 目录拷过来（U 盘 / 共享目录）
```

⚠ 目录里不要带中文和空格，避免 electron-builder 路径出问题。

---

## 二、一键打包

```bat
cd astrolabe\desktop
packaging\package-win.bat
```

脚本会依次做 6 件事，每步失败都会停下并告诉你原因：

```
[0/6] 检查 node / python 有没有装、是不是 64 位
[1/6] npm install            前端依赖（首次 2-3 分钟）
[2/6] npm run build:personal 前端构建 → frontend\dist-personal
[3/6] npm install            桌面依赖（首次下载 electron ~110MB，走国内镜像）
[4/6] pip install -r packaging\requirements.txt
                             ★ tree-sitter 四个语法包 + pyinstaller
[5/6] PyInstaller            边车单文件 → packaging\out\astrolabe-sidecar.exe
[6/6] electron-builder --win dir → dist_electron\win-unpacked\
```

**产物**：`desktop\dist_electron\win-unpacked\`

---

## 三、自己先验一遍（重要）

```
1. 进 dist_electron\win-unpacked\
2. 双击 Astrolabe.exe
3. 应该弹出一个白窗口，中间是「选择一个代码目录」
4. 选一个你熟悉的代码目录 → 等它解析 → 看到节点列表
5. 点一个节点 → 写一句话 → 写下 → 标题自动取好了
6. 关掉，再双击 → 应该直接回到上次那个节点
```

同时检查：

```
□ 同目录下出现 data\（astrolabe.db + 笔记 .md）
□ 断网后仍能打开、能写（只有"导入新仓库"不需要网络）
□ 任务管理器里没有常驻的 python.exe 失控进程
```

---

## 四、发给朋友

```
① 把 win-unpacked 改名成 Astrolabe
② 用 7-Zip 压成 .7z（zip 会大 35MB 左右）
③ 附一句话：
   「解压后双击 Astrolabe.exe。如果提示"无法验证发布者"，
     点『更多信息 → 仍要运行』。」
```

实测体积（Linux 版，Windows 接近）：

| 形态 | 大小 |
|---|---|
| 解包目录 | 约 240 MB |
| zip | 约 104 MB |
| 7z (`-mx=9`) | **约 69 MB** |
| 对照：Obsidian 官方 exe | 326 MB |

---

## 五、出问题怎么查

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 双击没反应 | 边车启动失败 | 在 cmd 里跑 `Astrolabe.exe` 看报错 |
| 解析出 0 个节点 | Python 里缺语法包 | 重跑第 4、5 步；确认 `pip list` 有 `tree-sitter-python` |
| `electron-builder` 下载超时 | 网络 | 脚本已设 `ELECTRON_MIRROR=npmmirror`；确认能访问 npmmirror.com |
| 打包报 "author is missed" | 已修 | `package.json` 里有 `author` 字段了 |
| 前端白屏 | `dist-personal` 没构建 | 检查 `frontend\dist-personal\index.html` 是否存在 |
| 朋友打开提示缺 DLL | 系统太旧（Win7/8） | 需要 Win10 1809+ |

---

## 六、为什么不能在这台 Linux 上打 Windows 包

```
electron-builder --win 需要 wine（改 exe 图标与版本信息）
PyInstaller 不能交叉编译（Windows 的 exe 只能在 Windows 上打）
```

所以：**Windows 包必须在 Windows（或 CI 的 windows-latest）上打。**
Linux 上只能打 `--linux dir`，用来验证配置本身没写错。
