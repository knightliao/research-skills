# 仓库协作规范

## 适用范围与目录结构

本仓库是用于管理研究型 Agent Skill 的 Monorepo。根目录只放置仓库级文档、通用框架、Skill 插件、CLI 和测试，避免堆放与全局管理无关的文件。

- 将每个 `.agents/skills/<skill-name>/` 目录视为一个独立 Skill。
- 每个 Skill 都必须包含带有有效 YAML frontmatter 的 `SKILL.md`。
- 保持 `SKILL.md` 简洁；详细策略、评分规则和领域知识应放入 `references/`。
- 示例放入 `examples/`，可复用的输出素材放入 `assets/`，确定性工具放入 `scripts/`。
- 不要在 Skill 内新增 `README.md`；`SKILL.md` 是 Skill 的入口文件。

## 框架、插件与 CLI 边界

- `skill_framework/` 是通用内核，只负责 Skill 发现、结构、frontmatter、本地引用、Python 边界、安全扫描、仓库规范和 ZIP 打包，不得包含任何具体 Skill 的字段、评分或报告模式。
- `plugins/` 存放仓库开发期的 Skill 专属静态校验。插件可以了解对应 Skill 的数据契约，但不进入 ZIP，也不能成为 Skill 运行时依赖。
- `tools/` 只提供稳定的命令行入口，负责根目录导入 bootstrap、参数解析、中文输出和退出码；业务逻辑必须放入框架或插件。
- `tests/framework/` 测试通用内核，`tests/plugins/` 测试插件接口和专属规则，`tests/skills/` 测试打包后 Skill 的运行时行为，`tests/integration/` 测试 CLI、打包和端到端流程。

插件第一版只支持以下接口：

```python
PLUGIN_API_VERSION = 1
SKILL_NAME = "skill-name"

def validate(context: SkillContext) -> ValidationResult:
    ...
```

- 插件文件名必须等于 Skill 名称将 `-` 替换为 `_` 后的结果。
- 插件只能返回独立的不可变 `ValidationResult`，不得接收、持有或修改仓库级全局报告。
- `Issue.code` 是稳定的机器可读接口；通用 code 在 `skill_framework/codes.py` 中维护，专属 code 使用 Skill 前缀并在对应插件中维护。
- 插件是受信任的仓库代码，但只能执行确定性、无网络、无文件修改的静态检查。
- Skill 可以不提供插件；此时只执行通用校验。增加无插件 Skill 不应要求修改框架、CLI 或 CI。

## Skill 边界

- 每个 Skill 必须保持自包含：内部引用和本地链接不得指向该 Skill 目录之外。
- 不得依赖其他 Skill 管理的文件。当隔离性比复用更重要时，可以在 Skill 内保留一份体积小且稳定的素材副本。
- Skill 目录名只能使用小写英文字母、数字和连字符，并且必须与 `SKILL.md` 中的 `name` 完全一致。
- 采用渐进式披露：从 `SKILL.md` 直接链接所需参考文件，避免形成多层嵌套的引用链。

## 脚本与 Python

- 脚本只处理校验、规范化、解析或格式化等确定性任务。研究判断、信源评估和编辑结论应保留在 Skill 指令与参考资料中。
- 除非仓库另有明确且成文的决定，否则统一使用 Python 3.11 或更高版本，并且仅使用 Python 标准库。
- 命令必须支持非交互运行、结果确定，并在失败时返回非零退出码。
- 使用空格缩进和清晰的 `snake_case` 命名；类型提示应服务于可读性，模块应职责集中。

## 语言规范

- 仓库文档默认使用简体中文，包括工作说明、研究规则、解释、示例和报告模板。
- 技术标识、文件名、代码标识符、命令行参数、JSON 字段名和 CSV 表头保持英文。
- 用户未指定语言时，Skill 输出和最终研究报告默认使用简体中文。
- 翻译和改写应优先保证语义准确、表达自然和规则可执行，不进行机械或生硬的逐句直译。
- 公司名、产品名、项目名和技术专有名词保留官方名称；必要时在第一次出现时补充中文解释。
- 中文与英文、数字之间适当留空格，并统一使用中文标点和排版。
- 后续新增文档必须遵守相同的语言规范。

## 安全与数据处理

- 禁止提交密钥、API Key、Token、Cookie、凭据、个人隐私、私人通信或内部及专有数据。
- 除非是经过明确脱敏并有意纳入测试的固定样例，否则生成的报告和抓取的信源材料不得进入版本控制。
- 不得在示例、测试、素材或日志中嵌入真实凭据或私有服务地址。

## 修改后验证

每次修改后必须：

1. 运行 `python3 -m unittest discover -s tests`。
2. 修改 Skill 文件或仓库校验规则后，运行 `python3 tools/validate_all_skills.py`。
3. 修改 Python 后运行 `python3 -m compileall skill_framework plugins tools tests .agents/skills`。
4. 在报告完成前运行 `git diff --check`，并检查 `git diff` 和 `git status --short`。

每次行为变更或缺陷修复都应补充确定性测试。随着项目发展，在 `tests/` 中覆盖校验器行为和重要失败场景。

## 变更安全

- 保留用户已有工作，并将修改严格限制在当前任务范围内。
- 未经用户明确要求，不得提交、推送、删除、重命名、覆盖或取消暂存用户已有文件。
- 不得进行无关重构，也不得改写现有 Git 历史。
- 忽略 `.idea/` 等 IDE 专用文件，不要将其加入提交。

## 提交与 Pull Request

仅在用户明确要求时创建提交。提交主题应简短并使用祈使语气，也可以遵循 Conventional Commits。Pull Request 应说明修改动机、实现方式、验证命令，以及兼容性或配置变更。
