#!/usr/bin/env python3
"""check_metrics.py 单测：同族指标分母一致性启发式 + 基础闸门行为"""
import contextlib, io, json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_metrics


def write_json(d, name, obj):
    fp = os.path.join(d, name)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


class CheckMetricsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def run_main(self, metrics_doc):
        write_json(self.dir, "metrics.json", metrics_doc)
        buf = io.StringIO()
        code = None
        with contextlib.redirect_stdout(buf):
            argv = sys.argv
            sys.argv = ["check_metrics.py", self.dir]
            try:
                check_metrics.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
            finally:
                sys.argv = argv
        return code, buf.getvalue()

    def test_family_denominator_mismatch_warns(self):
        """实机案例：达成率裁决用[预算数]，收入达成率仍用[35预算数] → ⚠️（不阻断）"""
        code, out = self.run_main({"metrics": [
            {"name": "达成率", "formula": "sum([实际数])/sum([预算数])"},
            {"name": "收入达成率",
             "formula": "sum(if([管报科目编码]='Fin15',[实际数],0))/sum(if([管报科目编码]='Fin15',[35预算数],0))"},
        ], "rejected": []})
        self.assertIsNone(code, out)  # ⚠️ 不阻断
        self.assertIn("同族指标分母不一致", out)
        self.assertIn("收入达成率", out)

    def test_family_consistent_no_warning(self):
        code, out = self.run_main({"metrics": [
            {"name": "达成率", "formula": "sum([实际数])/sum([预算数])"},
            {"name": "收入达成率", "formula": "sum([收入])/sum([预算数])"},
        ], "rejected": []})
        self.assertIsNone(code, out)
        self.assertNotIn("同族指标分母不一致", out)

    def test_unrelated_names_no_warning(self):
        """名称不包含 = 不同族，分母不同也不报"""
        code, out = self.run_main({"metrics": [
            {"name": "毛利率", "formula": "sum([毛利])/sum([预算数])"},
            {"name": "达成率", "formula": "sum([实际数])/sum([35预算数])"},
        ], "rejected": []})
        self.assertIsNone(code, out)
        self.assertNotIn("同族指标分母不一致", out)

    def test_pending_conflict_blocks(self):
        code, out = self.run_main({"metrics": [
            {"name": "退款率", "pending": True},
        ], "rejected": []})
        self.assertEqual(code, 1)
        self.assertIn("pending", out)


if __name__ == "__main__":
    unittest.main()
