# 公众号文章包规则

## 两层模型

文章源稿与发布包必须分开：

- 可编辑源稿位于文章包之外。用户可以反复修改同一个 Markdown 文件。
- `init` 每次读取当前源稿并复制为新版本包内的 `article.md` 快照。
- 包内 `article.md` 和 `illustration-plan.json`（如有）都是不可变发布输入；哈希变化会阻止 finalize。
- 旧包无论 incomplete 还是 complete 都不承担文章修改或模式切换；需要变化时运行新的 `init` 或 `rebuild`。
- complete 包永久只读；incomplete 包只允许安装该版本缺少的提示词与图片，并执行 `fail` 或 `finalize`。

## 文章源稿与插图计划

源稿只使用一个一级主标题、二级标题、普通段落、行内加粗、一级有序/无序列表、一级引用和分割线。拒绝所有图片引用、图注、表格、代码、内嵌 HTML、三级标题和嵌套列表。连续普通文本行属于同一段，空行结束段落；行内加粗不得跨行、嵌套、为空或未闭合。

发布模式必须显式归入以下枚举：

- `cover-only`：默认模式，只需要无字横版封面；不创建插图计划，或计划的 `images` 为空。
- `body-images`：显式正文配图模式；必须在 init 时提供独立 `illustration-plan.json`，且包含 1–4 张图片。

插图计划属于发布包配置，不属于文章内容。固定格式为：

```json
{
  "schema_version": 1,
  "images": [
    {
      "file": "images/body-01.png",
      "purpose": "说明该图用于表达什么",
      "section": "与源稿完全一致的二级标题",
      "insert_after_paragraph": 2
    }
  ]
}
```

文件编号从 01 连续递增，最多 4 张。`purpose` 不能为空；`section` 必须唯一对应源稿中的二级标题；`insert_after_paragraph` 只统计该章节的普通正文段落。计划必须按正文出现顺序排列，同一段落之后只能插入一张图。HTML 渲染器根据计划插入图片，绝不修改源稿。

正文有效字符数仍由共享 AST 计算：排除标题和 Markdown 控制符，再排除所有 Unicode 空白，普通段落、列表项和引用的实际文字计入。该数字用于内容审阅和人工决定配图量，不自动改变发布模式或插图计划。

## 图片与文章内容适配

图片不是与正文分离的通用装饰。编写提示词或编辑图片前，必须读取最终标题、导语、各节主旨和结语，不能只看文件名、标题或人物身份。先形成一份不进入正文的内部视觉简报：

- `core_theme`：文章真正讨论的对象；
- `central_tension`：文章要呈现的冲突、反差或判断；
- `tone`：理性、审慎、乐观、警示等整体语气；
- `allowed_metaphors`：由文章明确用语、论点或结构支持的抽象视觉隐喻；
- `forbidden_inferences`：图片不得暗示的具体事实、产品、场景、数字或立场。

为每张图写出至少两项“文章线索 → 视觉表达”的映射，视觉表达可使用色彩关系、光线、背景纹理、空间层次、抽象隐喻和构图重心。例如，文章同时讨论资本热度与商业落地压力时，可以用克制的冷色主体与少量暖色张力、逐渐消散的抽象圆形或受约束的结构线表达；不得据此虚构具体融资事件、机器人型号或现场。抽象元素必须是隐喻，不能伪装成纪实照片中的真实物体。

横版裁切、人物移位、留白和通用科技蓝背景只属于版式适配，不能单独证明内容适配。成品必须通过“换标题测试”：如果不修改画面就能自然套用到另一篇同领域但观点不同的文章，说明内容映射过弱，必须重新调整。内容相关性不得以牺牲人物真实性和事实边界为代价。

## 预览图与正式资产路径

“先试一张配图”“看看封面方向”等请求属于图片预览，不等同于创建发布包。必须先确定本次交付属于预览还是正式发布，再选择路径：

- **图片预览**：不运行 `init`、`rebuild`、`set-prompts`、`add-image` 或 `finalize`，也不创建文章包。成品保留在宿主图片工具的默认生成目录；在 Codex 中通常是 `$CODEX_HOME/generated_images/...`。下载头像或转换格式需要中转时，使用仓库之外、文章包之外的操作系统临时路径。不得为预览在仓库中创建 `output/`、`images/`、`covers/` 等通用目录，也不得把散落图片写进 `reports/subtitle-to-wechat-article/`。
- **正式发布资产**：先使用 `init` 或 `rebuild` 在 `reports/subtitle-to-wechat-article/<package>/` 创建不可覆盖的发布包，再固化提示词并生成临时图片。封面必须通过 `add-image --role cover` 安装为包内 `cover.png`；正文图必须通过相应 `add-image --role body --index N` 安装为 `images/body-NN.png`。只有被 manifest 记录且通过资源校验的固定目标才算正式资产。

预览图通过方向确认后，也不能手工复制或移动到包内。用户明确要求准备发布时，创建新包；若该预览仍符合冻结后的文章快照、视觉简报、提示词和资源校验，可以把它作为 `add-image` 的临时输入，否则重新生成。最终交付必须区分“预览文件实际路径”和“包内正式资产路径”，不能把宿主生成目录或中转目录报告成文章包输出。

## 用户访谈的人物配图

文章以一位明确的用户或受访者及其经历、观点为核心时，封面优先使用该人物的真实头像作为主视觉；此规则同时适用于默认 `cover-only` 和显式 `body-images` 模式。按以下顺序处理：

1. **确认主人公**：只根据字幕、讲者标注、标题或用户明确提供的信息确定核心受访者。主持人、采访者、旁白和被顺带提到的人不是默认主人公；多人访谈、圆桌或身份有歧义时，先请用户指定，不得静默选择。
2. **确认身份线索**：必须有明确姓名、账号或官方主页等文本线索，不通过声音、面部或上下文猜测私人身份。姓名存在同名风险时，至少再用一个字幕已知线索或用户提供信息交叉确认；该线索只用于避免下错头像，不得写入文章。
3. **获取头像**：优先使用用户提供且确认可用的头像；否则依次选择人物本人控制的公开主页、所属组织的官方人物页、可信活动或讲者页中的清晰单人头像。不得使用搜索结果缩略图、来源不明转载、带水印图片、无法确认人物的合影，也不得绕过登录、付费或其他访问控制。将原图下载到文章包之外的临时路径，不能作为额外图片留在包内；在最终交付说明中记录原始页面 URL、图片 URL 和获取日期，但不要写入文章正文。
4. **微修适配**：必须使用支持参考图编辑的图片工具，并把下载头像作为编辑输入，不能只凭姓名或文字描述重新生成人物。先应用本文件的内容—视觉映射，再做裁切、构图、背景延展或弱化，以及轻度曝光、色温、对比度、去噪和锐化。可以加入文章明确支持的克制色彩关系、背景纹理和抽象隐喻，但不能新增会被误认为真实记录的机器人、产品、场所、动作或事件。保持人物可识别性，不改变五官、年龄、肤色、体型、发型或身份特征，不做人脸替换，不新增文字、Logo、产品使用行为或暗示性纪实场景。
5. **安装成品**：将微修结果导出为真实 PNG。`cover-only` 将其作为 `cover.png`；`body-images` 仍以它作为封面主视觉，只有冻结的插图计划确实需要人物图时才另外安装一张正文图，避免机械重复同一头像。正式封面继续满足至少 1.8:1 的宽高比并通过资源校验。

头像检索是“文章事实不得联网补写”的唯一素材获取例外，只能用于定位和确认配图。主人公无法唯一确认、找不到可靠清晰头像、来源或使用权限不清，或微修工具不可用时，不得改用 AI 生成的相似人物冒充本人。只预览图片时停止生成并请求用户确认人物、提供官方链接或提供有权使用的头像，不创建文章包；正式打包时运行 `fail` 记录原因并保留 incomplete 包。

## 创建新版本

默认创建 cover-only 包：

```text
python3 scripts/build_wechat_package.py init \
  --source SUBTITLE \
  --article /path/to/editable-article.md \
  --output-root reports/subtitle-to-wechat-article \
  --mode cover-only
```

显式正文配图：

```text
python3 scripts/build_wechat_package.py init \
  --source SUBTITLE \
  --article /path/to/editable-article.md \
  --output-root reports/subtitle-to-wechat-article \
  --mode body-images \
  --illustration-plan /path/to/illustration-plan.json
```

`--mode` 省略时为 `cover-only`。init 只校验文章结构和插图计划结构，不要求图片已经存在。成功时 stdout 只返回新文章包的绝对路径。目录名最多 80 个 Unicode 字符、180 个 UTF-8 字节；同一来源重复执行自动创建基础目录、`-v2`、`-v3`，绝不覆盖。

manifest 使用 schema v2，记录外部 `article_source_file`、当前 `mode`、包内文章哈希，以及插图计划文件、哈希和数量。`expected_body_image_count` 由冻结的计划长度决定；cover-only 为 0。

## 重建新版本

从旧包的文章快照创建新版本：

```text
python3 scripts/build_wechat_package.py rebuild PACKAGE
```

使用修改后的外部源稿，或切换模式：

```text
python3 scripts/build_wechat_package.py rebuild PACKAGE \
  --article /path/to/edited-article.md \
  --mode body-images \
  --illustration-plan /path/to/new-plan.json
```

`rebuild` 默认使用旧包的 `article.md` 快照、来源字幕、模式和输出根目录。body-images 模式会复用旧包中独立且可信的计划；旧版包没有独立计划时，必须显式传入新计划。该命令只读旧包，并通过与 init 相同的排他版本创建流程生成新包；不会在原包内改写任何文件。

## 固化提示词与安装图片

cover-only 的提示词文件只包含：

```markdown
## cover

无文字横版封面提示词。
```

body-images 模式继续按计划数量提供 `body-01`、`body-02` 等连续角色。运行：

```text
python3 scripts/build_wechat_package.py set-prompts PACKAGE PROMPTS_FILE
```

固定目标为 `image-prompts.md`，已有目标时拒绝覆盖。普通文章的封面应为无文字横版编辑插画，建议接近 2.35:1；每个提示词必须包含来自内部视觉简报的内容—视觉映射。用户访谈的 cover 提示词还必须说明以已确认主人公头像为编辑输入并遵守人物微修边界。正文图应服务于计划中的用途和章节，不补写字幕之外的事实。

安装真实 PNG：

```text
python3 scripts/build_wechat_package.py add-image PACKAGE TEMP_IMAGE --role cover
python3 scripts/build_wechat_package.py add-image PACKAGE TEMP_IMAGE --role body --index 1
```

第二条只适用于 body-images 模式中的有效编号。工具临时路径不是成果；只有通过命令原子安装到固定目标的文件才算 ready。命令校验 PNG 数据块边界、CRC、IHDR、尺寸、IDAT 和 IEND，并记录 SHA-256、宽度与高度。封面宽高比至少为 1.8:1。已有正式目标一律拒绝覆盖，不得使用占位图。

图片生成失败时运行 `fail PACKAGE --reason "失败原因"`。已安装资产保留，状态继续为 incomplete。

## 完成、渲染与发布

```text
python3 scripts/build_wechat_package.py finalize PACKAGE
```

finalize 重新验证文章和计划哈希、结构、提示词、真实图片、额外资产和内部临时文件，再用共享 AST 与计划生成 `wechat-body.html`。失败原因原子写入 manifest 与发布指南；可以补齐当前版本缺少的资产后重试，但不能在原包内更换文章或模式。

完成后按 `publish-guide.md`：

1. 将 `title.txt` 粘贴到公众号标题栏。
2. 上传 `cover.png`。
3. 在浏览器打开 `wechat-body.html`，复制正文并粘贴到公众号编辑器。
4. 检查二级标题是否放大、加粗；body-images 模式还要逐张核对计划插入的正文图。

独立渲染默认不带正文图片：

```text
python3 scripts/render_wechat_html.py ARTICLE.md -o wechat-body.html
```

显式使用插图计划时：

```text
python3 scripts/render_wechat_html.py ARTICLE.md \
  --illustration-plan illustration-plan.json \
  -o wechat-body.html
```

独立渲染会同时校验文章结构、计划结构和计划引用的真实资源；缺图或非法图片时不生成成功结果。
