# Phase 2A M4 机会审计 —— Phase 2C 保真修复后的勘误记录

## 0. 性质与范围

| 项 | 值 |
| --- | --- |
| 类型 | **ERRATUM / 文档勘误**（文档级最小修订） |
| Owner / reviewer | M4 / M1 |
| 触发源 | `docs/phase2b-m6-experimental-fidelity-repair-spec.md`、`docs/phase2c-m6-workload-reuse-audit.md`、Phase 2C 原生 pilot（PR #40） |
| 被修订文档 | `docs/phase2a-m4-method-opportunity-audit.md`（rev.3） |
| 附带标注 | `docs/phase2a-h1-h2-closeout-verdict-record.md` §1.6（仅口径澄清） |
| 新实验 | **无** |
| 新观测缝请求 | **无** |
| 策略 / runtime 实现授权请求 | **无** |
| 统计重算 | **无** |

⚠️ **本勘误不重开任何已封存的 campaign，不改判任何 verdict，不重写原始结果，不选择性重跑，
也不据新 pilot 声称任何 Cost-Aware 方法有效或无效。** 它只修正本审计**自身**的四处证据等级表述、
一处机会前置条件，以及一处论据替换。

### 0.1 归因与时序（诚实记录）

勘误不该被读成「M4 之前写错了」。时间线核实如下：

```text
2026-10-10  25f05d2  audit rev.2（含 h1/h2 closeout）
2026-10-11  40d418f  audit rev.3（M1 四点修订）
2026-10-11  e2b2e31  audit rev.3b（HYP-C / F-D1 口径对齐）
2026-10-12  b6e9f29  Phase 2B 保真修复 spec 首次入库   <- 晚于 rev.3 一天
2026-10-12/13         Phase 2C 历史审计与原生 pilot
```

⇒ Phase 2B spec 对四类缺陷（`F-PREFIX` / `F-ARRIVAL` / `F-HISTORY` / `F-PRESSURE`）的**正式定位**
出现在本审计 rev.3 **之后**。因此：

- **归因性质：信息到达时序**，不是 rev.3 与既有证据的矛盾；
- 但可诚实指出一处**范围缺口**：rev.3 §4.1 已意识到 `block_id` 是槽位而非内容身份，
却仅停在「不能单独排除」的让步上，**未进一步核查跨 program 共享在构造上是否可能**。
该核查当时即可从 `phase2_h1_compiler.py` 与 `scripts/spikes/phase2_minimal_observability_metal.py` 读出。
本勘误补做该核查，并据此收紧表述。

---

## 1. 四类缺陷 → 本审计被命中的章节

| 缺陷 ID | 实际含义 | 命中章节 | 处置 |
| --- | --- | --- | --- |
| `F-PREFIX` | 编译器用 `ownership_group` 复用**逻辑** `prefix_prompt`，后端 `_turn_token_ids()` → `_program_prefix_token_ids(program_id)` 按 program 生成真实 token，**共享身份被忽略** | §2.7、§3.2、§4.1、§4.3、§4.4、§5.2 | 修订 2 处 + 升级 1 处 + 替换 1 处论据 |
| `F-HISTORY` | 逐候选采样值停留在 `trace_derived_proxy_inputs`，runtime TTL 从历史估计器读取 | §2.9 | 改因果措辞 |
| `F-PRESSURE` | logical release / native hashed eviction / 后续 APC 属不同事件层 | §2.7、F-C1 | 补受控佐证，结论强化 |
| `F-ARRIVAL` | 同步逐请求 `execute`，从未真实并发 | §2.9、discovery 退化读法 | 记录，无需改结论 |

### 1.1 核实命令（可复现）

```powershell
# 两语料对应提交的后端实现均含按 program_id 生成 token 的函数
git show 6023c66:scripts/spikes/phase2_minimal_observability_metal.py   # discovery 语料
git show e3a02fd:scripts/spikes/phase2_minimal_observability_metal.py   # H1 语料
# 两者均命中: def _program_prefix_token_ids(...) digest = sha256(program_id)
```

---

## 2. 五处修订

### 2.1 §3.2 标题与论据 —— 删除「第二次独立实例」

| | 内容 |
| --- | --- |
| 原文 | `### 3.2 [事实] 定向发现不可迁移（第二次独立实例）` |
| 现文 | `### 3.2 [事实] 定向发现不稳定（同源重复，非独立验证）` |

**理由**：两份语料出自**同一条内容构造代码路径**，`F-PREFIX` 在两边都成立，
且在 `F-ARRIVAL` / `F-HISTORY` 上同样退化：

```text
不同 program 首请求 native hash 链 : 0/771 相等        <- 跨 program 内容重叠恒为 0
同 program 首 -> 次 hash 链        : 408/408 相同
同 program 首 -> 所有后续 hash 链   : 495/495 相同
```

⇒ 两者**不是独立对照**。观测（`code` → `database`、reverse-deadline 由正转负）**仍然成立**，
但「迁移检验失败」的读法**缺乏依据**。

**修订结论**：构成「**同一生成族内重复方向不一致**」⇒ 该方向**不稳定**，
而**不是**「跨内容制度不可迁移」。

⚠️ **结论方向不变**：G1 本来即禁止以 H1 验证其启发的假设，discovery 方向性结论**同样不得作为先验**。

### 2.2 §2.7 追加受控压力佐证

新增 §2.7.1。Phase 2C `W-PRESSURE` 配对在**同一 native hash 进程内**：

| 臂 | `eligible` | `native_cached` | 结果 |
| --- | ---: | ---: | --- |
| 无压力 | 384 | **384** | `FULL_HIT` |
| 受控原生分配 | 384 | **256** | `PARTIAL_HIT` |

两臂**提交内容完全相同**、仅物理驻留不同 ⇒ **partial hit 可由该 entry 自身驻留独立产生**。

⇒ §2.7 的谨慎表述**被强化**（非修改）：§2.7 的「每 reclaimable block 实际重算量 0.6667–16.0000（24× 离散）」
应读作**驻留 artifact**，**不是**内容重叠 artifact。

### 2.3 §2.9 因果措辞 —— 接线缺口，非设计遗漏

| | 内容 |
| --- | --- |
| 原文 | 「H1 修正了成本分辨率……但**未**修正 TTL `benefit` 项的退化。」（易读成 M6 遗漏采样） |
| 现文 | 补 `F-HISTORY` 成因：**采样已发生，但未接入 runtime TTL 输入路径** |

⇒ 工程接线问题。**不改变** G5 裁定（记录为本轮 H1 实验限制，不因此重开 H1）。

### 2.4 §4.1 / §5.2（HYP-B）—— 从「不能排除」收紧为**构造排除**

| | 内容 |
| --- | --- |
| 原文 | 「上述 block-ID 结果**不能单独排除**跨 entry 重叠……跨 entry 重叠在本语料中**未被观测到**，也未证明存在因果机制」 |
| 现文 | 「跨 entry 内容重叠在 H1 语料中**被构造排除（structurally precluded）**，不是未被观测到。HYP-B 的前提在本语料中**从未被实例化**」 |

**理由**：0/771 是**确定性结构事实**，根因是 `F-PREFIX`。

⇒ HYP-B 证据等级由「未验证」改为「**本语料不可检验**」，理由为**设计缺陷而非实验证否**。

⚠️ **HYP-B 未被否定，也未被支持**；在具备真实内容拓扑的未来语料上仍可检验。

### 2.5 §4.3 机会三（共享所有权）—— 前置条件**降低**

| | 内容 |
| --- | --- |
| 原文 | 「要检验它，需一个 `relief < block_count` 存在的语料」 |
| 现文 | 根因为 `F-PREFIX`；新 schema（`W-XPROGRAM`）下**多所有者块在原理上已可表达**，所需改为「在现有 schema 上补一个 `relief` 观测」 |

**理由**：§2.2 的 `relief ≡ block_count` 100% 是**构造产物**（块在物理上从不被多所有者持有），
不是共享所有权的不存在。Phase 2C 分段内容 schema 下 `x-a` / `x-b` 提交同一段内容，
native APC 复用**同一批块** ⇒ 多所有者块**原理上已可表达**。

⇒ 这是修复带来的**唯一新增研究入口**，机会三的门槛显著下降。

⚠️ **仍是可行性判断，不是证据**：pilot **未测量** `relief`，且 `cost_aware_policy_authorized: false`。

---

## 3. **未**修订的章节（防止过度勘误）

| 章节 | 保持不变的理由 |
| --- | --- |
| §2.1 canonical loss 结构 | 单 entry 内 `I[返回] × C(prefix)`，与跨 entry 内容无关 |
| §2.2 三个量 | 单 entry 块记账；`relief ≡ block_count` 471/471 结论不变（原因见 §4.3） |
| §2.3 raw `C(r)/relief` 退化 | 依赖决策内成本特征与尺寸等价，与内容拓扑无关 |
| §2.4 native $C(r)$ U 形 | H2 隔离前向测量 |
| §2.5 deadline 关联弱 | 返回行为由 scenario 语法驱动 |
| §2.6 损失分解 32.5 / 17.5 / 45 / 5 | 成本=前缀长度、返回=指示器，两者均未变 |
| §2.8 特征判别力表 | 同上 |
| §3.1 三项排除 | 各有独立依据 |
| §3.3 瓶颈推断 | 为 `[推断]` 且已带不得写成确定机制的警告 |
| §4.2 机会二（返回因子） | 与内容拓扑无关；待 F-D1 口径澄清（Issue #37） |
| §5.1 原 HYP-A 否证 | 四项前置检查不依赖内容拓扑 |
| F-C1 / F-D1 结论 | `NOT_IDENTIFIABLE` 与「聚合口径不一致」均**被本次勘误强化**，未被推翻 |
| 结案记录 fidelity **120/120** | 该数字是 **replay 保真**（release set / sequence），**不是内容拓扑保真**；无冲突，**不改** |

---

## 4. 硬边界（与 Phase 2B spec §0 一致）

```text
不得将工程问题推导为历史结果必须改判。
```

- **不改判** H1/H2 任何 verdict；H1-R1 仍为 `DIAGNOSTIC_ONLY`；H2-M4 仍为 FAIL；
  H1/H2 仍 CLOSED，B1 仍 LOCKED；
- **不**据 Phase 2C pilot 声称 Cost-Aware 有效或无效 —— pilot 未实现、未评估任何策略；
- pilot 边界：`NON_HOLDOUT_NATIVE_PILOT`、`PARTIAL_HIT` 仅 **2** 例、`MISS = 0`、
  `attribution_scope: same_process_layered_temporal_sequence_only`、`review_status: M1_REVIEW_PENDING`；
- **不**请求新观测缝、**不**请求策略授权、**不**请求新 formal campaign；
- `G-TTL-HISTORY` **未升级**。

---

## 5. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| 四类缺陷定义与边界 | `docs/phase2b-m6-experimental-fidelity-repair-spec.md` §0、§0.1 |
| 不同 program 首链 0/771；同 program 408/408、495/495 | `docs/phase2c-m6-workload-reuse-audit.md`（archive SHA-256 `af5be5bd56a172f7945f12712289708aa55cda01f1b8c05a2bc3215b14c90af7`） |
| `F-PREFIX` 存在于两语料提交 | `git show 6023c66:scripts/spikes/phase2_minimal_observability_metal.py`；`git show e3a02fd:…` |
| 受控压力配对 384/384 vs 256/384 | `docs/phase2c-m6-native-pilot-result.json`（`pressure_pair`） |
| Phase 2C 拓扑与分段 schema | `configs/phase2/phase2c-native-pilot-cases-v1.json`、`configs/phase2/phase2c-workload-content-schema-v1.json` |
| Phase 2C 全 18 run PASS、APC 分布 22/16/2/0 | `docs/phase2c-m6-native-pilot-review-submission.md`、`docs/phase2c-m6-native-pilot-result.json` |
| spec 入库时序（`b6e9f29` 2026-10-12） | `git log --follow -- docs/phase2b-m6-experimental-fidelity-repair-spec.md` |
| rev.3 时序（`40d418f` 2026-10-11） | `git log --follow -- docs/phase2a-m4-method-opportunity-audit.md` |
| G1–G5 裁定 | M1，PR #36 review（2026-10-11） |

---

## 6. 验证证据

### 6.1 测试（证明未引入回归）

```text
本分支（含本勘误）     : 34 failed, 1064 passed
干净 main（stash 后）  : 34 failed, 1064 passed
```

⇒ 失败集**完全相同**，本勘误（纯文档）**未引入任何回归**。

⚠️ **34 项失败为既有的 Windows 检出产物，非本勘误所致，也不在本 PR 范围内修正。**
根因：仓库**无 `.gitattributes`** 且 `core.autocrlf=true`，检出时 LF → CRLF，
而多个测试对配置文件做 SHA-256 绑定校验。证据：

```text
configs/phase2/h2-formal-freeze-spec.json
  记录值 formal_freeze_spec_sha256 : 79f2e8a662841f70a5578f6ef8f684799de530d137b1421d9606fe81e9131833
  LF 归一化后实测                : 79f2e8a662841f70a5578f6ef8f684799de530d137b1421d9606fe81e9131833  <- 匹配
  CRLF 磁盘实测                  : 1d45874fea461f55448d0caed029430cf1fe574bd7423e88bd0f4f6700f29b5d  <- 不匹配
```

⇒ 在 M6 的 macOS（LF）环境下这些测试通过
（`docs/phase2c-m6-workload-reuse-regression.json`：1089 passed / 0 failed）。
但该记录绑定的 SHA 为 `d1b20af29d1307f84df13a319a2cb61363b76a9d`，
而当前 `main` 已前进到 `53f01ff`，故不应直接以该记录否定当前状态。

⛔ **修复方式（新增 `.gitattributes` 或按 LF 检出）应作为独立议题由 M1 裁定，不在本勘误中夹带。**

### 6.2 文档

本勘误仅修改 `.md`；仓库中**无任何测试**引用 `.md`（已核 `tests/**` 无命中），
故文档修订不可能影响测试结果。

---

## 7. 请求的裁定

请 M1 复核本勘误，并返回 `ACCEPT` / `CHANGES_REQUESTED` / `BLOCKED`。

⚠️ 本勘误**不请求**任何实现、实验或策略授权；若 `ACCEPT`，仅表示审计文档的证据等级表述已与
Phase 2B/2C 的保真事实对齐。是否值得进一步开发机会三（§4.3）或新观测缝，仍**另需 M1 裁定**（G1）。
