# hermes-time-perception

> English: [README.md](README.md)

Hermes Agent 的独立时间感知扩展。每个 LLM turn 发起之前，通过原生 `pre_llm_call` hook
把当前时间标签 append 到 user message 末尾。

- **零 patch**：完全走 Hermes 正规扩展面，不修改任何 Hermes 源码。
- **ephemeral**：注入内容只存在于当次 LLM 请求，不持久化到 session DB，不影响 prompt cache。
- **时区可配置**：`HERMES_TIMEZONE` 环境变量 > `~/.hermes/config.yaml` 的 `timezone` > 系统本地时区。

## 注入示例

```
[Current time: 2026-05-20 14:30 CST 星期三]
```

## 文件结构

```
time_perception/
├── plugin/
│   ├── plugin.yaml          # Hermes 插件清单
│   ├── __init__.py          # register(ctx) 入口
│   └── hooks.py             # pre_llm_call hook
├── time_perception/         # 纯 Python 工具包，零 Hermes 耦合
│   ├── __init__.py
│   └── time_context.py
├── tests/
│   └── test_time_context.py
├── init_design.md           # 设计背景与 roadmap
└── README.md
```

## 安装

```bash
mkdir -p ~/.hermes/plugins
ln -snf /home/gejifeng/DEV/Hermes_dev/time_perception/plugin \
        ~/.hermes/plugins/hermes-time-perception

hermes plugins enable hermes-time-perception
hermes plugins list   # 应看到 enabled
```

## 时区配置（可选）

```bash
export HERMES_TIMEZONE="Asia/Shanghai"
```
或写进 `~/.hermes/config.yaml`：
```yaml
timezone: Asia/Shanghai
```

## 验证

```bash
# 1. 单元测试
cd /home/gejifeng/DEV/Hermes_dev/time_perception
python3 -m pytest tests/ -v

# 2. 手动 smoke
python3 -c "from time_perception.time_context import format_current_time; print(format_current_time())"

# 3. 真实端到端
hermes -z "请回答：现在的日期、时间、星期几？"
```

## 卸载

```bash
hermes plugins disable hermes-time-perception
rm ~/.hermes/plugins/hermes-time-perception
```

## 兼容性

- Hermes v0.12.x / v0.13.x 已验证 `pre_llm_call` 与 `PluginContext.register_hook`。
- 升级 Hermes 后，运行 `python3 -m pytest tests/ -v` 即可回归。
