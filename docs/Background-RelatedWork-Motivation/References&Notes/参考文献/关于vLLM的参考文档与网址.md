# vLLM 参考文档与网址

> **文档定位**：本文件只登记**非论文**的 vLLM 参考材料及其证据等级。书目权威（论文标题、作者、版本、日期）见 [`文献索引.md`](文献索引.md)；论文细节见 [`../论文总结.md`](../论文总结.md)；项目术语口径见 [`../../专业术语表.md`](../../专业术语表.md)。
>
> **本项目后端**：vLLM **0.27.1** + GPU **Automatic Prefix Caching (APC)**。下列材料均**不是**该版本的权威规范，**不得**用来证明本项目运行时的默认逐出行为。
>
> **核验限制**：本次修订环境无法访问 `github.com` 与 `docs.vllm.ai`，因此下列链接的**当前可达性、内容是否已变更、以及 RFC 的当前状态均未核验**。链接一律保留原始稳定 URL，未替换为可能失效的镜像。

---

## 1. vLLM v0.6.0 自动前缀缓存实现文档（历史语义参考）

**稳定链接**：https://docs.vllm.ai/en/v0.6.0/automatic_prefix_caching/details.html

该页面说明 vLLM **v0.6.0** 的自动前缀缓存实现：每个 KV block 由块内 token 与此前前缀 token 的哈希共同标识，逻辑块通过哈希映射到物理块；相同哈希的请求可共享同一物理块。分页存储由 PagedAttention 提供，自动前缀缓存利用哈希表管理可复用块。

该版本页面还记载了前缀缓存满时的逐出顺序：

1. 只考虑 `ref_cnt = 0` 的块；
2. 若有多个候选，优先逐出**最久未使用**的块；
3. 最后访问时间相同，则优先逐出**最长前缀末端**的块。

**证据等级与边界**：

- 这是**版本固定为 v0.6.0 的实现文档**，可作为"vLLM 风格 LRU"的语义参考；
- **不等同于当前所有 vLLM 版本或配置的默认行为**；本项目后端为 vLLM 0.27.1，其原生 APC 逐出语义**本次未核验**；
- 这是**实现文档**，不是同行评审论文；不得把其中的逐出顺序表述为 PagedAttention 论文（arXiv:2309.06180v1）的默认逐出实现，两者是不同的来源。

---

## 2. vLLM V1 CPU KV offload `LRUCachePolicy` API 文档（接口参考）

**稳定链接**：https://docs.vllm.ai/en/latest/api/vllm/v1/kv_offload/cpu/policies/lru/

该页面是当前 vLLM V1 的 **CPU KV offload** `LRUCachePolicy` API 文档。它可用于了解 CPU 端 LRU policy 的接口与实现位置。

**证据等级与边界**：

- 这是 **CPU 端 offload policy 接口**，**不是** GPU 前缀缓存逐出策略的通用规范，**不应用来证明本项目 GPU KV cache 的默认逐出行为**；
- 链接使用 `/latest/`，会随上游更新而变；本次修订**未核验**其当前解析到的版本与内容；
- 本项目不做 CPU KV offloading（见 [`../../项目动机文档.md`](../../项目动机文档.md) §5），该材料仅用于划定范围。

---

## 3. vLLM RFC #37003（工程提案，不是论文、不是已实现功能）

**稳定链接**：https://github.com/vllm-project/vllm/issues/37003

仓库既有笔记记载其标题为 **"Context-Aware KV-Cache Retention API (Prioritized Evictions)"**，提案内容为：让上层编排器为 token 范围声明 `priority` 与 `duration`（`RetentionDirective` 带 `start` / `end` / `priority` / `duration`），未被标注的块继续走既有 LRU 路径；由编排器提供工作流信息，vLLM 负责执行优先级与 TTL。

**证据等级与边界（必须随引用一起声明）**：

- 这是 **RFC / 工程接口提案**，**不是同行评审论文**，**不是已合并（merged）的实现特性**；
- **没有任何实验或性能数据**，不得作为本项目或 vLLM 已取得性能收益的证据；
- 它在决策层级上属于**自顶向下由调用方声明重要性**（L3 保留指令接口），与本项目"由系统在线估计重要性"的路线互补；仅作为范围级保留表示的接口先例；
- **核验状态（未核实）**：本环境无法访问 github.com，因此该 issue 的**当前状态（Open / Closed / 已修订）、标题准确性与正文表述均未经本次核验**。上文标题来自本仓库既有笔记。对外引用前必须访问原链接确认，并须以 [`文献索引.md`](文献索引.md) §5 的未核验项登记为准。

---

## 4. vLLM 官方 `paged_attention.md`（历史 kernel 文档）

**仓库内文件**：[`paged_attention.md`](paged_attention.md)

该文档是 vLLM 官方对 **PagedAttention attention kernel 实现**的分步说明（输入、k/v cache 内存布局、QK、Softmax、Value、LV、Output），文首自带警告：

> This is a historical document based on the [original paper for vLLM](https://arxiv.org/abs/2309.06180). It no longer describes the code used in vLLM today.

**证据等级与边界**：

- **不是论文**、**不含任何驱逐策略语义**；只可用于解释 kernel 与 block 布局；
- **不得**作为本项目或 vLLM 逐出行为的依据；
- 与 §1 的 v0.6.0 APC 实现文档是两份不同材料：一份讲分页内存/哈希/逐出，一份讲 attention kernel。

---

## 5. 交叉引用

| 主题 | 权威文档 |
| --- | --- |
| 论文标题、作者、arXiv 版本与日期 | [`文献索引.md`](文献索引.md)（唯一书目权威） |
| PagedAttention 论文内容与 20.4% 等数字的条件 | [`../论文总结.md`](../论文总结.md) §1 |
| Continuum 风格基线的项目适配边界 | [`../../../baseline-freeze.md`](../../../baseline-freeze.md) §6、§8 |
| Entry / Block 两层、unpin / eviction 的定义 | [`../../专业术语表.md`](../../专业术语表.md) §1 |
| 当前项目状态与授权 | [`../../../research-status.md`](../../../research-status.md)（canonical，位于 `main`） |
| 四个未来研究方向中 RFC 的使用方式 | [`../../kv_cache_optimization_motivation_and_design_proposal.md`](../../kv_cache_optimization_motivation_and_design_proposal.md) §8.3、§11.5 |
