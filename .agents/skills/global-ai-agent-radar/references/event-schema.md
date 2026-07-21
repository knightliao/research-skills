# 事件数据契约

## 作用与生命周期

`events.json` 是执行 Agent 完成时间核验、去重、评分和过滤后，为生成最终报告临时整理的数据。文件名只是约定，可以使用任意仓库外临时路径。

- 只写入最终准备进入报告的重点事件、一般重要事件和待验证信号，不写入全部搜索候选。
- 写入某个待验证信号，表示执行 Agent 已判断它值得继续验证；校验脚本不替代这项研究判断。
- 该文件不是事实来源，也不是长期数据资产，不得作为证据引用或提交到 Git。
- 默认在报告生成后删除。确需审计留存时，先移除隐私、凭据和内部数据，再保存到仓库外的受控位置。
- 校验脚本只检查结构、枚举、日期、评分计算和确定性分类，不访问网络，也不验证事实真假、证据支持关系或来源是否真正独立。

## 顶层结构与空结果

输入可以是单个事件对象或事件对象数组。空数组 `[]` 表示**空结果状态**：经过筛选后，没有任何值得写入报告的事件或观察信号。

空结果状态不同于普通“无重点事件模式”：

- 普通无重点事件模式使用非空数组，可能包含一般重要事件或待验证信号；
- 空结果状态不包含事件章节，报告只保留今日结论、研究覆盖、观察池状态、后续验证事项和信息限制。

## 事件字段

每个事件必须包含以下字段：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `title` | string | 非空标题。 |
| `event_date` | string | 事件实际发生日期，格式为 `YYYY-MM-DD`。 |
| `publication_date` | string | 顶层主要来源的发布日期，格式为 `YYYY-MM-DD`。 |
| `source_url` | string | 首要来源的 HTTP 或 HTTPS URL。 |
| `source_type` | string | 首要来源类型，使用脚本支持的来源枚举。 |
| `facts` | array[string] | 至少一条由来源直接支持的事实。 |
| `inference` | string | 非空的分析推断摘要，不得伪装成事实。 |
| `scores` | object | 6 项 0–5 分整数评分；字段与中文名称见下表。 |
| `confidence` | string | 非评分字段；表示执行 Agent 的判断置信度，取值为 `high`、`medium` 或 `low`，不计入总分。 |
| `follow_up_signals` | array[string] | 后续可验证指标；允许为空，但会产生警告。 |

可选字段：

- `total_score`：六项评分之和。存在时必须与脚本重算结果一致；分类始终使用重算结果。
- `additional_sources`：补充来源数组，结构见下节。
- 其他未知字段：允许存在，以支持后续扩展。

`scores` 必须包含以下 6 个评分维度：

| 序号 | 中文名称 | JSON 字段 | 是否计入总分 |
| --- | --- | --- | --- |
| 1 | 新颖性 | `novelty` | 是 |
| 2 | 产品影响 | `product_impact` | 是 |
| 3 | 工程与技术影响 | `engineering_impact` | 是 |
| 4 | 企业应用与商业化影响 | `commercialization_impact` | 是 |
| 5 | 行业竞争与生态影响 | `ecosystem_impact` | 是 |
| 6 | 信息可信度 | `credibility` | 是 |

总分计算公式为：

```text
total_score = novelty
            + product_impact
            + engineering_impact
            + commercialization_impact
            + ecosystem_impact
            + credibility
```

`confidence`（判断置信度）位于 `scores` 之外，不是第 7 个评分维度，也不计入 `total_score`。`credibility` 评价来源质量、证据强度和事实可核验程度；`confidence` 表示执行 Agent 对当前综合判断的把握程度。两者含义不同，不要求一一映射。

## 主要来源与补充来源

顶层 `source_url`、`source_type` 和 `publication_date` 始终表示事件的首要来源，不能由 `additional_sources` 替代。

`additional_sources` 的每一项必须包含：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `url` | string | 非空 HTTP 或 HTTPS URL。 |
| `type` | string | 使用与 `source_type` 相同的枚举。 |
| `role` | string | `primary`、`independent`、`timing` 或 `background`。 |
| `publication_date` | string | 可选；存在时使用 `YYYY-MM-DD`。 |

各角色的含义：

- `primary`：另一个共同构成原始证据的主要来源，例如官方公告之外的官方文档或 GitHub Release。它补充但不替代顶层主要来源，也不会自动获得更高证据权重。
- `independent`：执行 Agent 声明该来源用于独立验证。
- `timing`：主要用于核验事件发生、发布或可用时间。
- `background`：只用于补充背景，不承担核心事实。

校验器只检查是否声明了 `role=independent`，不能证明来源真正独立、具有足够权威性或能够支持事件事实。重点事件和一般重要事件未声明独立来源时会产生非致命警告，由执行 Agent 复核。

## 总分与分类优先级

脚本始终使用六项评分重新计算总分，并按以下顺序分类；前面的规则优先：

1. `credibility` 为 0–1：拒绝进入最终事件清单。
2. `confidence=low`：归为待验证信号，高总分不能覆盖此规则。
3. `credibility=2`：归为待验证信号，不受总分和 `confidence` 影响。
4. 重算总分 24–30、`credibility>=3`、`confidence` 为 `high` 或 `medium`：重点事件。
5. 重算总分 18–23、`credibility>=3`、`confidence` 为 `high` 或 `medium`：一般重要事件。
6. 重算总分低于 18、`credibility>=3`、`confidence` 为 `high` 或 `medium`：仅在执行 Agent 判断值得继续验证时保留为待验证信号。

校验器不会判断第 6 类候选是否值得验证。条目出现在临时 JSON 中，即表示执行 Agent 已作出保留决定；不值得验证的候选不得写入。

## URL 校验与保守去重

顶层 `source_url` 和全部 `additional_sources[].url` 共同参与去重。比较前只执行保守规范化：

- 去除首尾空白；
- 将 scheme 和 hostname 转为小写；
- 去除 fragment；
- 保留 path 原样，包括末尾 `/`；
- 保留 query string、参数顺序、百分号编码和显式端口。

校验器不推测 `/path` 与 `/path/` 等价，不合并不同 query，不展开短链，不跟随跳转，也不查询 canonical URL。地址去重只表示结构上未重复，不代表来源内容或媒体所有权已经独立验证。

## 虚构示例

> 以下数据为虚构示例，仅用于说明字段结构，不代表真实事件。

```json
{
  "title": "ExampleAI 发布虚构的 Atlas Agent 测试版",
  "event_date": "2026-01-10",
  "publication_date": "2026-01-10",
  "source_url": "https://example.invalid/atlas/announcement",
  "source_type": "official",
  "additional_sources": [
    {
      "url": "https://docs.example.invalid/atlas/release",
      "type": "documentation",
      "role": "primary",
      "publication_date": "2026-01-10"
    },
    {
      "url": "https://research.example.invalid/atlas-review",
      "type": "media",
      "role": "independent",
      "publication_date": "2026-01-11"
    }
  ],
  "facts": [
    "虚构产品仅向受邀测试者开放。"
  ],
  "inference": "如果测试范围扩大，可能降低多步骤工作流的集成成本。",
  "scores": {
    "novelty": 4,
    "product_impact": 4,
    "engineering_impact": 4,
    "commercialization_impact": 3,
    "ecosystem_impact": 3,
    "credibility": 4
  },
  "total_score": 22,
  "confidence": "medium",
  "follow_up_signals": [
    "核验未来 2 周测试范围是否扩大。"
  ]
}
```
