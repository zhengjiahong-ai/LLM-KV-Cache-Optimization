# vLLM 参考文档与网址

[Implementation — vLLM](https://docs.vllm.ai/en/v0.6.0/automatic_prefix_caching/details.html)

该页面说明 vLLM v0.6.0 的自动前缀缓存实现：每个 KV block 由块内 token 与此前前缀 token 的哈希共同标识，逻辑块通过哈希映射到物理块。相同哈希的请求可共享同一物理块。分页存储由 PagedAttention 提供，自动前缀缓存则利用哈希表管理可复用块。

该版本页面还明确了前缀缓存满时的逐出顺序：只考虑 `ref_cnt = 0` 的块；若有多个候选，则优先逐出最久未使用块；时间相同则优先逐出最长前缀末端的块。该说明可作为本项目“vLLM 风格 LRU”基线的语义参考，但不等同于当前所有 vLLM 版本或配置的默认行为。

[lru - vLLM](https://docs.vllm.ai/en/latest/api/vllm/v1/kv_offload/cpu/policies/lru/)

该页面是当前 vLLM V1 的 **CPU KV offload** `LRUCachePolicy` API 文档，不是 GPU 前缀缓存逐出策略的通用规范。它可用于了解 CPU 端 LRU policy 的接口和实现位置，但不应用来证明本项目 GPU KV cache 的默认逐出行为。

[RFC: Context-Aware KV-Cache Retention API (Prioritized Evictions)](https://github.com/vllm-project/vllm/issues/37003)

该 RFC 当前仍为 Open 状态，属于接口提案而非已合并功能。它提出让编排器为 token 范围声明 `priority` 和 `duration`，未被标注的块继续走既有 LRU 路径。提案强调由编排器提供工作流信息，vLLM 负责执行优先级与 TTL。它可用于说明社区正在讨论保留指令接口，不应作为本项目或 vLLM 已取得性能收益的证据。
