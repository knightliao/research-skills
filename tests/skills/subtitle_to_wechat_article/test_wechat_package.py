"""公众号发布包两层模型、状态机和原子安装测试。"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".agents" / "skills" / "subtitle-to-wechat-article" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_wechat_package as builder
import render_wechat_html as renderer
import wechat_resources as resources


def png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def valid_png(width: int = 235, height: int = 100) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + (b"\x00\x00\x00" * width) for _ in range(height))
    return (
        resources.PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


def article_text(suffix: str = "") -> str:
    return f"""# 虚构文章标题{suffix}

## 第一节

这是第一段正文，包含足够清楚的语义。

这是第二段正文。

- 列表甲
- 列表乙

> 一段引用。

---

## 写在最后

这是结语。
"""


def plan_text() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "images": [
                {
                    "file": "images/body-01.png",
                    "purpose": "智能体工程示意",
                    "section": "第一节",
                    "insert_after_paragraph": 2,
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def prompt_text(body_count: int = 0) -> str:
    parts = ["## cover", "", "无文字横版编辑插画。", ""]
    for index in range(1, body_count + 1):
        parts.extend([f"## body-{index:02d}", "", f"第 {index} 张正文信息图。", ""])
    return "\n".join(parts)


class PackageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "虚构字幕.srt"
        self.article = self.root / "editable-article.md"
        self.plan = self.root / "editable-plan.json"
        self.output_root = self.root / "reports"
        self.source.write_text("1\n00:00:00,000 --> 00:00:01,000\n虚构字幕\n", encoding="utf-8")
        self.article.write_text(article_text(), encoding="utf-8")
        self.plan.write_text(plan_text(), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_package(self, mode: str = "cover-only") -> Path:
        return builder.create_package(
            self.source,
            self.article,
            self.output_root,
            mode=mode,
            illustration_plan=self.plan if mode == "body-images" else None,
        )

    def prepare_assets(self, package: Path) -> None:
        prompts = self.root / f"prompts-{package.name}.md"
        count = builder.load_manifest(package)["expected_body_image_count"]
        prompts.write_text(prompt_text(count), encoding="utf-8")
        cover = self.root / "cover-source.png"
        body = self.root / "body-source.png"
        cover.write_bytes(valid_png(235, 100))
        body.write_bytes(valid_png(160, 100))
        builder.set_prompts(package, prompts)
        builder.add_image(package, cover, "cover", None)
        for index in range(1, count + 1):
            builder.add_image(package, body, "body", index)


class PackageInitializationTests(PackageTestCase):
    def test_default_init_snapshots_editable_source_in_cover_only_mode(self) -> None:
        package = self.create_package()
        manifest = builder.load_manifest(package)
        self.assertEqual(2, manifest["schema_version"])
        self.assertEqual("cover-only", manifest["mode"])
        self.assertEqual(str(self.article.resolve()), manifest["article_source_file"])
        self.assertEqual(0, manifest["expected_body_image_count"])
        self.assertEqual({"file": None, "sha256": None, "image_count": 0}, manifest["illustration_plan"])
        self.assertEqual(["cover.png"], [item["file"] for item in manifest["images"]])
        self.assertEqual(builder.sha256_file(package / "article.md"), manifest["article_sha256"])

    def test_repeated_init_uses_current_source_and_never_changes_old_snapshot(self) -> None:
        first = self.create_package()
        first_bytes = (first / "article.md").read_bytes()
        self.article.write_text(article_text("（修订版）"), encoding="utf-8")
        second = self.create_package()
        third = self.create_package()
        self.assertEqual(["虚构字幕", "虚构字幕-v2", "虚构字幕-v3"], [first.name, second.name, third.name])
        self.assertEqual(first_bytes, (first / "article.md").read_bytes())
        self.assertIn("修订版", (second / "article.md").read_text(encoding="utf-8"))
        self.assertEqual([1, 2, 3], [builder.load_manifest(path)["package_version"] for path in (first, second, third)])

    def test_body_mode_requires_and_freezes_independent_plan(self) -> None:
        with self.assertRaises(builder.PackageError) as context:
            builder.create_package(self.source, self.article, self.output_root, mode="body-images")
        self.assertEqual("ILLUSTRATION_PLAN_INVALID", context.exception.code)
        package = self.create_package("body-images")
        manifest = builder.load_manifest(package)
        self.assertEqual("body-images", manifest["mode"])
        self.assertEqual(1, manifest["expected_body_image_count"])
        self.assertEqual("illustration-plan.json", manifest["illustration_plan"]["file"])
        self.assertEqual(plan_text(), (package / "illustration-plan.json").read_text(encoding="utf-8"))
        self.assertEqual("智能体工程示意", manifest["images"][1]["purpose"])

    def test_safe_stem_limits_characters_bytes_and_controls(self) -> None:
        self.assertEqual("abc-def", builder.sanitize_stem("abc\u200b\\def.srt"))
        self.assertEqual(80, len(builder.sanitize_stem(("a" * 100) + ".srt")))
        cjk = builder.sanitize_stem(("中" * 100) + ".srt")
        self.assertLessEqual(len(cjk), 80)
        self.assertLessEqual(len(cjk.encode("utf-8")), 180)
        self.assertEqual("subtitle", builder.sanitize_stem("\u200b\x00.srt"))

    def test_init_cli_stdout_only_contains_absolute_package_path(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = builder.main([
                "init", "--source", str(self.source), "--article", str(self.article),
                "--output-root", str(self.output_root),
            ])
        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertTrue(Path(stdout.getvalue().strip()).is_absolute())


class RebuildTests(PackageTestCase):
    def test_rebuild_uses_old_snapshot_by_default_without_modifying_old_package(self) -> None:
        old = self.create_package()
        before = {path.relative_to(old): path.read_bytes() for path in old.rglob("*") if path.is_file()}
        rebuilt = builder.rebuild_package(old)
        self.assertEqual("虚构字幕-v2", rebuilt.name)
        self.assertEqual((old / "article.md").read_bytes(), (rebuilt / "article.md").read_bytes())
        self.assertEqual(before, {path.relative_to(old): path.read_bytes() for path in old.rglob("*") if path.is_file()})

    def test_rebuild_accepts_new_source_and_mode_switch_as_new_version(self) -> None:
        old = self.create_package()
        self.article.write_text(article_text("（新源稿）"), encoding="utf-8")
        rebuilt = builder.rebuild_package(
            old,
            article=self.article,
            mode="body-images",
            illustration_plan=self.plan,
        )
        manifest = builder.load_manifest(rebuilt)
        self.assertEqual("body-images", manifest["mode"])
        self.assertEqual(str(self.article.resolve()), manifest["article_source_file"])
        self.assertIn("新源稿", (rebuilt / "article.md").read_text(encoding="utf-8"))
        self.assertEqual("cover-only", builder.load_manifest(old)["mode"])

    def test_rebuild_cli_prints_only_new_path(self) -> None:
        old = self.create_package()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = builder.main(["rebuild", str(old)])
        self.assertEqual(0, code, stderr.getvalue())
        self.assertEqual("虚构字幕-v2", Path(stdout.getvalue().strip()).name)

    def test_rebuild_reads_legacy_cover_only_snapshot_without_modifying_it(self) -> None:
        legacy = self.root / "legacy-package"
        legacy.mkdir()
        (legacy / "article.md").write_text(article_text(), encoding="utf-8")
        legacy_manifest = {
            "schema_version": 1,
            "source_file": str(self.source.resolve()),
            "expected_body_image_count": 0,
        }
        (legacy / "manifest.json").write_text(
            json.dumps(legacy_manifest, ensure_ascii=False), encoding="utf-8"
        )
        before = (legacy / "manifest.json").read_bytes()
        rebuilt = builder.rebuild_package(legacy)
        self.assertEqual("cover-only", builder.load_manifest(rebuilt)["mode"])
        self.assertEqual(before, (legacy / "manifest.json").read_bytes())


class PromptAndImageTests(PackageTestCase):
    def test_set_prompts_exact_roles_and_no_overwrite(self) -> None:
        package = self.create_package("body-images")
        prompts = self.root / "prompts.md"
        prompts.write_text(prompt_text(1), encoding="utf-8")
        builder.set_prompts(package, prompts)
        self.assertEqual(["cover", "body-01"], builder.load_manifest(package)["prompts"]["roles"])
        with self.assertRaises(builder.PackageError) as context:
            builder.set_prompts(package, prompts)
        self.assertEqual("TARGET_EXISTS", context.exception.code)

    def test_add_image_records_metadata_and_cover_mode_rejects_body(self) -> None:
        cover_package = self.create_package()
        body = self.root / "body.png"
        body.write_bytes(valid_png(160, 100))
        with self.assertRaises(builder.PackageError) as context:
            builder.add_image(cover_package, body, "body", 1)
        self.assertEqual("INDEX_OUT_OF_RANGE", context.exception.code)

        body_package = self.create_package("body-images")
        builder.add_image(body_package, body, "body", 1)
        item = builder.load_manifest(body_package)["images"][1]
        self.assertEqual("ready", item["status"])
        self.assertEqual((160, 100), (item["width"], item["height"]))

    def test_existing_target_is_never_overwritten(self) -> None:
        package = self.create_package()
        target = package / "cover.png"
        target.write_bytes(b"unknown")
        source = self.root / "valid.png"
        source.write_bytes(valid_png())
        with self.assertRaises(builder.PackageError) as context:
            builder.add_image(package, source, "cover", None)
        self.assertEqual("TARGET_EXISTS", context.exception.code)
        self.assertEqual(b"unknown", target.read_bytes())

    def test_install_cleanup_on_validation_fsync_and_replace_failures(self) -> None:
        source = self.root / "source.bin"
        source.write_bytes(b"content")
        for failure in ("validation", "fsync", "replace"):
            with self.subTest(failure=failure):
                target_dir = self.root / failure
                target_dir.mkdir()
                target = target_dir / "target.bin"
                validator = mock.Mock(return_value=True)
                fsync = mock.patch.object(builder.os, "fsync", wraps=os.fsync)
                replace = mock.patch.object(builder.os, "replace", wraps=os.replace)
                if failure == "validation":
                    validator.side_effect = ValueError("invalid")
                elif failure == "fsync":
                    fsync = mock.patch.object(builder.os, "fsync", side_effect=OSError("fsync failed"))
                else:
                    replace = mock.patch.object(builder.os, "replace", side_effect=OSError("replace failed"))
                with fsync, replace, self.assertRaises(Exception):
                    builder.install_file_no_overwrite(source, target, validator)
                self.assertFalse(target.exists())
                self.assertEqual([], [path for path in target_dir.iterdir() if builder._is_internal(path)])


class FinalizeStateMachineTests(PackageTestCase):
    def test_cover_only_finalize_and_complete_read_only(self) -> None:
        package = self.create_package()
        self.prepare_assets(package)
        builder.finalize_package(package)
        manifest = builder.load_manifest(package)
        self.assertEqual("complete", manifest["status"])
        self.assertEqual([], manifest["errors"])
        self.assertTrue((package / "wechat-body.html").is_file())
        self.assertNotIn("正文图片位置", (package / "publish-guide.md").read_text(encoding="utf-8"))
        before = (package / "manifest.json").read_bytes()
        prompts = self.root / "other.md"
        prompts.write_text(prompt_text(), encoding="utf-8")
        image = self.root / "other.png"
        image.write_bytes(valid_png())
        for operation in (
            lambda: builder.set_prompts(package, prompts),
            lambda: builder.add_image(package, image, "cover", None),
            lambda: builder.record_failure(package, "失败"),
            lambda: builder.finalize_package(package),
        ):
            with self.subTest(operation=operation), self.assertRaises(builder.PackageError) as context:
                operation()
            self.assertEqual("PACKAGE_COMPLETE", context.exception.code)
            self.assertEqual(before, (package / "manifest.json").read_bytes())

    def test_body_plan_drives_html_insertion_and_publish_guide(self) -> None:
        package = self.create_package("body-images")
        self.prepare_assets(package)
        builder.finalize_package(package)
        html = (package / "wechat-body.html").read_text(encoding="utf-8")
        self.assertIn('src="images/body-01.png"', html)
        self.assertGreater(html.index('src="images/body-01.png"'), html.index("这是第二段正文"))
        guide = (package / "publish-guide.md").read_text(encoding="utf-8")
        self.assertIn("第一节", guide)
        self.assertIn("第 2 个普通段落之后", guide)

    def test_snapshot_and_plan_hash_mismatch_require_new_package(self) -> None:
        article_package = self.create_package()
        (article_package / "article.md").write_text(article_text("（篡改）"), encoding="utf-8")
        with self.assertRaises(builder.PackageError) as context:
            builder.finalize_package(article_package)
        self.assertEqual("ARTICLE_HASH_MISMATCH", context.exception.code)

        plan_package = self.create_package("body-images")
        (plan_package / "illustration-plan.json").write_text(
            plan_text().replace("智能体工程示意", "被修改"), encoding="utf-8"
        )
        with self.assertRaises(builder.PackageError):
            builder.finalize_package(plan_package)
        codes = {item["code"] for item in builder.load_manifest(plan_package)["errors"]}
        self.assertIn("ILLUSTRATION_PLAN_HASH_MISMATCH", codes)

    def test_finalize_errors_are_current_and_retryable(self) -> None:
        package = self.create_package()
        with self.assertRaises(builder.PackageError):
            builder.finalize_package(package)
        self.assertIn("PROMPTS_MISSING", {item["code"] for item in builder.load_manifest(package)["errors"]})
        self.prepare_assets(package)
        self.assertEqual([], builder.load_manifest(package)["errors"])
        builder.finalize_package(package)
        self.assertEqual("complete", builder.load_manifest(package)["status"])

    def test_extra_image_and_internal_temp_block_finalize(self) -> None:
        for kind in ("extra", "temporary"):
            with self.subTest(kind=kind):
                package = self.create_package()
                self.prepare_assets(package)
                if kind == "extra":
                    (package / "images" / "body-99.png").write_bytes(valid_png())
                    expected = "EXTRA_IMAGE_ASSET"
                else:
                    (package / (".orphan.wechat-tmp-" + "a" * 32)).write_bytes(b"temporary")
                    expected = "INTERNAL_TEMP_PRESENT"
                with self.assertRaises(builder.PackageError):
                    builder.finalize_package(package)
                self.assertIn(expected, {item["code"] for item in builder.load_manifest(package)["errors"]})

    def test_manifest_format_and_renderer_complete_guard(self) -> None:
        package = self.create_package()
        self.prepare_assets(package)
        builder.finalize_package(package)
        raw = (package / "manifest.json").read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertIn("虚构文章标题".encode("utf-8"), raw)
        self.assertNotIn(b"\\u", raw)
        manifest = json.loads(raw)
        self.assertEqual(sorted(manifest["files"]), manifest["files"])
        stdout, stderr = io.StringIO(), io.StringIO()
        output = package / "another.html"
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = renderer.main([str(package / "article.md"), "-o", str(output)])
        self.assertNotEqual(0, code)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("PACKAGE_COMPLETE", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
