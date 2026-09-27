#!/usr/bin/env python3
"""scope_audit.py 单测：越界 page/ds 检出、干净流水通过、旧条目无法判定计数、缺文件降级"""
import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scope_audit


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def make_agent_dir(with_log=True, log_lines=None):
    d = tempfile.mkdtemp()
    write_json(os.path.join(d, "references", "cards.json"), {
        "_meta": {"pages": {"p1": {"title": "页一"}}},
        "页一": {"title": "页一", "pgId": "p1", "dsUsage": {"ds1": {"cards": 1, "filteredCards": 0}},
                 "cards": [{"name": "卡A", "cdId": "c1", "type": "TABLE"}]}})
    if with_log:
        os.makedirs(os.path.join(d, "memory"))
        lines = log_lines if log_lines is not None else []
        with open(os.path.join(d, "memory", "qa-log.jsonl"), "w", encoding="utf-8") as f:
            for e in lines:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return d


class AuditTest(unittest.TestCase):
    def test_out_of_scope_page_and_ds_detected(self):
        d = make_agent_dir(log_lines=[
            {"ts": "2026-09-27 10:0", "question": "覆盖内问题", "page": "p1", "ds": "ds1"},
            {"ts": "2026-09-27 10:1", "question": "越界看板问题", "page": "p_evil"},
            {"ts": "2026-09-27 10:2", "question": "越界数据集问题", "ds": "ds_evil"},
        ])
        entries, result = scope_audit.audit(d)
        self.assertEqual(len(entries), 3)
        self.assertEqual(len(result["violations"]), 2)
        self.assertEqual(result["violations"][0]["question"], "越界看板问题")
        self.assertIn("page p_evil", result["violations"][0]["reason"])
        self.assertIn("ds ds_evil", result["violations"][1]["reason"])
        self.assertEqual(result["unknown"], 0)

    def test_clean_log_passes(self):
        d = make_agent_dir(log_lines=[
            {"ts": "t1", "question": "q1", "page": "p1", "ds": "ds1"},
            {"ts": "t2", "question": "q2", "page": "p1"},
        ])
        entries, result = scope_audit.audit(d)
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["unknown"], 0)

    def test_legacy_entries_without_fields_counted_unknown(self):
        # 旧流水无 --page/--ds 字段：不误报、计入"无法判定"
        d = make_agent_dir(log_lines=[
            {"ts": "t1", "question": "旧问题", "route": "《页一》/卡A"},
        ])
        entries, result = scope_audit.audit(d)
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["unknown"], 1)

    def test_missing_log_returns_none_entries(self):
        d = make_agent_dir(with_log=False)
        entries, result = scope_audit.audit(d)
        self.assertIsNone(entries)

    def test_missing_scope_returns_none_result(self):
        d = tempfile.mkdtemp()  # 无 references/cards.json
        os.makedirs(os.path.join(d, "memory"))
        with open(os.path.join(d, "memory", "qa-log.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "t", "question": "q"}) + "\n")
        entries, result = scope_audit.audit(d)
        self.assertEqual(len(entries), 1)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
