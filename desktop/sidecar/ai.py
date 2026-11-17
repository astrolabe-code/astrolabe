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
        f"第 {node.get('line') or 0}-{node.get('line_end') or 0} 行"
        + ("（人工补的节点）" if str(node.get("origin") or "") == "manual" else ""),
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
QUESTIONS_SYSTEM = (
    "你是带新手读代码的老师。你的任务不是解释代码，而是**提出问题**，"
    "让读者注意到他本来不会注意的东西。\n"
    "⛔ 绝不给答案，也不要暗示答案；⛔ 不要问「这个函数做什么」（读者会自己写）。\n"
    "输出格式（严格三行 + 最多两行下一步，⛔ 不要别的文字）：\n"
    "陷阱：<一个关于前提/边界/错误处理的问题>\n"
    "优化：<一个关于「为什么不按最自然的写法」的问题>\n"
    "背景：<一个关于操作系统/CPU/语言标准/历史约束的问题，结尾加（背景知识）>\n"
    "下一步：<节点名> —— <理由>\n"
    "下一步：<节点名> —— <理由>\n"
    "★ 下面给的「可疑点」只是**用正则机械扫出来的线索**，很不完整；"
    "你必须通读源码自己找问题 —— 异常路径没处理、某个前提可能不成立、"
    "边界与类型转换、锁的范围、缓冲区大小、返回值约定……"
    "这些往往比魔数更值得问。\n"
    "★ 三个问题中**至少一个**要联系【你之前学过】里的内容，"
    "问「他那时学到的结论，在这里怎么起作用 / 还成不成立」；"
    "引用时用读者的原话，⛔ 不要改写成要点。\n"
    "★ 如果没有【你之前学过】，就当作第一次看这里，⛔ 不许编造「你可能记得」之类。"
)


def build_questions_messages(pack: dict, learned: list[dict] | None = None) -> list[dict]:
    """把一个「上下文包」渲染成 prompt。

    ★ 借鉴 GitNexus 的 `MODULE_USER_PROMPT`（源码 + 三层调用 + 执行流一并给），
      但目标是**出题**而不是写文档。
    ★ `learned` 里是用户在这个节点附近写过的笔记（原文），用于复习式提问。
    """
    node = pack.get("node") or {}
    parts: list[str] = [
        f"【当前节点】{node.get('kind') or ''} {node.get('name') or ''}"
        f"  @ {node.get('file') or ''}:{node.get('line') or 0}-{node.get('line_end') or 0}",
        f"【签名】{node.get('signature') or '（解析器未给出）'}",
        "【源码】",
        "```",
        str(pack.get("snippet") or "（读不到源码）"),
        "```",
    ]
    if pack.get("truncated_node"):
        parts.append("（注意：当前节点源码超过 200 行，上面是前 200 行）")

    sibs = pack.get("siblings") or []
    if sibs:
        parts.append(
            "【同文件的其它函数（只看名字，判断这个文件的职责）】\n"
            + "\n".join(f"- {x.get('name')}  @{x.get('line')}" for x in sibs)
        )

    def block(title: str, rows: list[dict]) -> None:
        if not rows:
            return
        parts.append(f"【{title}】")
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

    flows = pack.get("flows") or []
    if flows:
        parts.append(
            "【它在这些执行流里】\n"
            + "\n".join(
                f"- 第 {i + 1} 条（{f.get('length')} 步）：" + " → ".join(f.get("labels") or [])
                for i, f in enumerate(flows)
            )
        )

    sus = pack.get("suspicious") or []
    if sus:
        parts.append(
            "【正则扫出的线索（不完整，只用于定位；⛔ 不要只依赖这些）】\n"
            + "\n".join(f"- {x}" for x in sus)
        )

    # ---- 用户之前学过的（引用原话，⛔ 不概括）
    if learned:
        lines = ["【你之前学过（读者自己写的原话，⛔ 不要改写）】"]
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
        parts.append("【你之前学过】\n（这是第一次看这附近，⛔ 不要假装读者记得什么）")

    parts.append(
        "【任务】按 system 里规定的格式出 3 个问题（陷阱 / 优化 / 背景），"
        "并给出最多 2 条「下一步可以读」。"
        "★ 线索只是帮你快速定位，真正的可疑之处要你自己读源码发现；"
        "★ 问题里若引用代码事实，必须能指到上面给出的源码；"
        "背景类问题只问「有什么关系」，⛔ 不要下结论。"
    )
    return [
        {"role": "system", "content": QUESTIONS_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def parse_questions(text: str) -> dict:
    """把模型输出解析成 `{items: [{type, text}], next: [{name, why}]}`。

    ⚠ 用固定前缀行解析而不是 JSON：小模型经常把 JSON 写坏，
      而这种格式坏一行只丢一条，不会整段报废。
    """
    items: list[dict] = []
    nxt: list[dict] = []
    for raw in str(text or "").splitlines():
        s = raw.strip().lstrip("-·•* ").strip()
        if not s:
            continue
        for label in ("陷阱", "优化", "背景"):
            for sep in ("：", ":"):
                if s.startswith(label + sep):
                    body = s[len(label) + 1 :].strip()
                    if body:
                        items.append({"type": label, "text": body})
                    break
            else:
                continue
            break
        else:
            for sep in ("：", ":"):
                if s.startswith("下一步" + sep):
                    rest = s[4:].strip()
                    name, _, why = rest.partition("——")
                    if not why:
                        name, _, why = rest.partition("-")
                    nxt.append({"name": name.strip(), "why": why.strip()})
                    break
    return {"items": items[:3], "next": nxt[:2]}


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
    # ★ 统计「到底吐了多少字」：一个字都没出时必须报错，
    #   ⛔ 不能静默返回空回答（用户只会看到「问了但没回答」，无从排查）
    got = 0
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
        if got == 0:
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
