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

    def test_valid_single_event_passes(self) -> None:
        exit_code, stdout, stderr = self.run_validator(copy.deepcopy(VALID_EVENT))
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("计算总分 21/30", stdout)

    def test_valid_event_array_passes(self) -> None:
        second_event = copy.deepcopy(VALID_EVENT)
        second_event["title"] = "第二个虚构测试事件"
        exit_code, stdout, stderr = self.run_validator([VALID_EVENT, second_event])
        self.assertEqual(0, exit_code, stderr)
        self.assertIn("共 2 个事件", stdout)

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

    def test_total_score_mismatch_fails(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["total_score"] = 30
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("与六个评分维度之和 21 不一致", stderr)

    def test_invalid_confidence_fails(self) -> None:
        event = copy.deepcopy(VALID_EVENT)
        event["confidence"] = "certain"
        exit_code, _stdout, stderr = self.run_validator(event)
        self.assertNotEqual(0, exit_code)
        self.assertIn("confidence", stderr)

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
