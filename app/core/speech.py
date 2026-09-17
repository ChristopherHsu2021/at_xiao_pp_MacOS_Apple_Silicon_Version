"""人设语音规则：句尾『了 / 呢』强制替换为『捏』。

规则仅作用于句尾（句子结束标点之前或字符串末尾的 了/呢），
句中非句尾的 了/呢 保持不变（如『你吃了吗』）。
"""

import re

_SENT_SPLIT = re.compile(r"([。！？!?…]+)")
_TAIL = re.compile(r"[了呢]$")


def apply_ni(text: str) -> str:
    """将文本中所有句尾的 了/呢 替换为 捏。"""
    if not text:
        return text
    out = []
    for i, part in enumerate(_SENT_SPLIT.split(text)):
        if i % 2 == 1:  # 分隔符（句号等）
            out.append(part)
        else:
            out.append(_TAIL.sub("捏", part))
    return "".join(out)


def pick_line(lines: list, rng=None) -> str:
    """从台词列表中随机取一句并应用 捏 规则。"""
    if not lines:
        return ""
    if rng is not None:
        choice = rng.choice(lines)
    else:
        import random
        choice = random.choice(lines)
    return apply_ni(choice)
