# opencode router-standard（v4flash 版）设计文档

- **日期**: 2026-08-16
- **状态**: 已评审通过
- **背景**: 用户安装了 DSH 的 dsh-routing-suite（injector + router-standard 预设），但该套件是 DSH (DeepSeek Harness) 的 cordis 插件体系，无法在 opencode 中运行。本设计用 opencode 原生机制（agent 文件 + Task 分派 + prompt 内嵌锚定）复刻 router-standard 的核心能力，目标模型为 `opencode/deepseek-v4-flash-free`（免费）。

## 1. 目标

在 opencode 中提供一个纯 v4flash 的「任务感知路由」主代理，复刻 dsh router-standard 的三大能力：

1. **三行为带路由**：spec（计划）/ react（执行）/ weak（模型自分类）
2. **按模型选 persona**：Flash = neutral persona + classify 路由（few-shot 分类指令）
3. **三锚定**：回顾 + 收敛 + 反跑题（persona 静态锚，内嵌各代理 prompt）

## 2. 架构

```
用户 ──> router-standard (primary, v4flash)
              │  每轮先分类（neutral + classify，few-shot）
              ├─ spec 带 ──> Task ──> spec-planner  (subagent, v4flash)  计划/方案/任务分解
              ├─ react 带 ─> Task ──> react-executor (subagent, v4flash) 直接执行
              ├─ weak 带 ──> 自己处理（快速问答/证据不足/闲聊）
              └─ mixed 陷阱 ──> 先 spec 拆解，再 react 执行
```

### 2.1 组件

| 文件（全局 `~/.config/opencode/agents/`） | 模式 | 模型 | 职责 |
|------|------|------|------|
| `router-standard.md` | primary | `opencode/deepseek-v4-flash-free` | 每轮先分类（few-shot），按带分派；weak 带自己答；mixed 先 spec 后 react |
| `spec-planner.md` | subagent | 同上 | 只出计划：目标复述 → 步骤分解 → 依赖/风险 → 验收标准。**不执行** |
| `react-executor.md` | subagent | 同上 | 直接执行：按 spec 动手，保持改动最小，完成后报 文件+验证命令+结果 |

### 2.2 数据流

1. 用户消息 → router-standard 先做分类判断（spec/react/weak/mixed）
2. spec 带：Task(spec-planner) → 返回计划 → router 汇总给用户；如用户要求执行，再 Task(react-executor)
3. react 带：Task(react-executor) → 返回改动报告 → router 向用户汇报
4. weak 带：router 直接回答（neutral persona，不自作主张分派）
5. mixed：先 spec-planner 拆解，计划确认后再 react-executor 执行

### 2.3 三锚（内嵌每个代理 prompt）

- **回顾 (recall)**：响应前先复述任务目标与当前进度
- **收敛 (converge)**：输出只围绕任务，不展开无关内容
- **反跑题 (anti-runaway)**：检测偏离立即拉回；开放任务主动收敛到可交付结果

react-executor 的「反跑题」锚定最强（执行带是跑题高发区）。

## 3. 边界与非目标（YAGNI）

- **不做** chat.params 自动路由插件（纯 prompt 层路由，可预期可调试）
- **零侵入**：不修改 project-manager / deepseek-executor / visual-luna / default_agent
- **不建** skill 文件；三锚直接内嵌 prompt
- **不改** opencode.json / opencode.jsonc

## 4. 使用方式

- 切换：opencode 内 agent 选择器切到 `router-standard`，或命令行 `opencode --agent router-standard`
- terra 双轨入口（project-manager）原样保留

## 5. 验证（成功标准）

1. **分类测试**：抛「计划型」（设计一个模块）、「执行型」（修 bug）、「闲聊型」任务，观察正确分派/自处理
2. **三锚测试**：抛开放任务（如「帮我改进这个项目」），观察收敛到交付物、不跑题
3. **回归测试**：project-manager / deepseek-executor 行为不变（未改动，抽查即可）

## 6. 交付物

- `~/.config/opencode/agents/router-standard.md`
- `~/.config/opencode/agents/spec-planner.md`
- `~/.config/opencode/agents/react-executor.md`

> 注：本设计文档存放于 workspace（decisionvault），交付物在全局 opencode 配置目录。