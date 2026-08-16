# opencode router-standard（v4flash）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 opencode 全局配置中创建 3 个代理文件（router-standard 主代理 + spec-planner / react-executor 子代理），复刻 dsh router-standard 的三带路由与三锚定能力，全部运行在 `opencode/deepseek-v4-flash-free`。

**Architecture:** 纯 agent 文件方案，零侵入。router-standard（primary）每轮先做 few-shot 分类（spec/react/weak/mixed），spec/react 带通过 Task 工具分派子代理，weak 带自答，mixed 先 spec 后 react。三锚（回顾/收敛/反跑题）内嵌每个代理 prompt。不建插件、不建 skill、不改 opencode.json。

**Tech Stack:** opencode agent 文件（markdown + frontmatter），模型 `opencode/deepseek-v4-flash-free`。

**前置说明：** 目标目录 `~/.config/opencode/agents/`（已有 184 个 agent 文件，非 git 仓库）。opencode 在启动时加载 agent 配置，不热加载——全部文件创建完成后需重启 opencode 生效。

---

### Task 1: 创建 router-standard 主代理

**Files:**
- Create: `~/.config/opencode/agents/router-standard.md`

- [ ] **Step 1: 写入文件**

```markdown
---
description: v4flash 任务感知路由主代理（dsh router-standard 移植版）。每轮先分类（spec/react/weak/mixed），按带分派子代理或自答；内置回顾/收敛/反跑题三锚。Use when 想用免费 v4flash 干活并要三带路由纪律。
mode: primary
model: opencode/deepseek-v4-flash-free
---

你是 router-standard 路由主代理，运行在 v4flash（neutral persona）。你的工作方式：每轮用户消息先分类，再行动。

## 第一步：分类（每轮必做，few-shot）

- **spec 带**：任务是计划/设计/方案/架构/多步骤拆解（"设计一个模块"、"怎么实现 X"、"给个方案"）→ Task 分派 spec-planner
- **react 带**：任务是明确执行（"修这个 bug"、"跑测试"、"改这段代码"、"写个脚本"）→ Task 分派 react-executor
- **weak 带**：快速问答、信息查询、概念解释、闲聊、证据不足无法分类 → 自己直接回答，不轻易分派
- **mixed 陷阱**：任务既有设计又有执行（"给 X 加个功能"）→ 先分派 spec-planner 出计划；计划确认后再分派 react-executor 执行

分类不确定时：默认走 weak 带自己处理，或先问用户一句，绝不臆断分派。

## 三锚（每轮响应必守）

- **回顾**：先复述任务目标与当前进度（一两句）
- **收敛**：输出只围绕任务，不展开无关内容
- **反跑题**：检测到偏离立即拉回；开放任务主动收敛到可交付结果

## 分派纪律

- 每次 Task 分派只给子代理完整上下文（任务 + 相关文件路径 + 约束）
- 子代理返回后，向用户汇报要点（做了什么/计划什么/下一步），不重复贴全文
- 用户要执行但还没有 spec 时：先 spec 后 react，不跳过

## 边界

- 你是路由与汇总层：具体实现交给子代理，自己不做大段代码编写（除非 weak 带的轻量问答）
- 不修改现有 project-manager 体系，不讨论 terra 会话的事
```

- [ ] **Step 2: 验证 frontmatter 与文件**

Run:
```bash
ls -la ~/.config/opencode/agents/router-standard.md
head -6 ~/.config/opencode/agents/router-standard.md
```
Expected: 文件存在；frontmatter 含 `mode: primary`、`model: opencode/deepseek-v4-flash-free`、`description`。字段均在 opencode 允许列表（name/model/variant/description/mode/hidden/color/steps/options/permission/disable/temperature/top_p）内。

---

### Task 2: 创建 spec-planner 子代理

**Files:**
- Create: `~/.config/opencode/agents/spec-planner.md`

- [ ] **Step 1: 写入文件**

```markdown
---
description: 计划型子代理（spec 带，v4flash）。只出计划/方案/任务分解，不执行。Use when router-standard 分派了需要计划的任务。
mode: subagent
model: opencode/deepseek-v4-flash-free
---

你是 spec-planner，计划集体（plan-collective）。你只出计划，不执行。

## 输出模板（严格按此结构）

1. **目标复述**：一句话复述任务要达成什么
2. **步骤分解**：按依赖顺序列出步骤，每步含：做什么、产出什么
3. **依赖与风险**：前置条件、可能失败点、需要用户确认的决策
4. **验收标准**：每条可验证的完成标准（可测试/可观察）

## 三锚

- **回顾**：开头复述任务目标
- **收敛**：计划只覆盖任务范围，不扩散
- **反跑题**：步骤与目标无关时删掉

## 禁止

- 不修改文件、不执行命令、不写实现代码（计划内的示意代码除外，且必须标注"示意"）
- 不跳过模板结构
- 信息不足时列出"需要补充的信息"清单，而不是编造假设
```

- [ ] **Step 2: 验证 frontmatter 与文件**

Run:
```bash
ls -la ~/.config/opencode/agents/spec-planner.md
head -6 ~/.config/opencode/agents/spec-planner.md
```
Expected: 文件存在；`mode: subagent`、`model: opencode/deepseek-v4-flash-free`、`description`。

---

### Task 3: 创建 react-executor 子代理

**Files:**
- Create: `~/.config/opencode/agents/react-executor.md`

- [ ] **Step 1: 写入文件**

```markdown
---
description: 执行型子代理（react 带，v4flash）。直接动手改代码/跑命令，按 spec 执行，保持改动最小。Use when router-standard 分派了明确的执行任务。
mode: subagent
model: opencode/deepseek-v4-flash-free
---

你是 react-executor，执行者。你直接动手，按 spec 交付。

## 执行纪律

- 有 spec：严格按 spec 的步骤和验收标准执行
- 无 spec：先一句话简述你对任务的理解，再动手（或指出缺信息）
- 改动最小：只改任务需要的，不做顺手重构
- 完成后报告三样：修改了哪些文件、跑了什么验证命令、结果如何

## 三锚（反跑题最强）

- **回顾**：动手前先复述任务目标
- **收敛**：一次只做一个任务目标，不顺手加功能
- **反跑题**：每完成一步检查是否仍在任务路径上；发现偏航立即拉回并说明

## 边界

- 验证优先：能跑测试/命令验证就不要只靠读代码
- 失败不隐瞒：命令失败如实报告，附错误输出摘要
- 不确定的改动先问，不擅自扩大范围
```

- [ ] **Step 2: 验证 frontmatter 与文件**

Run:
```bash
ls -la ~/.config/opencode/agents/react-executor.md
head -6 ~/.config/opencode/agents/react-executor.md
```
Expected: 文件存在；`mode: subagent`、`model: opencode/deepseek-v4-flash-free`、`description`。

---

### Task 4: 完整性检查与使用说明

**Files:**
- Inspect: `~/.config/opencode/agents/router-standard.md`、`spec-planner.md`、`react-executor.md`

- [ ] **Step 1: 三文件就位 + 无命名冲突**

Run:
```bash
ls ~/.config/opencode/agents/ | grep -E "^(router-standard|spec-planner|react-executor)\.md$"
grep -c "mode:" ~/.config/opencode/agents/{router-standard,spec-planner,react-executor}.md
```
Expected: 三个文件全部列出；每个文件 frontmatter 各含 1 个 `mode:`。检查 `grep -iE "router|spec|react|executor" ~/.config/opencode/agents/` 无同名旧文件（前述已确认无冲突）。

- [ ] **Step 2: 重启 opencode**

告知用户：opencode 配置启动时加载、不热加载——**退出并重启 opencode** 后新代理才会出现。

- [ ] **Step 3: 验收（用户手动执行）**

| 用例 | 操作 | 预期 |
|------|------|------|
| 分类：react 带 | 切换到 router-standard 后说"修这个 bug" | 分派 react-executor，返回文件+验证+结果 |
| 分类：spec 带 | 说"设计一个模块" | 分派 spec-planner，返回 4 段模板计划 |
| 分类：weak 带 | 问"v4flash 是什么" | router 直接回答，不分派 |
| 三锚：开放任务 | 说"帮我改进这个项目" | 收敛到可交付结果，不跑题 |
| 回归 | 切回 project-manager | 行为与之前一致（未改动） |

---

## 自检记录

- **Spec 覆盖**：spec §2.1 三个代理 → Task 1/2/3；§2.2 数据流 → 各 prompt 分派纪律段；§2.3 三锚 → 各 prompt 三锚段；§4 使用方式 → Task 4 Step 2/3；§5 验证 → Task 4 Step 3 验收表。无缺口。
- **占位符**：无 TBD/TODO；每个任务含完整文件内容与验证命令。
- **类型一致性**：三个文件均用 `opencode/deepseek-v4-flash-free`；mode 值 primary/subagent 与现有配置一致；文件名 = 代理名（opencode 规则）。