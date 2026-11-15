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
        if pid == "local":
            # ★ 地址不是本机 ⇒ 是局域网里另一台机器，提示要换（不是「先 ollama serve」）
            remote = ("localhost" not in base) and ("127.0.0.1" not in base)
            low = msg.lower()
            if remote:
                msg = (
                    f"连不上 {base}：{msg}。"
                    "对方机器需以 OLLAMA_HOST=0.0.0.0 启动，并放行 11434 端口"
                )
            elif "refused" in low or "connect" in low:
                msg = "连不上 Ollama：先在终端运行 `ollama serve`（或确认 11434 端口）"
        return {
            "ok": False,
            "provider": pid,
            "detail": redact(msg),
            "latency_ms": int((time.time() - t0) * 1000),
        }


# ============================================================================
# 小结草稿：prompt 组装（顺序 = 缓存命中率）
# ============================================================================
# ★ 草稿和问答**共用同一个 system 开头**：
#   前缀越一致，provider 的前缀缓存命中率越高（DeepSeek / OpenAI 都按前缀计价）
BASE_SYSTEM = (
    "你是帮编程初学者读懂代码的助手。"
    "只根据用户给出的代码与上下文回答，不要编造上下文里没有的函数、文件或行为。"
    "用中文，平实具体，不用「本文」「综上所述」这类套话。"
)

DRAFT_SYSTEM = BASE_SYSTEM
ASK_SYSTEM = BASE_SYSTEM

MAX_NEIGHBORS = 8
MAX_SAMPLES = 2
MAX_SAMPLE_CHARS = 120


def _context_block(
    node: dict,
    snippet: str,
    lang: str,
    upstream: list[dict],
    downstream: list[dict],
    samples: list[dict],
) -> str:
    """节点上下文（草稿与问答**完全共用**，这样两边的 prompt 前缀一致）。

    ⚠ 顺序即缓存命中率：节点静态信息 → 源码 → 邻居 → 样例。
      ⛔ 不插时间戳 / 随机 id —— 那会让前缀每次都不同，缓存全部失效。
    """
    lines = [
        f"【节点】{node.get('kind') or ''}  {node.get('file') or ''}  "
        f"第 {node.get('line') or 0}-{node.get('line_end') or 0} 行",
        f"【签名】{node.get('signature') or '（解析器未给出）'}",
        "【源码】",
        f"```{lang}",
        snippet.rstrip(),
        "```",
    ]

    def section(title: str, rows: list[dict]) -> None:
        lines.append(f"【{title}】")
        if not rows:
            lines.append("- （无）")
            return
        for r in rows[:MAX_NEIGHBORS]:
            name = r.get("qname") or r.get("name") or ""
            lines.append(f"- {name}  @ {r.get('file_path') or ''}:{r.get('line') or 0}")

    section("它调用的函数", downstream)
    section("调用它的函数", upstream)

    lines.append("【作者写过的小结（只参考语气，不要照抄）】")
    if samples:
        for smp in samples[:MAX_SAMPLES]:
            title = str(smp.get("title") or "").strip()
            body = str(smp.get("excerpt") or "").strip().replace("\n", " ")
            lines.append(f"- {title}：{body[:MAX_SAMPLE_CHARS]}")
    else:
        lines.append("- （还没有）")

    return "\n".join(lines)


def build_draft_messages(
    node: dict,
    snippet: str,
    lang: str,
    upstream: list[dict],
    downstream: list[dict],
    samples: list[dict],
) -> list[dict]:
    """组装**小结草稿**的 prompt（上下文段与问答共用）。"""
    ctx = _context_block(node, snippet, lang, upstream, downstream, samples)
    task = (
        "【任务】写一段 150–300 字的小结，面向第一次读这段代码的人："
        "它做什么、为什么这么写、有什么容易踩的坑。"
        "不要逐行解释代码，也不要重复代码本身。"
    )
    return [
        {"role": "system", "content": DRAFT_SYSTEM},
        {"role": "user", "content": ctx + "\n" + task},
    ]


def build_ask_messages(
    node: dict,
    snippet: str,
    lang: str,
    upstream: list[dict],
    downstream: list[dict],
    samples: list[dict],
    question: str,
) -> list[dict]:
    """组装**问答**的 prompt。

    ★ 上下文段与草稿逐字相同 ⇒ 先让草稿跑过一次的项目，
      再问问题能命中前缀缓存（便宜约 10 倍）。
    """
    ctx = _context_block(node, snippet, lang, upstream, downstream, samples)
    q = str(question or "").strip()
    return [
        {"role": "system", "content": ASK_SYSTEM},
        {"role": "user", "content": f"{ctx}\n【问题】{q}\n（只答这个问题，不要写小结。）"},
    ]


# ============================================================================
# 流式对话（SSE）
# ============================================================================
def stream_chat(messages: list[dict], max_tokens: int = 600, deadline_s: float = 120):
    """逐块 yield `{"event":"delta","text":...}`，最后可能有一条 `usage`。

    ⚠ 不自动重试：超时/失败直接抛，由调用方转成 error 事件（
      所有者原话：「不要...刷爆别人的token」—— 静默重试最容易烧钱）。
    """
    act = active()
    if act["needs_key"] and not act["api_key"]:
        raise RuntimeError("还没有填 API Key（设置 → AI）")
    if not act["base_url"] or not act["model"]:
        raise RuntimeError("AI 配置不完整（缺 base_url 或 model）")

    url = f"{act['base_url']}/chat/completions"
    payload = {
        "model": act["model"],
        "messages": messages,
        "max_tokens": int(max_tokens),
        "stream": True,
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    if act["api_key"]:
        req.add_header("Authorization", f"Bearer {act['api_key']}")

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            for raw in resp:
                if time.time() - t0 > deadline_s:
                    raise RuntimeError("生成超时")
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:  # noqa: BLE001
                    continue
                choices = obj.get("choices") or []
                if choices:
                    piece = (choices[0].get("delta") or {}).get("content") or ""
                    if piece:
                        yield {"event": "delta", "text": piece}
                usage = obj.get("usage")
                if isinstance(usage, dict):
                    yield {
                        "event": "usage",
                        "in": int(usage.get("prompt_tokens") or 0),
                        "out": int(usage.get("completion_tokens") or 0),
                    }
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}"
        try:
            detail += f" {exc.read().decode('utf-8', 'replace')[:300]}"
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(redact(detail)) from None
