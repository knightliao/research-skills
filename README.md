# 研究型 Agent Skills

本仓库是用于管理多个研究型 Agent Skill 的 Monorepo。它将研究工作流、参考规则、示例、输出模板和确定性工具放在可独立校验、测试和打包的 Skill 目录中。

每个 `.agents/skills/<skill-name>/` 都是独立 Skill，必须包含 `SKILL.md` 并保持自包含。Skill 的运行时引用、本地链接和脚本依赖不得指向该 Skill 目录之外。

仓库采用四层架构：`skill_framework/` 提供完全通用的内核，`plugins/` 承载 Skill 专属校验，`tools/` 只保留 CLI，`tests/` 按框架、插件、Skill 和集成场景分层。插件是仓库开发期扩展，不进入 Skill ZIP，也不是 Skill 运行时依赖。

## 当前 Skill

### global-ai-agent-radar

`global-ai-agent-radar` 研究最近 24–72 小时全球 AI Agent 在产品、技术、开源生态、企业应用、商业化、融资和竞争方面的真正增量，为技术负责人、产品负责人、业务负责人和创业者生成增量雷达。它强调原始来源、时间核验、去重、评分、影响判断和后续可验证指标，不是普通 AI 新闻摘要。

具体工作流以该 Skill 的 `SKILL.md` 和 `references/` 为准，本 README 不重复维护研究规则。

## 目录结构

```text
.
├── .agents/skills/
│   └── global-ai-agent-radar/
│       ├── SKILL.md
│       ├── references/
│       ├── examples/
│       ├── assets/
│       └── scripts/
├── .github/workflows/validate.yml
├── skill_framework/        # 通用发现、校验、安全与打包内核
├── plugins/                # Skill 专属静态校验插件
├── tools/
│   ├── package_skill.py
│   └── validate_all_skills.py
├── tests/
│   ├── framework/
│   ├── plugins/
│   ├── skills/
│   └── integration/
├── AGENTS.md
└── README.md
```

仓库要求 Python 3.11 或更高版本，所有本地工具只使用 Python 标准库。

## 本地校验与测试

校验全部 Skill 的通用结构、安全规则及已注册专属插件：

```bash
python3 tools/validate_all_skills.py .
```

运行全部单元测试和端到端冒烟测试：

```bash
python3 -m unittest discover -s tests -v
```

检查 Python 文件能否编译：

```bash
python3 -m compileall \
  skill_framework \
  plugins \
  tools \
  tests \
  .agents/skills
```

校验输出中的每条错误和警告都包含稳定的英文 `code`，便于 CI、编辑器或后续 API 按类别处理；中文消息用于定位动态详情。

## 校验研究事件 JSON

`validate_events.py` 接受单个事件对象或事件对象数组。建议使用仓库外临时路径：

```bash
python3 .agents/skills/global-ai-agent-radar/scripts/validate_events.py \
  <临时目录>/events.json
```

`events.json` 只是约定名称，可以替换为任意 JSON 文件路径。它由执行 Agent 在完成时间核验、去重、评分和过滤后临时生成，只包含最终准备写入报告的重点事件、一般重要事件和待验证信号，不包含全部搜索候选。

空数组 `[]` 表示没有任何最终条目的空结果状态；非空数组但没有重点事件时，仍属于普通“无重点事件模式”，可以包含一般重要事件和待验证信号。完整字段、来源角色、分类顺序和 URL 去重规则见 Skill 内的 `references/event-schema.md`。

该文件不是事实来源或长期数据资产，默认在报告生成后删除，不应提交到当前仓库。需要留存时，应先脱敏并选择仓库外的受控位置。校验器只检查结构和确定性规则，不验证事实真假、来源独立性或证据支持关系。

## 打包单个 Skill

默认从 `.agents/skills/<skill-name>/` 读取，并输出到 `dist/<skill-name>.zip`：

```bash
python3 tools/package_skill.py global-ai-agent-radar
```

也可以显式指定 Skill 和输出目录：

```bash
python3 tools/package_skill.py \
  --skill global-ai-agent-radar \
  --output-dir dist
```

打包前会执行通用校验、安全扫描，并只导入目标 Skill 对应的插件。其他 Skill 的插件即使损坏，也不会阻塞定向打包；完整仓库校验和 CI 仍会发现该问题。校验失败、Skill 不存在或缺少 `SKILL.md` 时不会生成或覆盖正式 ZIP。同名输出使用临时文件原子覆盖，源 Skill 不会被修改。

ZIP 只有一个顶层目录：

```text
global-ai-agent-radar.zip
└── global-ai-agent-radar/
    ├── SKILL.md
    ├── references/
    ├── examples/
    ├── assets/
    └── scripts/
```

缓存、`.DS_Store`、Git 元数据、IDE 配置和临时编辑器文件不会进入 ZIP。`dist/` 是本地构建输出，不进入 Git。

`skill_framework/`、`plugins/`、`tools/` 和 `tests/` 都属于仓库开发设施，不会进入 Skill ZIP。

## 维护观察池

具体结构化名单只维护在 `.agents/skills/global-ai-agent-radar/assets/watchlist.csv`，分类和调整规则由 `references/company-watchlist.md` 定义。

维护流程：

1. 日报或研究报告只提出观察池升级、降级、暂停、剔除或新增建议，不自动修改 `watchlist.csv`。
2. 人工核验对象名称、官方地址、分类、状态和调整证据。
3. 经人工确认后修改 `watchlist.csv`，避免同时维护第二份完整名单。
4. 运行仓库校验和单元测试，查看 `git diff` 后再提交。

观察池不是排名或封闭名单，研究时仍需发现池外的新公司、产品、项目和协议。

## 增加新的 Skill

1. 在 `.agents/skills/<skill-name>/` 创建独立目录；名称只使用小写字母、数字和连字符。
2. 创建带有 `name` 和 `description` frontmatter 的 `SKILL.md`，并确保 `name` 与目录名一致。
3. 按需增加 `references/`、`examples/`、`assets/` 和 `scripts/`；不要在 Skill 内新增 README。
4. 保证所有运行时文件和本地引用都位于该 Skill 目录内，脚本只处理确定性任务。
5. 如果只有通用约束，不需要新增插件；仓库校验和 CI 会自动发现并打包该 Skill。
6. 如果有专属数据契约，在 `plugins/<skill_name>.py` 实现 `PLUGIN_API_VERSION = 1`、`SKILL_NAME` 和返回独立 `ValidationResult` 的 `validate(context)`；插件不得修改文件或访问网络。
7. 通用测试放入 `tests/framework/`，插件测试放入 `tests/plugins/`，Skill 运行时测试放入 `tests/skills/<skill_name>/`，端到端测试放入 `tests/integration/`。
8. 运行仓库校验、全部测试、目标打包、`compileall` 和 `git diff --check`。

插件文件名使用 Skill 名称将连字符替换为下划线后的形式，例如 `global-ai-agent-radar` 对应 `plugins/global_ai_agent_radar.py`。仓库级校验会全量发现插件并报告失效或孤立插件；定向打包只加载目标插件。

## Git 提交建议

- 每个提交只处理一个明确主题，使用简短、祈使语气的主题；可以采用 Conventional Commits。
- 提交前运行全部测试和校验，检查 `git status --short` 与 `git diff`。
- 不提交 `dist/`、`runs/`、运行时事件数据、缓存或本地研究输出。
- 未经明确要求，不创建提交、不推送，也不删除其他人的已有文件。

## 安全规范

- 不提交 API Key、Token、Cookie、密码、Authorization Header、私钥、个人隐私、内部数据或私人服务地址。
- 测试只能使用明确标记的虚构数据或假凭据，且不得输出完整疑似秘密值。
- 研究报告、抓取材料和运行日志默认不进入版本控制。
- 打包前必须通过本地校验；发现高可信敏感信息时打包立即失败。

## 第一版已知限制

- 当前只有 `global-ai-agent-radar` 一个 Skill；CI 会自动发现、校验和打包新增 Skill，但专属业务行为仍需随 Skill 增加对应测试。
- 插件 API 当前版本为 `1`，第一版只提供 `validate` 钩子，不提供自定义打包、发布或 benchmark 生命周期。
- 插件作为受信任的本地 Python 代码运行，没有进程级沙箱；代码审查必须保证其确定性、无网络且不修改文件。
- 事件校验支持单个 JSON 对象或 JSON 数组（包括表示空结果的 `[]`），暂不支持 JSON Lines。
- frontmatter 校验只支持当前仓库使用的扁平 `key: value` 子集，不是完整 YAML 解析器。
- 本地工具只做确定性校验和打包，不负责联网检索、新闻抓取或研究判断。
- 观察池调整依赖人工确认，不会由日报或脚本自动写入。
- ZIP 未签名，并保留源文件时间信息，不保证不同文件系统之间逐字节完全一致。
- 打包工具不保留符号链接；指向 Skill 外部或失效的符号链接会导致校验失败，合法的内部符号链接也会从 ZIP 中省略。
