#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ AI 接入：**OpenAI 兼容协议**（云端服务商 + 本地 Ollama）

## 所有者原话（逐字）

> 「注意不要写出漏洞，把用户的云端key泄露了，刷爆别人的token，
>   还有缓存命中率想办法高一点，减少token消耗。」

## 三条铁律

```
① Key 不泄露
   · 存 ASTROLABE_DATA_DIR/ai.json（⛔ 不在项目目录 ⇒ 不会被 git 带走）
   · 文件权限 600
   · 对外只返回打码（sk-****ab12）
   · 任何异常/日志出海前都过一遍 redact() —— 有的 SDK 会把请求头打进异常

② 不刷爆 token
   · 只在用户点按钮时调一次；⛔ 不自动重试（超时/失败直接报）
   · max_tokens 由调用方封顶
   · ⛔ 不做「批量给所有节点生成」

③ 缓存命中率高
   · prompt 前缀固定：system → 节点静态信息 → 易变内容最后
   · ⛔ 不往 prompt 里塞时间戳 / 随机 id（会让前缀缓存全部失效）
```

## 为什么只支持 OpenAI 兼容协议

DeepSeek / Kimi / GLM / 通义 / OpenAI / **Ollama（`/v1`）** 都说同一套协议，
一个 client 通吃。Anthropic 走 `/v1/messages`，是不同的协议（所有者 2026-11-15：
「Claude 那兼容可以先不做，外网访问慢不说，还限制中文」）。
"""

from __future__ import annotations

import json
import os
import stat
import time
import urllib.error
import urllib.request

import library

# ============================================================================
# 预设（选中自动填 base_url，用户只需填 key）
# ============================================================================
PRESETS: dict[str, dict] = {
    "local": {
        "label": "Ollama（本地）",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder:7b",
        "needs_key": False,
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "needs_key": True,
    },
    "kimi": {
        "label": "Kimi（月之暗面）",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-32k",
        "needs_key": True,
    },
    "glm": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "needs_key": True,
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "needs_key": True,
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "needs_key": True,
    },
}

DEFAULT_ACTIVE = "local"


# ============================================================================
# 配置读写
# ============================================================================
def config_path() -> str:
    """`ai.json` 放**全局数据目录**（exe 旁的 data/），⛔ 不在项目目录里。"""
    return os.path.join(library.data_dir(), "ai.json")


def _defaults() -> dict:
    return {
        "active": DEFAULT_ACTIVE,
        "providers": {
            pid: {
                "base_url": p["base_url"],
                "model": p["model"],
                "api_key": "",
            }
            for pid, p in PRESETS.items()
        },
    }


def load() -> dict:
    """读配置；坏文件/缺字段都退回默认值（⛔ 不因为配置文件坏了就崩）。"""
    base = _defaults()
    try:
        with open(config_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:  # noqa: BLE001
        return base
    if not isinstance(raw, dict):
        return base

    active = str(raw.get("active") or DEFAULT_ACTIVE)
    if active not in PRESETS:
        active = DEFAULT_ACTIVE
    base["active"] = active

    providers = raw.get("providers")
    if isinstance(providers, dict):
        for pid, p in providers.items():
            if pid not in base["providers"] or not isinstance(p, dict):
                continue
            for field in ("base_url", "model", "api_key"):
                if isinstance(p.get(field), str):
                    base["providers"][pid][field] = p[field].strip()
    return base


def save(patch: dict) -> dict:
    """合并保存；**空 key 表示不改**（前端不会拿回明文，所以不能靠它回填）。"""
    cfg = load()
    patch = patch if isinstance(patch, dict) else {}

    active = patch.get("active")
    if isinstance(active, str) and active in PRESETS:
        cfg["active"] = active

    incoming = patch.get("providers")
    if isinstance(incoming, dict):
        for pid, p in incoming.items():
            if pid not in cfg["providers"] or not isinstance(p, dict):
                continue
            cur = cfg["providers"][pid]
            for field in ("base_url", "model"):
                if isinstance(p.get(field), str) and p[field].strip():
                    cur[field] = p[field].strip()
            key = p.get("api_key")
            # ★ 只有显式传了非空 key 才覆盖；传 "" / 不传 ⇒ 保留原 key
            if isinstance(key, str) and key.strip():
                cur["api_key"] = key.strip()

    path = config_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 600：仅本人可读
    except Exception:  # noqa: BLE001 —— Windows 上 chmod 支持有限
        pass
    os.replace(tmp, path)
    return public()


# ============================================================================
# 密钥脱敏（所有对外文本都要过这一层）
# ============================================================================
def _known_keys() -> list[str]:
    cfg = load()
    return [
        (p.get("api_key") or "").strip()
        for p in cfg["providers"].values()
        if (p.get("api_key") or "").strip()
    ]


def redact(text: str) -> str:
    """把任何已知 key 从文本里抹掉。

    ⚠ 这是最后一道闸：异常信息、HTTP 响应体、第三方库的报错都可能带上 key。
    """
    out = str(text or "")
    for key in _known_keys():
        if len(key) > 8:
            out = out.replace(key, "***")
    # 兜底：形如 sk-xxxx 的串一律打码（哪怕不是我们配置里的）
    import re

    return re.sub(r"\b(sk|pk)-[A-Za-z0-9_\-]{8,}", "***", out)


def mask(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "***"
    return f"{k[:3]}****{k[-4:]}"


def public() -> dict:
    """对外视图：**不含 key 明文**。"""
    cfg = load()
    items = []
    for pid, preset in PRESETS.items():
        p = cfg["providers"].get(pid) or {}
        key = (p.get("api_key") or "").strip()
        items.append(
            {
                "id": pid,
                "label": preset["label"],
                "base_url": p.get("base_url") or preset["base_url"],
                "model": p.get("model") or preset["model"],
                "needs_key": bool(preset.get("needs_key")),
                "has_key": bool(key),
                "key_masked": mask(key),
            }
        )
    return {"active": cfg["active"], "items": items, "path": config_path()}


def active() -> dict:
    """当前生效的服务商（含明文 key，**只在服务端内部用**）。"""
    cfg = load()
    pid = cfg["active"]
    p = cfg["providers"].get(pid) or {}
    preset = PRESETS.get(pid) or {}
    return {
        "id": pid,
        "label": preset.get("label") or pid,
        "base_url": (p.get("base_url") or preset.get("base_url") or "").rstrip("/"),
        "model": p.get("model") or preset.get("model") or "",
        "api_key": (p.get("api_key") or "").strip(),
        "needs_key": bool(preset.get("needs_key")),
    }


# ============================================================================
# HTTP（标准库，⛔ 不引 openai SDK：它体积大、且会把请求头写进日志）
# ============================================================================
def _call(url: str, payload: dict | None, key: str, timeout: float) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body = resp.read().decode("utf-8", "replace")
    return json.loads(body) if body.strip() else {}


def probe(provider_id: str = "") -> dict:
    """连通性测试。

    · 本地：`GET {base}/models`（Ollama 没启动会直接连不上）
    · 云端：`POST {base}/chat/completions`，`max_tokens=1`（最便宜的验证方式）
    """
    cfg = load()
    pid = provider_id if provider_id in PRESETS else cfg["active"]
    p = cfg["providers"].get(pid) or {}
    preset = PRESETS.get(pid) or {}
    base = (p.get("base_url") or preset.get("base_url") or "").rstrip("/")
    if not base:
        return {"ok": False, "provider": pid, "detail": "没有 base_url", "latency_ms": 0}

    key = (p.get("api_key") or "").strip()
    if preset.get("needs_key") and not key:
        return {"ok": False, "provider": pid, "detail": "还没有填 API Key", "latency_ms": 0}

    t0 = time.time()
    try:
        if pid == "local":
            _call(f"{base}/models", None, key, 8)
        else:
            _call(
                f"{base}/chat/completions",
                {
                    "model": p.get("model") or preset.get("model") or "",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "stream": False,
                },
                key,
                20,
            )
        return {
            "ok": True,
            "provider": pid,
            "detail": "",
            "latency_ms": int((time.time() - t0) * 1000),
        }
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}"
        try:
            detail += f" {exc.read().decode('utf-8', 'replace')[:200]}"
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": False,
            "provider": pid,
            "detail": redact(detail),
            "latency_ms": int((time.time() - t0) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        # ⚠ 本地连不上时把「怎么启动」说清楚，⛔ 不要只说 connection refused
        msg = str(exc)
        if pid == "local" and ("refused" in msg.lower() or "connect" in msg.lower()):
            msg = "连不上 Ollama：先在终端运行 `ollama serve`（或确认 11434 端口）"
        return {
            "ok": False,
            "provider": pid,
            "detail": redact(msg),
            "latency_ms": int((time.time() - t0) * 1000),
        }
