# 全球 AI Agent 增量雷达

> 使用说明：根据是否存在 24–30 分的重点事件选择模式 A 或模式 B，删除未使用的模式和无内容章节。不要为了保持形式完整而填充低价值事件。事实、证据、推断和建议必须分别书写。

## 模式 A：有重大变化

### 报告信息

- **报告日期**：{{report_date}}
- **研究截止时间**：{{cutoff_time}}（{{timezone}}）
- **研究范围**：{{research_window}}；重点检查 {{focus_window}}
- **覆盖地区**：{{regions}}
- **重点方向**：{{focus_areas}}
- **面向读者**：{{audience}}

### 今日结论

{{用 2–4 句话说明重点事件数量、最重要增量及其决策意义。不要复述新闻标题。}}

### 今日最重要变化

{{用一个短段落说明最重要变化、相对此前状态的增量，以及为什么现在值得行动。}}

### 重点事件

#### {{event_name}}

- **分类**：{{category}}
- **事件发生时间**：{{event_time}}
- **信息发布时间**：{{publication_time}}
- **能力可用时间与范围**：{{availability_time_and_scope}}
- **重要性等级**：重点事件
- **总评分**：{{total_score}} / 30
- **分项评分**：新颖性 {{novelty_score}}；产品影响 {{product_score}}；工程与技术影响 {{engineering_score}}；企业应用与商业化影响 {{commercial_score}}；行业竞争与生态影响 {{ecosystem_score}}；信息可信度 {{confidence_score}}

**已确认事实**

{{只写来源直接支持的事件事实、发布阶段和适用范围。}}

**证据**

- {{primary_evidence_type_and_direct_link}}
- {{independent_evidence_or_known_gap}}
- {{time_evidence}}

**真正增量**

{{说明此前状态、本次新增能力或新阶段，以及为什么不是旧闻、重复报道或包装变化。}}

**分析推断**

- **产品影响**：{{product_impact_or_no_evidence}}
- **工程与技术影响**：{{engineering_impact_or_no_evidence}}
- **企业应用与商业化影响**：{{commercial_impact_or_no_evidence}}
- **竞争与生态影响**：{{ecosystem_impact_or_no_evidence}}

**风险与不确定性**

- {{risk_or_evidence_limit}}
- {{scope_or_reproducibility_limit}}

**行动建议**

- {{audience}}：{{action_with_condition_and_stop_rule}}

**后续观察指标**

- {{metric}}；数据来源：{{metric_source}}；期限：{{observation_period}}；触发条件：{{trigger}}

<!-- 有多个重点事件时复制上面的事件块。 -->

### 一般重要事件

#### {{event_name}}

- **事件与增量**：{{confirmed_fact_and_increment}}
- **证据与可信度**：{{evidence_links_and_confidence}}
- **评分**：{{total_score}} / 30
- **影响与边界**：{{material_impact_and_limits}}
- **后续指标**：{{verifiable_metrics}}

<!-- 没有 18–23 分的一般重要事件时删除本节。 -->

### 观察池调整

- **升级**：{{entity_and_evidence_based_reason_or_none}}
- **降级**：{{entity_and_evidence_based_reason_or_none}}
- **暂停**：{{entity_and_evidence_based_reason_or_none}}
- **剔除**：{{entity_and_evidence_based_reason_or_none}}
- **维持**：{{entities_and_short_reason}}

### 值得行动的方向

1. **{{action_title}}**：{{owner}} 在 {{timeframe}} 内执行 {{bounded_action}}；使用 {{success_metric}} 判断是否继续。
2. **{{action_title}}**：{{owner}} 在 {{timeframe}} 内执行 {{bounded_action}}；主要风险为 {{risk}}。

### 未来 1–4 周观察指标

- {{week_1_signal_and_verification_source}}
- {{week_2_signal_and_verification_source}}
- {{week_4_signal_and_verification_source}}

### 方法和信息限制

{{说明搜索范围、时间口径、主要证据缺口、无法访问的来源和可能影响判断的限制。}}

---

## 模式 B：没有重大变化

### 报告信息

- **报告日期**：{{report_date}}
- **研究截止时间**：{{cutoff_time}}（{{timezone}}）
- **研究范围**：{{research_window}}
- **覆盖地区与方向**：{{regions_and_focus_areas}}

### 今日结论

**今天没有重大突破。**

{{说明没有重点事件的原因，例如候选项总分不足、可信度不足或只是旧闻重发。不要加入低价值新闻填充。}}

### 未达到收录阈值的观察信号

#### {{signal_name}}

- **已确认事实**：{{confirmed_fact}}
- **证据与可信度**：{{evidence_and_confidence}}
- **评分**：{{score}} / 30
- **未收录原因**：{{threshold_or_confidence_reason}}
- **待验证条件**：{{specific_verification_conditions}}

<!-- 没有值得保留的观察信号时删除本节。 -->

### 观察池状态

- **升级**：{{none_or_entities}}
- **降级**：{{none_or_entities}}
- **暂停或剔除**：{{none_or_entities}}
- **维持**：{{entities_and_short_reason}}

### 后续验证事项

- {{verification_item_with_timeframe}}
- {{verification_item_with_source_or_trigger}}

### 信息限制

{{说明本期未覆盖范围、来源缺口和其他限制。}}
