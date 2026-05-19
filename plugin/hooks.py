"""
Hermes pre_llm_call hook —— 时间感知注入。

Hermes 在每个 turn 发起 LLM 调用之前触发 pre_llm_call。
本 hook 返回的 {"context": "..."} 会被 append 到当前 turn 的 user message 末尾，
对 LLM 可见但不污染 system prompt（保护 prompt cache prefix），也不持久化到 session DB。
"""

from time_perception.time_context import format_current_time


def on_pre_llm_call(*, session_id: str = "", user_message: str = "",
                    conversation_history=None, is_first_turn: bool = False,
                    model: str = "", platform: str = "", sender_id: str = "",
                    **kwargs) -> dict:
    """每 turn 返回当前时间标签（ephemeral，append 到 user message 末尾）。"""
    return {"context": format_current_time()}


def register_hooks(ctx) -> None:
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
