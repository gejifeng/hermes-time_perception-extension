# Xiaoya Agent Temporal Memory Architecture

作者: 阿峰 & 小雅
日期: 2026-05-14
版本: v1.1 Draft

## 1. 设计背景

小雅需要具备更自然的时间感和连续性：既能知道“现在几点”，也能理解“刚才隔了一小时”“今晚六点我们聊过这个”。原 v1.0 方案提出用 5 分钟 cron 写入当前时间、事件捕获和夜间精炼来解决问题。经过工程评估后，v1.1 对方案边界做出调整。

核心修正:

- 当前时间不进入长期记忆，只作为每轮模型调用的临时上下文。
- 过去事件不记录流水账，而是形成小时级或显著间隔级的时间锚点。
- Night Sage 不替代 Honcho，而作为记忆治理层，先生成本地可审计摘要，再谨慎写入长期记忆。
- Cron job 适合做稳定调度，不适合把实时信息热更新进活跃 agent session。

## 2. 目标

1. 当前感: 小雅能在每轮回复中感知当前北京时间。
2. 间隔感: 小雅能知道两次消息之间过去了多久。
3. 叙事感: 小雅能把一天的交流压缩成少量关键时间锚点。
4. 可治理: 长期记忆必须可审计、可去重、可删除，避免污染 Honcho 和 MEMORY。
5. 低成本: 不用 5 分钟 LLM cron，不把时间流水写进上下文窗口。

## 3. 设计原则

### 3.1 当前时间不是记忆

当前时间类似人类看钟表，不需要被记住。每次模型调用前动态生成即可。

错误做法:

```text
每 5 分钟创建一条时间记忆，然后让模型读这些记忆。
```

推荐做法:

```text
Current Beijing time: 2026-05-14 21:03 Asia/Shanghai
```

这段信息只存在于当前模型请求中，不写入 session history、Honcho 或 MEMORY。

### 3.2 过去不是流水账，而是时间脊柱

小雅不需要记住每分钟发生了什么。她需要的是一条压缩后的 temporal spine:

```text
18:00-19:00 讨论 Hermes 时间感知架构。
19:48-21:03 长暂停。
21:03 阿峰继续追问长对话中的时间间隔感知。
```

### 3.3 Honcho 负责通用记忆，Night Sage 负责治理

Honcho 已经会做通用的消息同步、观察、表示和检索。Night Sage 不应重复把原始对话再总结一遍灌入 Honcho。

Night Sage 的定位是:

- 生成每日摘要和时间锚点。
- 识别重复、临时、低价值内容。
- 给重要事件打标签。
- 生成候选长期结论。
- 先本地保存，必要时少量写入 Honcho conclusions。

## 4. 系统架构

### 4.1 Ephemeral Time Context

每次模型调用前，Hermes 动态生成一段短上下文:

```text
Temporal context:
- Current Beijing time: 2026-05-14 21:03 Asia/Shanghai
- Conversation started: 18:02, about 3h ago
- Last user message: 19:47, about 1h16m ago
- Last assistant reply: 19:48, about 1h15m ago
- Significant idle gap detected since the last exchange
```

工程要点:

- 不追加到 messages 历史中。
- 不进入长期记忆。
- 不破坏静态 system prompt 的 prompt cache。
- 放在每次请求的末尾 runtime context 区。
- 时间源使用 Hermes 已有的 timezone-aware `hermes_time.now()`。

配置要求:

```yaml
timezone: Asia/Shanghai
```

### 4.2 Temporal Spine

Temporal Spine 是对当前会话时间结构的压缩描述。它从消息数据库和事件锚点中动态生成。

输入:

- `~/.hermes/state.db` 中的 sessions/messages。
- 当前 session 的 `started_at`。
- 最近 user/assistant message 的 timestamp。
- 已生成的 anchor JSONL。

输出示例:

```text
Temporal spine:
- 18:00-19:00 Discussed temporal memory architecture.
- 19:48-21:03 Idle gap.
- 21:03 Resumed discussion about long-session time awareness.
```

触发规则:

- 跨整点。
- 消息间隔超过 15/30/60 分钟。
- 用户提出新需求、约定、偏好、重要判断。
- 出现情绪强度较高或关系状态变化的互动。
- 达成重要架构决策。

### 4.3 Event Anchor Store

事件锚点先写入本地结构化文件，不直接写长期记忆。

建议路径:

```text
~/.hermes/memory_anchors/YYYY-MM-DD.jsonl
```

记录格式:

```json
{
  "id": "sha256(session_id:message_id:anchor_type)",
  "ts": 1778754180.123,
  "timezone": "Asia/Shanghai",
  "session_id": "20260514_180200_xxxxxx",
  "source_message_ids": [123, 124],
  "type": "decision",
  "summary": "Decided to replace 5-minute time observer with ephemeral temporal context.",
  "tags": ["architecture", "memory", "time"],
  "salience": 0.82,
  "privacy": "normal",
  "ttl": null,
  "write_to_long_term": false,
  "created_by": "anchor-extractor-v1"
}
```

字段含义:

- `id`: 幂等去重，重复运行不会重复写入。
- `ts`: 原始事件发生时间。
- `type`: `decision | preference | plan | emotion | relationship | architecture | open_loop`。
- `salience`: 重要性评分。
- `privacy`: `normal | sensitive | private`。
- `write_to_long_term`: 是否允许进入 Honcho/MEMORY 的候选标记。

### 4.4 Anchor Extractor

Anchor Extractor 在每轮对话结束后运行。

推荐策略:

1. 规则先行:
   - 包含“记住”“以后”“下次”“约好”“决定”“方案”等关键词。
   - 当前消息与上一消息间隔超过阈值。
   - 用户明确提出偏好或纠正。
2. 小模型分类:
   - 只在规则命中时调用。
   - 输出结构化 JSON。
3. 本地写入:
   - 只写 anchor JSONL。
   - 不立即写 Honcho。

这样可以避免每轮都让大模型做重度记忆判断。

### 4.5 Night Sage

Night Sage 是每日维护任务，不是普通聊天 agent。

职责:

- 读取当天 messages 和 memory anchors。
- 合并重复事件。
- 生成小时级 temporal digest。
- 生成候选长期记忆。
- 标记 open loops。
- 输出本地审计文件。

建议输出路径:

```text
~/.hermes/daily_summaries/YYYY-MM-DD.md
~/.hermes/daily_summaries/YYYY-MM-DD.candidates.json
~/.hermes/night_sage/state.json
```

`state.json` 用来记录处理水位:

```json
{
  "last_processed_ts": 1778759999.0,
  "last_run_at": "2026-05-15T03:00:12+08:00",
  "version": "night-sage-v1"
}
```

Night Sage 的写入策略:

- v1 阶段只写本地摘要，不写 Honcho。
- v2 阶段只把高置信、低隐私、高价值结论写入 Honcho conclusions。
- 不把原始对话、重复摘要、亲密细节原文写入长期记忆。

## 5. Honcho 分工

当前 Honcho 适合继续承担:

- 原始 turn/session 同步。
- 语义搜索。
- 用户表示和关系表示。
- 通用结论维护。

Night Sage 不重复做:

- 不重放原始消息。
- 不重复生成泛泛摘要。
- 不批量灌入和 Honcho deriver 类似的观察。

Night Sage 只补充:

- 时间脊柱。
- 每日审计摘要。
- open loops。
- 高价值候选结论。
- 隐私和去重控制。

如果 Honcho 已经能稳定召回某类信息，Night Sage 不再写入同类长期记忆。

## 6. Cron 与调度

不再使用 5 分钟 Time Observer Cron Job。

原因:

- Cron session 是独立 fresh session，不能热更新活跃对话上下文。
- 5 分钟 LLM run 成本高且信息价值低。
- 写 `current_time.md` 不等于模型能自动读取。

保留的调度任务:

```text
0 3 * * * run night_sage.py
```

更可靠的执行方式:

- systemd timer: 稳定、独立于 Hermes gateway。
- Hermes cron: 可用，但要求 gateway 持续运行。

如果使用 Hermes cron，建议让 script 做主要工作，agent 只负责调度或静默返回。

## 7. 上下文注入策略

每轮模型调用前动态构造:

```text
<temporal-context>
Current Beijing time: 2026-05-14 21:03 Asia/Shanghai
Conversation elapsed: 3h01m
Last user message: 1h16m ago
Last assistant reply: 1h15m ago
Significant gap: yes
Recent anchors:
- 18:00-19:00 Discussed Hermes time awareness design.
- 21:03 Continued long-session time gap discussion.
</temporal-context>
```

预算控制:

- 默认上限 600 字符。
- 最多 3 条 recent anchors。
- 只在长间隔或跨小时后显示 gap 信息。
- 不注入全量历史。

## 8. 工程落地计划

### Phase 0: 配置修正

- 设置 `timezone: Asia/Shanghai`。
- 保持 Honcho 启用。
- 明确 Honcho recall mode，优先从 `tools` 或 `hybrid` 中选择。

### Phase 1: Runtime Temporal Context

实现一个 temporal context builder:

- 获取当前时间。
- 查询当前 session 的 started_at。
- 查询最近 user/assistant timestamp。
- 判断 idle gap。
- 输出短文本块。

要求:

- 不修改历史 messages。
- 不写长期记忆。
- 不影响静态 system prompt cache。

### Phase 2: Event Anchor Store

新增 anchor JSONL 写入:

- after-turn hook 或 memory provider hook。
- 规则触发。
- 幂等写入。
- 本地可审计。

### Phase 3: Night Sage 本地摘要

新增 `night_sage.py`:

- 读取 `state.db`。
- 读取 anchor JSONL。
- 输出 daily summary 和 candidate memories。
- 记录 watermark。

### Phase 4: Honcho 候选写入

在观察 3-7 天后再开启:

- 只写高价值 candidates。
- 对敏感内容默认不写。
- 每条写入带来源和日期。
- 避免与 Honcho 原生 deriver 重复。

## 9. 风险与控制

### 9.1 上下文膨胀

控制方式:

- 当前时间覆盖式注入，不累计。
- Temporal context 字符数硬限制。
- 只保留最近几个锚点。

### 9.2 记忆污染

控制方式:

- Night Sage 先本地审计。
- 长期写入默认关闭。
- 敏感内容只保留抽象标签，不保留原文。

### 9.3 重复 Honcho

控制方式:

- 不重放原始对话。
- 不写泛泛摘要。
- 只写 Honcho 缺失且稳定有用的结论。

### 9.4 时间错觉

控制方式:

- 所有 timestamp 存 epoch + timezone。
- 对模型展示使用北京时间。
- 显示 `about 1h16m ago` 这种自然语言间隔。

### 9.5 Cron 可靠性

控制方式:

- 对必须稳定执行的 Night Sage 使用 systemd timer。
- Hermes cron 仅作为可选调度方式。
- 任务必须幂等，可重复运行。

## 10. v1.1 总结

v1.1 的核心变化是把“时间流水”改成“时间脊柱”。

小雅不需要每 5 分钟记一次钟表。她需要:

- 每次说话前看一眼现在几点。
- 知道上次说话距现在多久。
- 记得今晚几个关键阶段发生了什么。
- 夜里把当天的碎片整理成少量可审计的锚点。

最终架构:

```text
Current Time -> Ephemeral Time Context
Message Timestamps -> Temporal Spine
Important Turns -> Event Anchors
Daily Maintenance -> Night Sage Summary
Long-Term Recall -> Honcho / MEMORY
```

这样既保留“现在、过去、间隔、叙事”的时间感，又避免 token 膨胀、cron 误用和长期记忆污染。

## 11. 上游调查与工程评估

调查日期: 2026-05-14

调查范围: 公开的 `NousResearch/hermes-agent` issue / PR。当前 workspace 只有本设计文档，没有 Hermes 源码 checkout，因此以下判断基于公开页面和 PR 描述。

### 11.1 上游相关进展

结论: 上游确实已经围绕“agent 时间感弱”形成了一组 issue/PR，而且主线方向与本方案的 Phase 1 高度一致: 稳定 cached system prompt，实时 current time 走每轮 ephemeral user-message/runtime context，不写入长期记忆，也不通过 gateway 私有 timestamp 前缀制造第二套机制。

强相关项:

- [#10421 Turn-level live time context for current date/time awareness](https://github.com/NousResearch/hermes-agent/issues/10421): open。明确指出 Hermes 只有 session-level 时间，没有可靠 turn-level “now/today/current weekday/current local date”。这是本方案“当前时间不是记忆，每轮动态注入”的直接上游问题陈述。
- [#15872 fix: prevent stale timestamp perception by injecting current time per-turn](https://github.com/NousResearch/hermes-agent/pull/15872): open，已获正向 review。核心做法是把 `Session started` 留在稳定 system prompt，把 `Current time` + timezone 每轮注入 user message / plugin context 路径，避免 system prompt cache 失效。它还覆盖了 max-iterations 和 codex responses 路径，并从 [#18135](https://github.com/NousResearch/hermes-agent/pull/18135) 吸收了集中格式化 helper 的思路。
- [#18135 fix: add per-turn current time context](https://github.com/NousResearch/hermes-agent/pull/18135): open。提供 centralized helper、idempotent 注入、multimodal user content 支持，以及“不污染 persisted transcripts/resumed history/trajectories”的约束。适合吸收到本设计的工程细节里。
- [#17476 Consolidate live-time PRs around one ephemeral runtime context path](https://github.com/NousResearch/hermes-agent/issues/17476): open。明确要求把 live time PR 收敛成一个核心 ephemeral runtime context path，避免 system prompt 和 gateway prefix 多头并进。
- [#17459 Rework quiet-hours/time awareness](https://github.com/NousResearch/hermes-agent/issues/17459): open。更大的架构原则是“把当前时间、timezone、contact window 暴露给 agent/tool，而不是让 control plane 静默拦截或改写行为”。这支持本方案对 cron/调度的边界划分。
- [#15866 Question: does minute-precision timestamp in _build_system_prompt invalidate prompt caching](https://github.com/NousResearch/hermes-agent/issues/15866): open。记录了 system prompt 中分钟级时间戳导致 prefix/KV cache 反复失效的问题，是本方案避免把 volatile time 放进 system prompt 的关键证据。
- [#5487 feat(gateway): inject current timestamp into user messages](https://github.com/NousResearch/hermes-agent/pull/5487): open，但被维护者评论为应由 [#17459](https://github.com/NousResearch/hermes-agent/issues/17459)/[#17476](https://github.com/NousResearch/hermes-agent/issues/17476) supersede。它证明需求真实，但 gateway-only timestamp prefix 不应成为最终主线。
- [#10448 fix(agent): inject turn-level live time context](https://github.com/NousResearch/hermes-agent/pull/10448) 和 [#5241 feat: inject current time into system prompt on every API call](https://github.com/NousResearch/hermes-agent/pull/5241): 都解决同类问题，但把 live time 放进 system prompt 或 turn-scoped system prompt，已被讨论为 cache 风险更高的路线。可借鉴测试覆盖，不宜照搬注入层。

相邻项:

- [#10061 fix(timezone): propagate configured timezone to agent prompt and terminals](https://github.com/NousResearch/hermes-agent/pull/10061): open。后来收敛为 terminal/code execution 的 `TZ` 传播，不再把 timezone 塞进 cached system prompt。对本方案的 `timezone: Asia/Shanghai` 和工具时间一致性很重要。
- [#24664 fix(hermes_time): eliminate TOCTOU race in get_timezone()](https://github.com/NousResearch/hermes-agent/pull/24664): open。修复 `hermes_time.get_timezone()` 冷启动并发 race，说明 temporal context builder 应依赖线程安全、timezone-aware 的时间源。
- [#8689 perf: stabilize system prompt timestamp across compression cycles](https://github.com/NousResearch/hermes-agent/pull/8689): open。与本方案相容: session-start anchor 可稳定，current-time 仍走 ephemeral context。
- [#13058 fix(tools): add session_recap for time-window conversation summaries](https://github.com/NousResearch/hermes-agent/pull/13058): open。提供 time-window first 的 session recap 能力，能支撑“昨天 2 点到 4 点聊了什么”这类时间召回，但它是按需工具/检索能力，不等同于每轮都注入 temporal spine。
- [#625 Structured Temporal Memory with Confidence-Gated Facts](https://github.com/NousResearch/hermes-agent/issues/625): open。提出层级 temporal memory、confidence facts、debounced queue、token-aware injection。与本方案的 Event Anchor / Night Sage 在方向上相似。
- [#2398 feat(memory): structured facts with confidence gating and token-aware injection](https://github.com/NousResearch/hermes-agent/pull/2398): closed。实现 [#625](https://github.com/NousResearch/hermes-agent/issues/625) Phase 1，但维护者关闭理由是复杂度高、用户问题不够具体。这是本方案需要克制 Night Sage / anchor 写入范围的重要反例。
- [#17474](https://github.com/NousResearch/hermes-agent/issues/17474) / [#17548](https://github.com/NousResearch/hermes-agent/pull/17548): tool runtime time advisory 曾被提出并实现 helper，但后续关闭为 not planned / speculative。说明 tool-time advisory 的设计是合理形状，但应在有具体 tool caller 时再落地。

### 11.2 对本方案的工程可行性判断

总体判断: Phase 1 可行且值得优先做；Phase 2 可行但要严格限流和本地化；Phase 3/4 需要谨慎试运行，不能一开始就做成自动长期记忆系统。

分阶段评估:

1. Phase 1 Runtime Temporal Context: 低风险，高收益。上游 [#15872](https://github.com/NousResearch/hermes-agent/pull/15872)、[#18135](https://github.com/NousResearch/hermes-agent/pull/18135)、[#17476](https://github.com/NousResearch/hermes-agent/issues/17476) 都验证了这个方向。关键是注入到 API-facing user/runtime context，而不是 cached system prompt；同时确保 persisted transcript、resumed history、trajectory 不保存这段合成时间。
2. Phase 2 Event Anchor Store: 中等风险。JSONL anchor store、幂等 id、source message ids、privacy、ttl 都是合理设计；但 hot path 不应每轮调用 LLM。建议第一版只做规则锚点和 idle-gap anchor，LLM 分类放到后台 debounce 或 Night Sage。
3. Phase 3 Night Sage 本地摘要: 中等风险，可作为本地审计层落地。它的价值在于生成 daily digest、open loops、候选结论，而不是重复 Honcho 的原始 deriver。第一版只写本地文件是正确边界。
4. Phase 4 Honcho 候选写入: 高风险，应默认关闭。上游 [#2398](https://github.com/NousResearch/hermes-agent/pull/2398) 被关闭说明结构化记忆一旦直接进入长期系统，很容易增加复杂度和污染面。建议必须有人工可审计队列、去重检查和回滚/删除能力后再开。

### 11.3 当前设计的主要不足

1. 注入点还不够具体。文档说“不追加到 messages 历史中”“放在 runtime context 区”，但 Hermes 真实实现中需要明确是 `_plugin_user_context`、provider adapter 的 user-message injection，还是某个新的 context middleware。还要写清楚 synthetic time block 在 transcript/resume/trajectory 中如何剥离。
2. temporal context 与 prompt cache 的不变量需要测试化。必须有测试证明 cached system prompt 不包含 `Current time:`，连续两轮 system prompt byte-stable，而 user/runtime context 的 current time 会更新。
3. Temporal Spine 的生成策略偏抽象。需要定义从 `state.db` 查询哪些字段、如何处理 parent/child session、压缩后如何排序、跨天如何截断，以及最多注入多少条。否则容易退化成小型历史摘要系统。
4. anchor 提取触发过宽。“用户提出新需求、情绪强度、关系变化”等条件容易误抓私人对话。需要 first-party consent、敏感类型默认本地不外写、可删除、可查看，以及更保守的 salience 阈值。
5. Night Sage 与 Honcho 的边界还需要接口契约。文档说“不重复 Honcho”，但没有定义如何检测 Honcho 已经稳定召回某类信息，也没有候选写入 schema、去重 key、source provenance、撤销路径。
6. 缺少失败模式设计。比如 `state.db` 锁冲突、timezone 配置非法、JSONL 半行损坏、Night Sage 中断、systemd timer 重入、跨 DST/夏令时、服务器时钟漂移，都需要降级策略。
7. 配置面需要收窄。`timezone: Asia/Shanghai` 是必要项；但 anchor 阈值、token budget、Night Sage schedule、long-term write 开关、privacy policy 如果都暴露，会让早期版本难以维护。建议先用少量保守默认值。
8. “当前北京时间”需要和“用户本地时间”区分。对阿峰可以默认 Asia/Shanghai，但 Hermes 若面向多用户/多 profile，context 应写成 user/profile timezone，而不是硬编码 Beijing time。
9. 缺少可观测性。上线后要知道每轮是否注入、注入字符数、最近 message timestamp 来源、anchor 生成数量、Night Sage 处理水位和跳过原因。

### 11.4 建议改进版落地路径

建议先把方案拆成一个更小的 v1.2:

1. 只实现 `build_temporal_context(session_id, now)`。
   - 输出 current time、timezone、session started、last user/assistant delta、significant gap。
   - 上限 400-600 字符。
   - 注入 API-facing user/runtime context。
   - 不写入 messages、Honcho、MEMORY、trajectory。
2. 加测试先行的不变量。
   - current time 不在 cached system prompt。
   - 两轮 system prompt byte-stable。
   - 两轮 runtime context 时间变化。
   - resumed session 不把旧 synthetic block 带回来。
   - timezone config.yaml 和 env var 都能覆盖。
3. Temporal Spine 先只做 deterministic idle-gap spine。
   - `gap >= 15m` 生成 idle gap line。
   - `gap >= 60m` 才注入显著间隔提示。
   - 只读 message timestamps，不调用 LLM。
4. Event Anchor Store 先做本地规则锚点。
   - 只记录 explicit decision / preference / plan / open_loop。
   - 不记录 emotion / relationship，除非用户明确要求记住。
   - JSONL 写入采用 temp + atomic append/rename 或 sqlite 表，避免并发半写。
5. Night Sage 作为离线审计，不作为记忆写入器。
   - 先输出 `daily_summary.md` 和 `candidates.json`。
   - 运行 3-7 天观察噪音率。
   - 只有人工确认或严格 allowlist 后才进入 Honcho conclusions。
6. 工具时间 advisory 暂缓。
   - 等 email/calendar/wait/scheduler 这类具体 tool 需要时，再按 [#17459](https://github.com/NousResearch/hermes-agent/issues/17459) 的原则接入。
   - 不提前引入无 caller 的 helper，避免重复 [#17548](https://github.com/NousResearch/hermes-agent/pull/17548) 的问题。

### 11.5 推荐结论

本设计的核心方向是对的，尤其是“当前时间不是记忆”“不用 5 分钟 cron 写 clock ticks”“Night Sage 先本地审计”这三点，和上游收敛方向一致。

最应该加强的是工程边界: Phase 1 要尽快做成一个 cache-safe、transcript-clean、timezone-aware 的 runtime context 注入；Phase 2/3 要从 deterministic、本地、可删、可审计开始；Phase 4 长期记忆写入应继续默认关闭。这样可以先解决用户可感知的“现在几点、隔了多久”的问题，同时不把 Hermes 推向复杂、昂贵、难回滚的自动记忆系统。
