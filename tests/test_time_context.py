"""
time_context 与 pre_llm_call 时间注入的单元测试。

不依赖任何 Hermes 模块，可独立运行：
    cd time_perception && python -m pytest tests/ -v
"""

import importlib
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_TIME_TAG_RE = re.compile(
    r"^\[Current time: \d{4}-\d{2}-\d{2} \d{2}:\d{2} .+ "
    r"(星期一|星期二|星期三|星期四|星期五|星期六|星期日)\]$"
)


def _fresh_time_context(monkeypatch, *, tz: str | None = None, hermes_home: Path | None = None):
    """重新 import time_context，让模块级 _tz_str 重新求值。"""
    if tz is None:
        monkeypatch.delenv("HERMES_TIMEZONE", raising=False)
    else:
        monkeypatch.setenv("HERMES_TIMEZONE", tz)
    if hermes_home is not None:
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    else:
        monkeypatch.delenv("HERMES_HOME", raising=False)

    sys.modules.pop("time_perception.time_context", None)
    return importlib.import_module("time_perception.time_context")


def test_format_current_time_default_local(monkeypatch):
    mod = _fresh_time_context(monkeypatch)
    tag = mod.format_current_time()
    assert _TIME_TAG_RE.match(tag), f"tag 格式不符: {tag!r}"


def test_format_current_time_explicit_tz(monkeypatch):
    mod = _fresh_time_context(monkeypatch, tz="Asia/Shanghai")
    tag = mod.format_current_time()
    assert _TIME_TAG_RE.match(tag), f"tag 格式不符: {tag!r}"
    assert ("CST" in tag) or ("+0800" in tag) or ("+08" in tag), tag


def test_format_current_time_invalid_tz_falls_back(monkeypatch):
    mod = _fresh_time_context(monkeypatch, tz="Not/A_Real_Zone")
    tag = mod.format_current_time()
    assert _TIME_TAG_RE.match(tag), f"tag 格式不符: {tag!r}"


def test_config_yaml_timezone_used_when_env_unset(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("timezone: Asia/Tokyo\n", encoding="utf-8")
    mod = _fresh_time_context(monkeypatch, tz=None, hermes_home=tmp_path)
    tag = mod.format_current_time()
    assert _TIME_TAG_RE.match(tag), tag
    assert ("JST" in tag) or ("+0900" in tag) or ("+09" in tag), tag


def test_pre_llm_call_hook_returns_time_context(monkeypatch):
    _fresh_time_context(monkeypatch)
    sys.modules.pop("plugin.hooks", None)
    hooks = importlib.import_module("plugin.hooks")

    result = hooks.on_pre_llm_call(
        session_id="s1",
        user_message="hi",
        is_first_turn=True,
        model="gpt-4",
        platform="cli",
        sender_id="user",
    )
    assert isinstance(result, dict)
    assert "context" in result
    assert _TIME_TAG_RE.match(result["context"]), result["context"]


def test_register_hooks_registers_pre_llm_call(monkeypatch):
    _fresh_time_context(monkeypatch)
    sys.modules.pop("plugin.hooks", None)
    hooks = importlib.import_module("plugin.hooks")

    registered: dict[str, object] = {}

    class _FakeCtx:
        def register_hook(self, name, cb):
            registered[name] = cb

    hooks.register_hooks(_FakeCtx())
    assert "pre_llm_call" in registered
    assert registered["pre_llm_call"] is hooks.on_pre_llm_call
