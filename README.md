# 研究型 Skills

用于集中管理多个独立研究型 Agent Skill 的 Monorepo。

## Skills 列表

- `global-ai-agent-radar`：识别最近 24–72 小时全球 AI Agent 领域真正有意义的变化，为技术负责人、产品负责人和投资人提供增量雷达。

## 校验

项目要求 Python 3.11 或更高版本，且仅使用 Python 标准库。

```bash
python3 -m unittest discover -s tests
python3 tools/validate_all_skills.py
```
