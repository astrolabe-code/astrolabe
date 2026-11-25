"""
小结打分：把 AI 输出的证据锚点，按固定权重折成 0~100 分。

设计原则：AI 只给证据，系统按固定公式算分 —— 同一篇小结永远同一个分，
不会因 AI 心情波动（借鉴 LogiNote 的 threeLayer.ts）。
"""

# 权重（总和 100）
W_WHAT = 40
W_HOW = 25
W_CONCRETE = 25
W_BOUNDARY = 10

# 档位
LEVEL_SOLID = 80      # 扎实
LEVEL_PASS = 60       # 合格（<60 需补充，不算已学）


def score_evidence(ev: dict) -> tuple[int, str]:
    """
    @param ev  AI 输出的 4 个布尔 {covers_what, covers_how, has_concrete, has_boundary}
    @return (分数 0~100, 档位 'solid'|'pass'|'weak')
    """
    s = 0
    if ev.get("covers_what"):
        s += W_WHAT
    if ev.get("covers_how"):
        s += W_HOW
    if ev.get("has_concrete"):
        s += W_CONCRETE
    if ev.get("has_boundary"):
        s += W_BOUNDARY
    s = max(0, min(100, s))
    level = "solid" if s >= LEVEL_SOLID else "pass" if s >= LEVEL_PASS else "weak"
    return s, level


LEVEL_LABEL = {"solid": "扎实", "pass": "合格", "weak": "需补充"}
