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
                "models": [
            "qwen2.5-coder:7b",
            "qwen2.5-coder:14b",
            "qwen2.5-coder:32b",
            "llama3.2",
            "deepseek-r1:7b",
            "codellama:13b",
        ],
"needs_key": False,
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
                "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
"needs_key": True,
    },
    "kimi": {
        "label": "Kimi（月之暗面）",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-32k",
                "models": [
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
"needs_key": True,
    },
    "glm": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
                "models": [
            "glm-4-flash",
            "glm-4-air",
            "glm-4-plus",
        ],
"needs_key": True,
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
                "models": [
            "qwen-plus",
            "qwen-turbo",
            "qwen-max",
            "qwen2.5-coder-32b-instruct",
        ],
"needs_key": True,
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
                "models": [
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4.1-mini",
        ],
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
                "models": list(preset.get("models") or []),
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


def list_models(provider_id: str = "") -> dict:
    """拉取该服务商的模型列表（`GET {base}/models`）。

    ★ 覆盖：Ollama 的 `/v1/models`、DeepSeek / Kimi / GLM / 通义 / OpenAI
      都实现了这个端点。拉不到不算错误 —— 前端仍可手输模型名。
    ⛔ 不缓存：模型列表会因为本地 `ollama pull` 而变，几秒的请求不值得缓存。
    """
    cfg = load()
    pid = provider_id if provider_id in PRESETS else cfg["active"]
    p = cfg["providers"].get(pid) or {}
    preset = PRESETS.get(pid) or {}
    base = (p.get("base_url") or preset.get("base_url") or "").rstrip("/")
    if not base:
        return {"ok": False, "models": [], "detail": "没有填地址"}

    key = (p.get("api_key") or "").strip()
    if preset.get("needs_key") and not key:
        return {"ok": False, "models": [], "detail": "还没有填 API Key"}

    try:
        data = _call(f"{base}/models", None, key, 12)
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}"
        try:
            detail += f" {exc.read().decode('utf-8', 'replace')[:160]}"
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "models": [], "detail": redact(detail)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "detail": redact(str(exc))}

    models: list[str] = []
    items = data.get("data") if isinstance(data, dict) else None
    for it in items or []:
        if isinstance(it, dict):
            mid = it.get("id") or it.get("name")
            if mid:
                models.append(str(mid))
    models.sort()
    return {"ok": True, "models": models, "detail": ""}


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
    "上下文里标了「人工补的节点」或「人工补的关系」的，说明那不是解析器从源码里得到的，"
    "而是作者手工添加的 —— 引用到它时要说清这一点，不要当成源码事实。"
)

ASK_SYSTEM = (
    BASE_SYSTEM
    + "\n只给了当前节点的源码（可能还有它的笔记）。"
    "需要看上下游或别的节点时，用 read_node / list_neighbors / search_nodes 工具去读，"
    "⛔ 不要凭印象猜它们的实现。"
)

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
        f"第 {node.get('line') or 0}-{node.get('line_end') or 0} 行"
        + ("（人工补的节点）" if str(node.get("origin") or "") == "manual" else ""),
        f"【签名】{node.get('signature') or '（解析器未给出）'}",
        "【源码】",
        f"```{lang}",
        snippet.rstrip(),
        "```",
    ]

    def section(title: str, rows: list[dict]) -> None:
        # ★ 没给就是没给，⛔ 不要写「（无）」—— 那会让模型以为真的没有上游/下游
        if not rows:
            return
        lines.append(f"【{title}】")
        for r in rows[:MAX_NEIGHBORS]:
            name = r.get("qname") or r.get("name") or ""
            tag = "（人工补的节点）" if str(r.get("origin") or "") == "manual" else ""
            lines.append(f"- {name}  @ {r.get('file_path') or ''}:{r.get('line') or 0}{tag}")

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


COMPLETE_SYSTEM = (
    "你是帮作者把「想说的意思」写成「文字」的助手。"
    "作者知道自己想表达什么，只是不容易写出来。\n"
    "你的任务：只写出**接下来最要紧的那半句**，让作者知道「下一句往哪写」。\n"
    "要求：\n"
    "1. 顺着作者的用词和语气写，不要换文风；\n"
    "2. 只写半句到一句 —— 十几个字，一眼能看完；"
    "⛔ 不要试图把整层逻辑一次讲完，细节留给作者自己写；\n"
    "3. 如果作者的表述可以更清楚，用更清楚的写法，但不能改变他的原意；\n"
    "4. 不要总结、不要另起话题、不要加引号、不要解释；\n"
    "5. ⛔ 不要把【作者刚写到】里的字再抄一遍 —— 你输出的是它**后面**的内容；"
    "如果作者写到「这个方」，你从「向下…」开始，而不是「这个方向下…」。"
)


# ★★ 补全的「心理状态」要跟着标签走 —— 所有者原话：
#   「补全的心理状态也要符合选中的标签，写在提示词里」
#   ⚠ 「质疑」与「困惑」的区别来自 kindMeta.ts 里的既有定义：
#     质疑 = 有立场（觉得该那样写）；困惑 = 没立场、只是缺信息。
KIND_HINTS = {
    "flash": (
        "这条笔记是「灵光一闪」：作者刚想通一点东西，心情是兴奋但还没组织好。"
        "顺着这个念头往下推半步，说清「突然明白了什么」就够了，"
        "⛔ 不要展开成论证或正式总结。"
    ),
    "question": (
        "这条笔记是「质疑」：作者认为应该有别的写法，心里是有立场的。"
        "把「那样写为什么更好」的理据说出来，形成一句追问；"
        "⛔ 不要退回去解释被质疑的那段代码。"
    ),
    "confuse": (
        "这条笔记是「困惑」：作者没看懂，只是缺信息，还没有立场。"
        "说清「卡在哪一步、哪个词不明白」，用疑问的口吻；"
        "⛔ 不要直接把答案写出来 —— 那会跳过「发现自己不懂」这一步。"
    ),
    "pitfall": (
        "这条笔记是「踩坑」：作者踩到过问题，想留住教训。"
        "说清「什么情况下会出错、错成什么样」，⛔ 不要写成普适的总结。"
    ),
    "summary": (
        "这条笔记是「小结」：作者在把一片知识串起来。"
        "平实地陈述它做什么、为什么这么写，这里可以比其它类型稍微展开。"
    ),
}


def build_complete_messages(
    node: dict,
    snippet: str,
    lang: str,
    upstream: list[dict],
    downstream: list[dict],
    doc: str,
    before: str,
    kind: str = "",
) -> list[dict]:
    """行内补全的 prompt：由「作者正在写的半句」续写十几个字。

    ★ 带上**整篇已写内容**（学语气），但⛔ 不要求模仿思维方式 ——
      提示词里只说「顺着用词和语气」，并允许更清楚的表述。
    ★ 上下文段与问答/（原）草稿共用，前缀保持稳定，能吃 provider 缓存。
    """
    ctx = _context_block(node, snippet, lang, upstream, downstream, [])
    # ★★ 以「光标向上的文字」为基础 —— 所有者原话：
    #   「应该光标在哪里，就以光标向上的文字为基础补全」
    #   ⛔ 不能只看当前段落：上一段说过什么，决定了下一句该往哪写。
    #   tail = 紧前的半句（接续用）；head = 更早的内容（学用词和语气）
    text = (before or doc or "").strip()
    tail = text[-300:]
    head = text[:-300].strip()[-600:]
    parts = [ctx]
    if head:
        parts.append(f"【作者已经写的内容（学它的用词和语气，不要照抄）】\n{head}")
    if tail:
        parts.append(f"【作者刚写到】\n{tail}")
    hint = KIND_HINTS.get(str(kind or "").strip())
    if hint:
        parts.append(f"【这条笔记的语气】\n{hint}")
    parts.append(
        "【任务】接着上面往下写**最要紧的那半句**（十几个字，一眼能看完），"
        "让作者知道下一句往哪写；⛔ 不要一次讲完所有细节。直接给出文字，不要解释。"
    )
    return [
        {"role": "system", "content": COMPLETE_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


# ============================================================================
# 流式对话（SSE）
# ============================================================================
# ============================================================================
# 起标题（正文够，⛔ 不需要节点上下文 —— 省一截 token）
# ============================================================================
KIND_LABELS = {
    "flash": "灵光一闪",
    "question": "质疑",
    "confuse": "困惑",
    "pitfall": "踩坑",
    "summary": "小结",
}

TITLE_SYSTEM = (
    "你是帮作者给笔记起标题的助手。"
    "根据正文起一个**中文标题**：10-20 字，概括这段笔记真正说了什么。\n"
    "要求：不要书名号、不要「小结」「灵光一闪」这类类型前缀、不要结尾句号；"
    "只输出标题本身，不要解释、不要引号。"
)


def build_title_messages(body_text: str, kind: str = "") -> list[dict]:
    """起标题的 prompt。★ 只用正文，⛔ 不塞源码/邻居（标题不该由代码决定）。"""
    parts: list[str] = []
    label = KIND_LABELS.get(str(kind or "").strip())
    if label:
        parts.append(f"【这条笔记的类型】{label}")
    parts.append(f"【正文】\n{str(body_text or '').strip()[:600]}")
    parts.append("【任务】起一个标题，直接输出标题本身。")
    return [
        {"role": "system", "content": TITLE_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def clean_title(text: str) -> str:
    """清掉模型可能带的引号/书名号/句号，⛔ 不按句读截断（标题本来就短）。"""
    t = str(text or "").strip().replace("\n", " ")
    for ch in "《》\"'“”「」『』":
        t = t.replace(ch, "")
    t = t.strip().rstrip("。.，,；;：:")
    # ★ 模型有时仍带「小结：」「灵光一闪：」前缀 —— prompt 说了但它不一定听
    for label in KIND_LABELS.values():
        for sep in ("：", ":"):
            if t.startswith(label + sep):
                t = t[len(label) + 1 :].strip()
    return t[:40].strip()


# ============================================================================
# 节点思考题：带上下文出题 + 联系已学笔记
# ============================================================================
# ★★ 不同类型的节点，值得追问的东西完全不同
#
# 所有者原话（2026-11-17）：
# 「节点有好几种类型的，你要分类写提示语呀。」
#
# ⚠ 这里只给**关注方向**，不写死具体问题；
#   格式（陷阱/优化/背景）由前端解析，保持统一。
KIND_FOCUS = {
    "function": "参数前提、返回值约定、错误路径；它和调用者的分工是否清楚",
    "method": "它依赖对象的哪些状态、这些状态会不会不一致；和同类其它方法的关系",
    "class": "职责边界、状态由谁维护、要扩展时该改哪里",
    "interface": "这个接口承诺了什么、实现方要满足哪些隐含前提",
    "struct": "字段谁写谁读、内存布局与对齐、生命周期",
    "union": "同一块内存被当成几种类型用，谁负责记住当前是哪种",
    "enum": "取值是否穷尽、默认分支怎么处理",
    "typedef": "它想隐藏什么细节、别名会不会掩盖真实类型",
    "record": "字段的可变性、相等性语义",
    "macro": "展开后的真实行为、参数求值次数、作用域泄漏",
    "module": "对外暴露什么、内部依赖谁",
    "package": "包的分层、哪些是公开 API",
    "variable": "作用域、生命周期、谁修改它",
    "constant": "值是怎么定的、改了会影响谁",
    "field": "由谁维护、何时变化",
    "type": "它表达什么约束、和运行时类型的差距",
    "file": "这个文件的职责、和同目录其它文件怎么分工、为什么这样切",
    "dir": "为什么这样分目录、层与层的依赖方向、放错的代价",
}


QUESTIONS_SYSTEM = (
    "你是根据提供的代码图谱信息，带新手读代码的老师。任务是**提问**，不是解释代码。\n"
    "不给答案，也不要暗示答案；不问「这个函数做什么」（读者会自己写）。\n"
    "\n"
    "输出格式（不要别的文字）：\n"
    "陷阱：<前提 / 边界 / 错误处理 / 容易出错、形成 bug 的地方>\n"
    "优化：<为什么不按更自然的写法>\n"
    "背景：<这段代码牵涉到的任何学科背景，不限于计算机和数学>\n"
    "下一步：<节点名> —— <理由>\n"
    "\n"
    "问题按**能问出的来**，1 到 3 个都行，不要求凑满。\n"
    "⛔ 宁可少问，不要为了凑数编造 —— 编出来的问题会误导读者。\n"
    "\n"
    "要不要问、问几个，你自己判断这个节点值不值得问：\n"
    "同样是「一句调用」，有的藏着边界与约定（异常被吞、参数被悄悄改写、"
    "顺序有依赖、失败时静默），有的只是把参数原样传下去、读者一眼就懂。\n"
    "空文件、纯声明、常量表、类型别名也是一样 —— 读了源码和必要的邻居，才知道是哪种。\n"
    "⛔ 不要按节点类型或代码行数去猜它难不难。\n"
    "读完确实没有值得问的，只输出一行：\n"
    "简评：<为什么没什么可问，建议接着看哪个节点>\n"
    "\n"
    "材料可能不完整。需要看别的节点时，用提供的工具去读，不要猜。\n"
    "问题落在这个节点上，不要去问相邻的其它节点；提到相邻节点时，说清它和这个节点的关系。\n"
    "能联系【你之前学过】时尽量联系，引用读者的原话，不要改写。\n"
    "没有【你之前学过】就当第一次看，不许编造「你可能记得」。\n"
    "源码标注为「空文件」时那是正常的（包标记文件之类），不要问「源码在哪」。"
)


def build_questions_messages(pack: dict, learned: list[dict] | None = None) -> list[dict]:
    """把一个「上下文包」渲染成 prompt。

    ★ 借鉴 GitNexus 的 `MODULE_USER_PROMPT`（源码 + 三层调用 + 执行流一并给），
      但目标是**出题**而不是写文档。
    ★ `learned` 里是用户在这个节点附近写过的笔记（原文），用于复习式提问。
    """
    node = pack.get("node") or {}
    kind = str(node.get("kind") or "").lower()
    parts: list[str] = [
        f"[当前节点类型]:{kind} ",
        f"[当前节点名字]:{node.get('name') or ''}",
        f"[当前节点路径]:{node.get('file') or ''}:{node.get('line') or 0}-{node.get('line_end') or 0}",
        f"[当前节点签名]:{node.get('signature') or '（解析器未给出）'}",
    ]
    # ★ 按类型给关注方向（dir 和 method 不该被问同一套东西）
    focus = KIND_FOCUS.get(kind)
    if focus:
        parts.append(f"[这类节点值得追问的]:{focus}")
    # ★ 文件语义：告诉模型「这个文件本来长什么样」，避免把「空」当异常
    hint = str(pack.get("file_hint") or "").strip()
    if hint:
        parts.append(f"[这个文件是]:{hint}")
    parts.extend(
        [
            "[源码]",
            "```",
            str(pack.get("snippet") or "（读不到源码）"),
            "```",
        ]
    )
    if pack.get("truncated_node"):
        parts.append("（注意：当前节点源码超过 200 行，上面是前 200 行）")

    sibs = pack.get("siblings") or []
    if sibs:
        # ★ 少而全：每个带源码（原来只给名字+行号，信息量太低）
        lines = ["【同文件的其它函数（带源码，看这个文件在做什么）】"]
        for x in sibs:
            lines.append(f"- {x.get('name')}  @{x.get('line')}")
            lines.append(f"```\n{x.get('snippet') or ''}\n```")
        more = int(pack.get("siblings_more") or 0)
        if more:
            lines.append(f"（同文件还有 {more} 个函数未给出）")
        parts.append("\n".join(lines))

    def block(title: str, rows: list[dict]) -> None:
        if not rows:
            return
        parts.append(f"[{title}]")
        for r in rows:
            parts.append(
                f"- {r.get('name')}  @ {r.get('file')}:{r.get('line')}\n"
                f"```\n{r.get('snippet') or ''}\n```"
            )

    block("它调用的函数（完整源码）", pack.get("downstream") or [])
    block("调用它的函数（完整源码）", pack.get("upstream") or [])

    dropped = pack.get("dropped") or {}
    lost = int(dropped.get("downstream") or 0) + int(dropped.get("upstream") or 0)
    if lost:
        parts.append(f"（还有 {lost} 个相邻函数因长度限制未给出）")

    # ★★ 说清这份上下游有多可信：
    #   解析边可能漏（动态分派 / 回调 / 反射），手工补的边是用户给的、确切。
    #   ⛔ 不把两者混成一句「可能不准」——那会低估用户补图的价值。
    ep = pack.get("epistemic") or {}
    ep_manual = int(ep.get("manual") or 0)
    ep_parsed = int(ep.get("parsed") or 0)
    if ep_manual or ep_parsed:
        lines = ["【这份上下游有多可信】"]
        if ep_parsed:
            lines.append(
                f"- {ep_parsed} 条来自静态解析：动态分派、回调、反射可能没连上，"
                "所以「没看到某个调用者」不等于「它不存在」"
            )
        if ep_manual:
            lines.append(
                f"- {ep_manual} 条是读者手工补的：这些是**确切**的，直接当真"
            )
        parts.append("\n".join(lines))

    flows = pack.get("flows") or []
    if flows:
        parts.append(
            "[它在这些执行流里]\n"
            + "\n".join(
                f"- 第 {i + 1} 条（{f.get('length')} 步）：" + " → ".join(f.get("labels") or [])
                for i, f in enumerate(flows)
            )
        )

    sus = pack.get("suspicious") or []
    if sus:
        parts.append(
            "[正则扫出的线索（不完整，只用于定位；不要只依赖这些）]\n"
            + "\n".join(f"- {x}" for x in sus)
        )

    # ★ 目录节点：给它的直接子项（文件名/子目录），让模型能问「这个目录为什么这样切分」
    kids = pack.get("children") or []
    if kids:
        lines = ["[这个目录里的东西（子目录 / 文件）]"]
        for c in kids[:30]:
            mark = "目录" if c.get("kind") == "dir" else "文件"
            lines.append(f"- [{mark}] {c.get('name')}")
        if len(kids) > 30:
            lines.append(f"（还有 {len(kids) - 30} 项未列出）")
        parts.append("\n".join(lines))

    # ---- 用户之前学过的（引用原话，⛔ 不概括）
    if learned:
        lines = ["[你之前学过（读者自己写的原话，不要改写）]"]
        for it in learned[:3]:
            age = it.get("age_days")
            when = f"{age} 天前" if isinstance(age, int) and age >= 0 else "之前"
            lines.append(
                f"- {it.get('name')}（{when}写的{it.get('kind_label') or '笔记'}，"
                f"关系：{it.get('relation') or '同一片代码'}）"
            )
            lines.append(f"  「{str(it.get('text') or '').strip()[:200]}」")
        parts.append("\n".join(lines))
    else:
        parts.append("[你之前学过]\n（这是第一次看这附近，不要假装读者记得什么）")

    parts.append(
        "[任务]按上面的格式出 3 个问题，并给最多 2 条「下一步可以读」。"
        "引用代码事实时以上面给出的材料为准；背景类问题只问「有什么关系」，不下结论。"
        "线索只是定位参考，真正的疑点要你自己从源码里看出来。"
    )
    return [
        {"role": "system", "content": QUESTIONS_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def parse_questions(text: str) -> dict:
    """把模型输出解析成 `{items: [{type, text}], next: [{name, why}]}`。

    ★ 三条策略：
      ① 优先认固定前缀（陷阱 / 优化 / 背景 / 下一步 / 简评）
      ② 认不出的行**不丢**，留着当兜底
      ③ 一条都没认出来、但模型确实说了话 ⇒ 整段当「简评」返回

    ⚠ 第 ③ 条是为了对面现实：模型经常直接写一段判断（「这个类没什么可问」），
      不按格式来。丢掉它会让界面显示「检查 AI 设置」——那是误导。
    """
    items: list[dict] = []
    nxt: list[dict] = []
    note = ""
    plain: list[str] = []

    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("-·•* 　").strip()
        if not line:
            continue
        hit = False

        # 1) 简评
        for sep in ("：", ":"):
            if line.startswith("简评" + sep):
                note = line[3:].strip()
                hit = True
                break
        if hit:
            continue

        # 2) 三类问题
        for label in ("陷阱", "优化", "背景"):
            for sep in ("：", ":"):
                if line.startswith(label + sep):
                    body = line[len(label) + 1 :].strip()
                    if body:
                        items.append({"type": label, "text": body})
                    hit = True
                    break
            if hit:
                break
        if hit:
            continue

        # 3) 下一步
        for sep in ("：", ":"):
            if line.startswith("下一步" + sep):
                rest = line[4:].strip()
                name, _, why = rest.partition("——")
                if not why:
                    name, _, why = rest.partition("-")
                nxt.append({"name": name.strip(), "why": why.strip()})
                hit = True
                break
        if hit:
            continue

        # 4) 认不出：先留着（⛔ 不要丢）
        plain.append(line)

    # ★ 兜底：一个好的问题都没解析出来，但模型说了话
    if not items:
        fallback = note or " ".join(plain)
        if fallback.strip():
            items.append({"type": "简评", "text": fallback.strip()[:300]})

    # ★ 最多留 5 条：允许模型出「两个陷阱 + 一个优化」这种组合，
    #   ⛔ 不要卡在 3 条——那会把第 4、5 条直接丢掉（用户看到的就是"少了"）
    return {"items": items[:5], "next": nxt[:2]}


def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    executor,
    max_rounds: int | None = None,
    max_tokens: int = 800,
    deadline_s: float = 180.0,
):
    """带**只读工具**的多轮流式对话。

    所有者原话（2026-11-18）：
    「工具调用不要设限制了，ai读不到，列出的问题太莫名其妙了。」

    ⇒ 默认**不限轮数**（`max_rounds=None`）。只保留两条安全阀，
      它们都不是「限制 AI 思考」，而是防止真的转死：

    ```
    ① 同一组「工具 + 参数」第二次出现 ⇒ 立刻收尾
       模型原地打转时再跑下去只是烧钱，读不到就是读不到
    ② 总时长超过 deadline_s（默认 180 秒）⇒ 收尾
       本地小模型偶尔会连续吐 tool_calls，要有个兜底
    ```

    ⚠ 上面的循环用 `while`；每轮都重发完整历史，轮数越多 token 越多，
      但**这是使用者自己要的**（宁可多读，也不要瞎问）。
    """
    convo = list(messages)
    t0 = time.time()
    seen: set[str] = set()
    rnd = 0

    while True:
        rnd += 1
        if max_rounds is not None and rnd > max_rounds:
            break
        if time.time() - t0 > deadline_s:
            break

        pending: dict[int, dict] = {}
        text_acc: list[str] = []

        for evt in stream_chat(convo, max_tokens=max_tokens, tools=tools):
            kind = evt.get("event")
            if kind == "delta":
                text_acc.append(str(evt.get("text") or ""))
                yield evt
            elif kind == "tool":
                idx = int(evt.get("index") or 0)
                slot = pending.setdefault(idx, {"id": "", "name": "", "args": ""})
                if evt.get("id"):
                    slot["id"] = str(evt["id"])
                fn = evt.get("function") or {}
                if isinstance(fn, dict):
                    if fn.get("name"):
                        slot["name"] = str(fn["name"])
                    if fn.get("arguments"):
                        slot["args"] += str(fn["arguments"])
            else:
                yield evt

        if not pending:
            return

        calls = []
        for idx in sorted(pending):
            slot = pending[idx]
            calls.append(
                {
                    "id": slot["id"] or f"call_{idx}",
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": slot["args"] or "{}"},
                }
            )

        # ★ 安全阀 ①：同样的调用重复出现 ⇒ 它读不到了，别再转
        signature = "|".join(f"{c['function']['name']}::{c['function']['arguments']}" for c in calls)
        if signature in seen:
            yield {
                "event": "step",
                "round": rnd,
                "note": "重复的读取请求，已停止（读不到就是读不到，不必再试）",
            }
            break
        seen.add(signature)

        convo.append(
            {"role": "assistant", "content": "".join(text_acc) or None, "tool_calls": calls}
        )

        for c in calls:
            fname = str(c["function"]["name"] or "")
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
                if not isinstance(args, dict):
                    args = {}
            except Exception:  # noqa: BLE001
                args = {}
            try:
                res = executor(fname, args)
            except Exception as exc:  # noqa: BLE001
                res = f"工具 {fname} 执行失败：{redact(str(exc))}"
            convo.append(
                {"role": "tool", "tool_call_id": c["id"], "content": str(res)[:4000]}
            )

        yield {"event": "step", "round": rnd}

    # 到这里说明撞上了安全阀：让它只用已看到的作答
    convo.append(
        {
            "role": "user",
            "content": "（读取已结束。请只根据上面看到的内容回答，不要再请求工具。）",
        }
    )
    for evt in stream_chat(convo, max_tokens=max_tokens):
        if evt.get("event") == "delta":
            yield evt
        elif evt.get("event") == "usage":
            yield evt


def brief(text: str, limit: int = 24, after: str = "") -> str:
    """把完整补全截成「一眼能看完」的开头（最多 24 字，且回退到最近的句读）。

    ★ 显示给用户的必须是**十几个字**的提示 —— 一次显示好几句就变成代写了，
      和作者「自己写」的初衷冲突。模型话痨时由这里兜底。
    ★ `after` = 作者已经写出的尾部：模型经常把它再抄一遍
      （写「这个方」，它输出「这个方向下…」），这里从最长匹配开始剥掉，
      否则界面上会出现「这个方这个方向下」。
    """
    t = str(text or "").strip().replace("\n", " ").strip()
    a = str(after or "").strip()
    # ★ 先试完整 after，再逐级缩短 —— 漏掉「等长」会切不掉整句重复
    for n in [len(a), 40, 30, 20, 12, 8, 6, 5, 4, 3, 2]:
        if 0 < n <= len(a) and t.startswith(a[-n:]):
            t = t[len(a[-n:]) :].lstrip("，,。.、；;：: ")
            break
    if len(t) <= limit:
        return t
    head = t[:limit]
    for i in range(len(head) - 1, 0, -1):
        if head[i] in "。！？；，、 ":
            return head[:i].rstrip()
    return head.rstrip()


def chat_once(messages: list[dict], max_tokens: int = 120) -> str:
    """一次性拿完整文本（补全用）：内部仍走 stream_chat，但把片段拼起来。

    ★ 补全只要十几个字，流式反而闪；调用方拿到整段直接显示成浅色提示。
    """
    parts: list[str] = []
    for evt in stream_chat(messages, max_tokens=max_tokens):
        if evt.get("event") == "delta":
            parts.append(str(evt.get("text") or ""))
    return "".join(parts).strip()


def stream_chat(
    messages: list[dict],
    max_tokens: int = 600,
    deadline_s: float = 120,
    tools: list[dict] | None = None,
):
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
    # ★ 只读工具（读节点 / 列邻居 / 搜索）：模型可主动要求读更多
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    if act["api_key"]:
        req.add_header("Authorization", f"Bearer {act['api_key']}")

    t0 = time.time()
    # ★ 统计「到底吐了多少字」：一个字都没出时必须报错，
    #   ⛔ 不能静默返回空回答（用户只会看到「问了但没回答」，无从排查）
    got = 0
    got_tool = False
    try:
        # ⚠ 首字超时给足：本地 7B/14B 在 CPU 上第一块可能要几十秒，
        #   30 秒会误判成超时（此处是单次读超时，不是总时长）
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
            for raw in resp:
                if time.time() - t0 > deadline_s:
                    raise RuntimeError("生成超时")
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                # ★★ 三种返回形态都认：
                #   ① OpenAI / DeepSeek 的 SSE：`data: {"choices":[{"delta":{...}}]}`
                #   ② 有的兼容层忽略 stream：一整块 JSON，内容在 `message.content`
                #   ③ Ollama 原生 NDJSON：`{"message":{"content":"..."}}`（无 data: 前缀）
                payload = line[5:].strip() if line.startswith("data:") else line
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except Exception:  # noqa: BLE001
                    continue

                piece = ""
                if isinstance(obj, dict):
                    choices = obj.get("choices") or []
                    if choices:
                        ch = choices[0] if isinstance(choices[0], dict) else {}
                        piece = (ch.get("delta") or {}).get("content") or ""
                        if not piece:
                            piece = (ch.get("message") or {}).get("content") or ""
                    if not piece and isinstance(obj.get("message"), dict):
                        piece = obj["message"].get("content") or ""

                if piece:
                    got += 1
                    yield {"event": "delta", "text": piece}

                # ★★ 工具调用：流式下是**增量分片**（同一 index 的 arguments 一段段来），
                #   这里只透出原始片段，累积交给 chat_with_tools。
                if isinstance(obj, dict):
                    chs = obj.get("choices") or []
                    dl = (chs[0].get("delta") or {}) if chs and isinstance(chs[0], dict) else {}
                    tcs = dl.get("tool_calls") if isinstance(dl, dict) else None
                    if isinstance(tcs, list):
                        for tc in tcs:
                            if isinstance(tc, dict):
                                got_tool = True
                                yield {"event": "tool", **tc}

                usage = obj.get("usage") if isinstance(obj, dict) else None
                if not isinstance(usage, dict):
                    # Ollama 原生用量字段
                    if isinstance(obj, dict) and obj.get("eval_count"):
                        usage = {
                            "prompt_tokens": obj.get("prompt_eval_count") or 0,
                            "completion_tokens": obj.get("eval_count") or 0,
                        }
                if isinstance(usage, dict):
                    # ★★ 尽量把各家 usage 的细节都摊平：
                    #   DeepSeek：prompt_cache_hit_tokens / prompt_cache_miss_tokens
                    #   OpenAI  ：prompt_tokens_details.cached_tokens
                    #   推理模型：completion_tokens_details.reasoning_tokens
                    #   Ollama  ：只有 prompt_eval_count / eval_count（无缓存概念）
                    pin = int(usage.get("prompt_tokens") or 0)
                    pout = int(usage.get("completion_tokens") or 0)
                    total = int(usage.get("total_tokens") or (pin + pout))

                    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
                    miss = int(usage.get("prompt_cache_miss_tokens") or 0)
                    pdet = usage.get("prompt_tokens_details")
                    if not hit and isinstance(pdet, dict):
                        hit = int(pdet.get("cached_tokens") or 0)
                    if not miss and pin:
                        miss = max(0, pin - hit)

                    think = 0
                    cdet = usage.get("completion_tokens_details")
                    if isinstance(cdet, dict):
                        think = int(cdet.get("reasoning_tokens") or 0)
                    if not think:
                        think = int(usage.get("reasoning_tokens") or 0)

                    yield {
                        "event": "usage",
                        "in": pin,
                        "out": pout,
                        "total": total,
                        # 缓存三项：命中 / 未命中 / 写入（写入目前没有服务商给出）
                        "hit": hit,
                        "miss": miss,
                        "write": int(usage.get("cache_write_tokens") or 0),
                        # 推理模型：思考 vs 回答
                        "think": think,
                        "response": max(0, pout - think),
                    }
        if got == 0 and not got_tool:
            raise RuntimeError(
                "模型没有返回任何内容。常见原因：模型名不对、该模型不支持 chat 补全，"
                "或服务端未按流式返回（可先在设置里点「测试连通」确认）"
            )
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}"
        try:
            detail += f" {exc.read().decode('utf-8', 'replace')[:300]}"
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(redact(detail)) from None
