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

固定目标为 `image-prompts.md`，已有目标时拒绝覆盖。封面应为无文字横版编辑插画，建议接近 2.35:1；正文图应服务于计划中的用途和章节，不补写字幕之外的事实。

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
