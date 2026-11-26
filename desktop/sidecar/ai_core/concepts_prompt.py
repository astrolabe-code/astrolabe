"""
知识点标注：读一段源码，列出它用到的知识点。

设计：
  · 不预设类别 —— 代码背后的知识可能来自任何领域（计算机/数学/物理/生物/工程…）
  · 输出是一段纯文本，用顿号分隔，直接存进 Code.concepts（最多约 100 字）
  · 截断按「知识点」为单位，⛔ 不把单个知识点截成半截（见 clip_concepts）
"""

CONCEPTS_SYSTEM = """你读代码，指出这段代码**真正用到**的知识点。

# 输出格式（硬性要求，违反即失败）

**只输出一行纯文本**，格式严格如下：

知识点一、知识点二、知识点三

- 用中文顿号「、」分隔
- 不要 JSON、不要数组、不要对象、不要代码块
- 不要编号、不要引号、不要前缀（如「知识点：」「好的」「以下是」）
- 不要解释、不要换行、不要结尾句号
- 最多 5 个，每个 2~10 个字

## 唯一正确的输出示例

引用计数、RCU、缓存局部性、无锁编程

## 错误示例（绝对不要这样输出）

- ["引用计数", "RCU"]          ← 错误：JSON 数组
- {"concepts": ["RCU"]}        ← 错误：JSON 对象
- 好的，我来分析：引用计数      ← 错误：有前缀
- 1. 引用计数 2. RCU           ← 错误：有编号
- 这段代码用了引用计数。        ← 错误：有解释/句号

# 内容要求

知识点不限领域 —— 计算机、数学、物理、统计、工程、生物等都可以。
只列这段代码**确实体现**的，不要泛泛而谈（「函数」「循环」「变量」不算知识点）。

现在直接输出那一行，不要其它任何文字。"""


def build_concepts_messages(snippet: str, name: str = "") -> list[dict]:
    """给 AI 的 prompt：只要源码片段，不要邻居/笔记/上下文。"""
    parts = [
        f"【函数名】{str(name or '').strip()[:120]}",
        f"【源码】\n{str(snippet or '').strip()[:2500]}",
        "【任务】只输出一行顿号分隔的知识点（如：引用计数、RCU、缓存局部性）。"
        "禁止 JSON、禁止代码块、禁止解释、禁止前缀。现在直接输出那一行。",
    ]
    return [
        {"role": "system", "content": CONCEPTS_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def clip_concepts(text: str, limit: int = 100) -> str:
    """
    ★ 把 AI 输出的知识点文本限制在 limit 字以内。

    按「知识点」为单位从后往前丢 —— ⛔ 绝不把某个知识点截成半截。
    分隔符优先顿号「、」，兼容逗号「,」「，」和换行。
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    # 归一成统一分隔符
    for sep in ("，", ",", "\n", "；", ";"):
        raw = raw.replace(sep, "、")
    items = [p.strip(" 。.;；·-") for p in raw.split("、")]
    items = [p for p in items if p]
    if not items:
        return ""
    out: list[str] = []
    for item in items:
        candidate = "、".join(out + [item])
        if len(candidate) <= limit:
            out.append(item)
        else:
            break   # ★ 放不下就停，不切 item
    # 若连第一个都放不下（极端长词），才硬截——但这是最后手段
    if not out and items:
        return items[0][:limit]
    return "、".join(out)


def clean_concepts(text: str) -> str:
    """清理模型输出 → 顿号分隔的一行知识点（≤100字，按项截断）。"""
    import json, re
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    # ① 兼容 JSON 数组输出：["引用计数","RCU"]
    if raw.startswith("[") or raw.startswith("{"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, list):
                raw = "、".join(str(x) for x in obj)
            elif isinstance(obj, dict):
                v = obj.get("concepts") or obj.get("knowledge") or obj.get("result")
                if isinstance(v, list):
                    raw = "、".join(str(x) for x in v)
                elif isinstance(v, str):
                    raw = v
        except Exception:
            pass
    # ② 去包装前缀（反复）
    prefixes = ("知识点如下：", "知识点如下:", "知识点：", "知识点:", "concepts:")
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if raw.lower().startswith(prefix.lower()):
                raw = raw[len(prefix):].strip().strip('"“”\'`')
                changed = True
                break
    # ③ 去编号列表（「1. RCU 2. 缓存」→「RCU、缓存」）
    raw = re.sub(r'(?:^|\s)\d+[.、)]\s*', '、', raw)
    raw = re.sub(r'^、+', '', raw)

    # ④ 按行拆分，丢掉「好的/我来分析」这类非知识点行
    junk = ("好的", "我来分析", "以下是", "这是", "分析如下", "作为", "注意", "希望", "以上")
    parts = []
    for line in raw.splitlines():
        line = line.strip(" 　·-*\t")
        if not line:
            continue
        if any(line.startswith(j) for j in junk):
            continue
        parts.append(line)
    raw = "、".join(parts)
    return clip_concepts(raw, limit=100)
