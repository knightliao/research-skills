"""研究事件 JSON 校验命令行工具的自动化测试。"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = (
    ROOT
    / ".agents"
    / "skills"
    / "global-ai-agent-radar"
    / "scripts"
    / "validate_events.py"
)


def load_validator_module():
    """从 Skill 路径加载待测脚本。"""

    spec = importlib.util.spec_from_file_location("validate_events_under_test", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 validate_events.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = load_validator_module()

VALID_EVENT = {
    "title": "虚构测试事件",
    "event_date": "2026-01-10",
    "publication_date": "2026-01-10",
    "source_url": "https://example.invalid/official-event",
    "source_type": "official",
    "additional_sources": [
        {
            "url": "https://independent.example.invalid/review",
            "type": "media",
            "role": "independent",
            "publication_date": "2026-01-10",
        }
    ],
    "facts": ["这是明确标记的自动化测试事实。"],
    "inference": "这是明确标记的自动化测试推断。",
    "scores": {
        "novelty": 4,
        "product_impact": 4,
        "engineering_impact": 3,
        "commercialization_impact": 3,
        "ecosystem_impact": 2,
        "credibility": 5,
    },
    "total_score": 21,
    "confidence": "high",
    "follow_up_signals": ["检查后续公开测试结果。"],
}


class ValidateEventsTests(unittest.TestCase):
    def run_validator(self, payload, *, raw: bool = False):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "events.json"
            if raw:
                path.write_text(payload, encoding="utf-8")
            else:
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = validator.main([str(path)])
        return exit_code, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def event_with_scores(scores: dict[str, int], *, confidence: str = "high") -> dict:
        event = copy.deepcopy(VALID_EVENT)
        event["scores"] = scores
        event["total_score"] = sum(scores.values())
        event["confidence"] = confidence
        return event

    def test_score_fields_are_exactly_six_and_exclude_confidence(self) -> None:
        self.assertEqual(
            (
                "novelty",
                "product_impact",
                "engineering_impact",
                "commercialization_impact",
                "ecosystem_impact",
                "credibility",
            ),
            validator.SCORE_FIELDS,
        )
        self.assertNotIn("confidence", validator.SCORE_FIELDS)

    def test_valid_single_event_passes_and_is_general_event(self) -> None:
        exit_code, stdout, stderr = self.run_validator(copy.deepcopy(VALID_EVENT))
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("重算总分 21/30", stdout)
        self.assertIn("分类 一般重要事件", stdout)

    def test_valid_event_array_passes(self) -> None:
        second_event = copy.deepcopy(VALID_EVENT)
        second_event["title"] = "第二个虚构测试事件"
        second_event["source_url"] = "https://example.invalid/second-event"
        exit_code, stdout, stderr = self.run_validator([VALID_EVENT, second_event])
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("共 2 个事件", stdout)

    def test_empty_array_is_successful_empty_result_without_warning(self) -> None:
        exit_code, stdout, stderr = self.run_validator([])
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("空结果状态", stdout)
        self.assertIn("0 个最终条目", stdout)
        self.assertNotIn("警告：", stdout)

    def test_missing_required_field_fails(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        del event["title"]
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("缺少必填字段 title", stderr)
        self.assertIn("事件 1", stderr)

    def test_invalid_date_fails(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["event_date"] = "2026-02-30"
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("event_date", stderr)

    def test_invalid_url_fails(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["source_url"] = "ftp://example.invalid/event"
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("source_url", stderr)

    def test_invalid_facts_type_fails(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["facts"] = "不是列表"
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("facts 必须是列表", stderr)

    def test_score_out_of_range_fails(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["scores"]["novelty"] = 6
        event.pop("total_score")
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("novelty 必须在 0 至 5", stderr)

    def test_total_score_mismatch_fails_and_cannot_control_classification(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["total_score"] = 30
        exit_code, stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("重算总分 21/30", stdout)
        self.assertIn("分类 一般重要事件", stdout)
        self.assertIn("与六个评分维度之和 21 不一致", stderr)

    def test_missing_total_score_uses_recalculated_total(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        del event["total_score"]
        exit_code, stdout, stderr = self.run_validator(event)
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("重算总分 21/30；分类 一般重要事件", stdout)

    def test_invalid_confidence_fails(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["confidence"] = "certain"
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("confidence", stderr)

    def test_total_24_with_low_confidence_is_follow_up_signal(self) -> None:
        event = self.event_with_scores(
            {
                "novelty": 4,
                "product_impact": 4,
                "engineering_impact": 4,
                "commercialization_impact": 4,
                "ecosystem_impact": 3,
                "credibility": 5,
            },
            confidence="low",
        )
        exit_code, stdout, stderr = self.run_validator(event)
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("重算总分 24/30；分类 待验证信号", stdout)
        self.assertNotIn("分类 重点事件", stdout)

    def test_total_23_with_low_confidence_is_follow_up_signal(self) -> None:
        event = self.event_with_scores(
            {
                "novelty": 4,
                "product_impact": 4,
                "engineering_impact": 4,
                "commercialization_impact": 3,
                "ecosystem_impact": 3,
                "credibility": 5,
            },
            confidence="low",
        )
        exit_code, stdout, stderr = self.run_validator(event)
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("重算总分 23/30；分类 待验证信号", stdout)
        self.assertNotIn("分类 一般重要事件", stdout)

    def test_credibility_two_overrides_high_total(self) -> None:
        event = self.event_with_scores(
            {
                "novelty": 5,
                "product_impact": 5,
                "engineering_impact": 5,
                "commercialization_impact": 5,
                "ecosystem_impact": 5,
                "credibility": 2,
            }
        )
        exit_code, stdout, stderr = self.run_validator(event)
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("重算总分 27/30；分类 待验证信号", stdout)

    def test_credibility_zero_or_one_is_rejected(self) -> None:
        for credibility in (0, 1):
            with self.subTest(credibility=credibility):
                event = self.event_with_scores(
                    {
                        "novelty": 5,
                        "product_impact": 5,
                        "engineering_impact": 5,
                        "commercialization_impact": 5,
                        "ecosystem_impact": 5,
                        "credibility": credibility,
                    }
                )
                exit_code, _stdout, stderr = self.run_validator(event)
                self.assertNotEqual(0, exit_code)
                self.assertIn("不得进入最终事件清单", stderr)

    def test_additional_source_fields_are_validated(self) -> None:
        invalid_values = (
            ("url", "ftp://example.invalid/source", "url 必须是有效"),
            ("type", "newsletter", ".type"),
            ("role", "confirmation", ".role"),
            ("publication_date", "2026-02-30", "publication_date"),
        )
        for field_name, value, expected_message in invalid_values:
            with self.subTest(field_name=field_name):
                event = copy.deepcopy(VALID_EVENT)
                event["additional_sources"][0][field_name] = value
                exit_code, _stdout, stderr = self.run_validator(event)
                self.assertNotEqual(0, exit_code)
                self.assertIn(expected_message, stderr)

    def test_primary_url_and_additional_url_are_deduplicated_conservatively(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["source_url"] = " https://Example.invalid/resource#announcement "
        event["additional_sources"][0]["url"] = "https://example.invalid/resource#review"
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("与“主要来源 source_url”重复", stderr)

    def test_duplicate_additional_urls_fail(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["additional_sources"].append(
            {
                "url": "https://INDEPENDENT.example.invalid/review#second",
                "type": "community",
                "role": "background",
            }
        )
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("与“additional_sources 的第 1 项”重复", stderr)

    def test_trailing_slash_is_not_assumed_equivalent(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["source_url"] = "https://example.invalid/resource"
        event["additional_sources"][0]["url"] = "https://example.invalid/resource/"
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertEqual(0, exit_code, stderr)

    def test_additional_primary_does_not_replace_top_level_primary_source(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        del event["source_url"]
        event["additional_sources"] = [
            {
                "url": "https://example.invalid/another-primary",
                "type": "documentation",
                "role": "primary",
            }
        ]
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("缺少必填字段 source_url", stderr)

    def test_independent_source_check_is_only_a_structure_declaration(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["additional_sources"][0]["url"] = "https://unverified.example.invalid/claim"
        exit_code, stdout, stderr = self.run_validator(event)
        self.assertEqual(0, exit_code, stderr)
        self.assertNotIn("未在 additional_sources 中声明", stdout)

    def test_general_event_without_independent_declaration_warns(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        del event["additional_sources"]
        exit_code, stdout, stderr = self.run_validator(event)
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("未在 additional_sources 中声明 role=independent", stdout)
        self.assertIn("只确认结构声明", stdout)

    def test_warnings_do_not_change_success_exit_code(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["event_date"] = "2026-01-11"
        event["follow_up_signals"] = []
        exit_code, stdout, stderr = self.run_validator(event)
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("警告", stdout)
        self.assertIn("2 个警告", stdout)

    def test_unparseable_json_fails(self) -> None:
        exit_code, _stdout, stderr = self.run_validator("{not-json", raw=True)
        self.assertNotEqual(0, exit_code)
        self.assertIn("无法解析 JSON", stderr)


if __name__ == "__main__":
    unittest.main()
