# 第三方组件声明 · Third-Party Notices

本项目使用了以下第三方组件。它们的**版权与许可证归各自作者所有**，
本项目在此**保留并声明**这些权利。

> ⚠ **重要**：本项目自身的许可（见 [LICENSE](LICENSE)）**不因使用它们而改变**。
> ★ 这些依赖均为**宽松许可**（BSD / MIT / PostgreSQL），**允许**本项目以
> 「保留所有权利」的方式发布 —— ★ 前提是**保留它们的版权声明**（本文件即为此用）。

## Python 依赖

| 组件 | 版本 | 许可证 | 版权 |
|---|---|---|---|
| Django | 5.1.4 | BSD-3-Clause | Django Software Foundation |
| djangorestframework | 3.15.2 | BSD-3-Clause | Tom Christie |
| gunicorn | 23.0.0 | MIT | Benoît Chesneau |
| uvicorn | 0.34.0 | BSD-3-Clause | Encode OSS Ltd |
| psycopg | 3.2.3 | LGPL-3.0 | Daniele Varrazzo |
| redis-py | 5.2.1 | MIT | Redis Inc. |
| tree-sitter | 0.23.2 | MIT | Max Brunsfeld |
| tree-sitter-python / -c / -cpp / -java | 0.23.x | MIT | Max Brunsfeld |
| python-dotenv | 1.0.1 | BSD-3-Clause | Saurabh Kumar |

## 运行环境（容器镜像）

| 组件 | 版本 | 许可证 |
|---|---|---|
| PostgreSQL | 17 | PostgreSQL License |
| Valkey | 8.0 | BSD-3-Clause |
| nginx | alpine | BSD-2-Clause |

## 说明

- ★ **LGPL 组件（psycopg）** 以**动态引用**方式使用 —— 本项目**未修改其源码**，
  且使用者可**自行替换**该库的版本（pip 安装天然满足）。
- ★ 各依赖的**完整许可证文本**见其官方仓库。
- ★ 本文件的完整性会随依赖变化而更新（见 `docs/backend-decisions.md`）。
