"""
Hermes Time Perception 插件注册入口。

Hermes 自动发现 ~/.hermes/plugins/hermes-time-perception/ 并调用 register(ctx)。
本扩展只做一件事：每个 LLM turn 之前，通过 pre_llm_call hook 把当前时间
append 到 user message 末尾（ephemeral，不污染 system prompt / prompt cache）。
"""

import sys
from pathlib import Path

# 把仓库根目录加入 sys.path，使 time_perception/ 子包可被 import。
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from .hooks import register_hooks


def register(ctx) -> None:
    register_hooks(ctx)
