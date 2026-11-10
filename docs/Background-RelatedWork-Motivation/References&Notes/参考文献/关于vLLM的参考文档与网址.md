# vLLM 参考文档与网址

## vLLM 0.27.1 GPU APC 的项目边界

项目使用 Native vLLM 的 BlockPool、free queue、refcount、APC hash 和物理清理。Phase 1A adapter 接收 Native 合法候选，并通过 Native 路径执行选出的 victim。Phase 1B 另维护逻辑 retention 状态和资格过滤。解除 Entry 保护后，关联 Block 是否可回收仍由引用及其余保护约束决定。项目的具体候选与 victim 顺序以[适配器设计](../../../policy-adapter-design.md)、[基线冻结](../../../baseline-freeze.md)和 [Phase 1B final report](../../../experiments/phase1b-continuum/final-report.md)为准。

## 历史 APC 文档与 CPU offload API

- v0.6.0 的 APC 文档说明由块内 token 和前缀构造 hash，逐出从零引用候选中按 LRU 选择，同时间按较长前缀末端优先。该规则属于旧版本，不能据此推定 0.27.1 的并列顺序。[vLLM v0.6.0 APC Implementation](https://docs.vllm.ai/en/v0.6.0/automatic_prefix_caching/details.html)
- vLLM V1 的 LRUCachePolicy API 位于 CPU KV offload 模块，其对象、队列与 GPU APC 的 Native victim 路径不同。该链接跟随 latest 版本。[CPU offload LRU API](https://docs.vllm.ai/en/latest/api/vllm/v1/kv_offload/cpu/policies/lru/)
- 本地 Paged Attention 笔记描述历史 attention kernel 与数据布局，包含 query/key/value 的向量组织。它不能作为当前 BlockPool 的实现规范。[历史 kernel 笔记](paged_attention.md)

## RFC #37003

该提案允许 orchestrator 通过 token range 指定 priority 和 duration，未标注的块沿用 LRU。其价值在于展示保留指令和请求调度可以使用不同的接口。issue 正文及讨论中的原型属于提案材料，未核实该 API 的上游发布状态，项目的独立保护表不依赖该接口。[Context-Aware KV-Cache Retention API (Prioritized Evictions)](https://github.com/vllm-project/vllm/issues/37003)
