#!/usr/bin/env python3
"""
workbench.py 最小单测：数据收集/体检/保存回调的关键路径。
运行: python3 -m unittest discover -s references/scripts -p 'test_*.py' -v
不触网：guancli 调用一律打桩（monkeypatch page_snapshot / 提供 biBaseUrl 跳过 auth 探测）。
"""
import json, os, sys, tempfile, time, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_page
import workbench as wb


def write_json(d, name, obj):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


class TestPureHelpers(unittest.TestCase):
    def test_structure_hash_order_insensitive(self):
        a = [{"cdId": "c1", "name": "净收入"}, {"cdId": "c2", "name": "毛利率"}]
        b = list(reversed(a))
        self.assertEqual(wb._structure_hash(a), wb._structure_hash(b))

    def test_structure_hash_consistent_with_parse_page(self):
        cards = [{"cdId": "b", "name": "x"}, {"cdId": "a", "name": "y"}]
        self.assertEqual(parse_page._structure_hash(cards), wb._structure_hash(cards))

    def test_ver_tuple(self):
        self.assertLess(wb._ver_tuple("3.0.0"), wb._ver_tuple("3.1.0"))
        self.assertEqual(wb._ver_tuple("garbage"), ())
        self.assertLess(wb._ver_tuple(""), wb._ver_tuple("0.0.1"))

    def test_diff_cards(self):
        old = [{"cdId": "c1", "name": "A"}, {"cdId": "c2", "name": "B"}, {"cdId": "c3", "name": "C"}]
        new = [{"cdId": "c1", "name": "A"}, {"cdId": "c2", "name": "B2"}, {"cdId": "c4", "name": "D"}]
        ch = wb._diff_cards(old, new)
        self.assertEqual(ch["added"], ["D"])
        self.assertEqual(ch["removed"], ["C"])
        self.assertEqual(ch["renamed"], ["B→B2"])


class TestCheckStaleness(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self._orig = wb.page_snapshot
        self.addCleanup(setattr, wb, "page_snapshot", self._orig)

    def _fixture(self, pages, built_days_ago=40, builder_version="3.0.0"):
        built = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - built_days_ago * 86400))
        write_json(self.dir, "cards.json", {"_meta": {
            "builtAt": built, "builderVersion": builder_version,
            "biBaseUrl": "https://bi.example.com", "pages": pages}})

    def test_stale_with_card_diff(self):
        learned = [{"cdId": "c1", "name": "净收入"}, {"cdId": "c2", "name": "毛利率"}]
        self._fixture({"pgA": {"title": "经营驾驶舱", "mtime": "2026-09-01 10:00",
                               "cardCount": 2, "cardHash": wb._structure_hash(learned),
                               "cards": learned},
                       "pgB": {"title": "渠道分析", "mtime": "2026-09-10 12:00"}})
        def fake(pg):
            if pg == "pgA":
                return {"mtime": "2026-09-20 09:00", "error": False,
                        "cards": [{"cdId": "c1", "name": "净收入"}, {"cdId": "c3", "name": "退款分析"}]}
            return {"mtime": "2026-09-10 12:00", "cards": [], "error": False}
        wb.page_snapshot = fake
        r = wb.check_staleness(self.dir, fresh_days=30)
        pa, pb = r["pages"]
        self.assertTrue(pa["stale"])
        self.assertEqual(pa["changes"]["added"], ["退款分析"])
        self.assertEqual(pa["changes"]["removed"], ["毛利率"])
        self.assertIn("新增 1 张", pa["detail"])
        self.assertFalse(pb["stale"])
        self.assertTrue(r["overdue"])
        self.assertTrue(r["upgradeAvailable"])

    def test_config_only_change(self):
        learned = [{"cdId": "c1", "name": "净收入"}]
        self._fixture({"pgA": {"title": "P", "mtime": "t0", "cards": learned}}, built_days_ago=5)
        wb.page_snapshot = lambda pg: {"mtime": "t1", "error": False, "cards": list(learned)}
        r = wb.check_staleness(self.dir)
        self.assertEqual(r["pages"][0]["detail"], "卡片清单未变，是配置/布局调整")
        self.assertFalse(r["overdue"])

    def test_legacy_meta_degrades(self):
        self._fixture({"pgA": {"title": "P", "mtime": "t0"}}, built_days_ago=5,
                      builder_version="")
        wb.page_snapshot = lambda pg: {"mtime": "t1", "cards": [{"cdId": "x", "name": "y"}],
                                       "error": False}
        r = wb.check_staleness(self.dir)
        p = r["pages"][0]
        self.assertTrue(p["stale"])
        self.assertIsNone(p["changes"])
        self.assertIn("旧版档案", p["detail"])
        # 未记录 builderVersion 的老包应提示可升级
        self.assertTrue(r["upgradeAvailable"])

    def test_error_page(self):
        self._fixture({"pgA": {"title": "P", "mtime": "t0"}}, built_days_ago=5)
        wb.page_snapshot = lambda pg: {"mtime": None, "cards": None, "error": True}
        r = wb.check_staleness(self.dir)
        self.assertTrue(r["pages"][0]["error"])
        self.assertFalse(r["pages"][0]["stale"])

    def test_accel_stats_included(self):
        # v4.2 取数加速层环境指标：复用率 + 卡片级/数据集级分级（纯本地计算）
        self._fixture({"pgA": {"title": "P", "mtime": "t0"}}, built_days_ago=5)
        write_json(self.dir, "cards.json", {
            "看板A": {"pgId": "pgA", "cards": {
                "卡1": {"cdId": "c1", "type": "PIE", "dsId": "ds1", "filtered": False},
                "卡2": {"cdId": "c2", "type": "BASIC_BAR", "dsId": "ds1", "filtered": True},
                "卡3": {"cdId": "c3", "type": "PIVOT_TABLE", "dsId": "ds2", "filtered": False},
                "筛1": {"cdId": "c4", "type": "SELECTOR", "dsId": "ds9"},
            }},
            "_meta": {"builtAt": "2026-09-01 10:00", "builderVersion": "4.2.0", "pages": {}}})
        wb.page_snapshot = lambda pg: {"mtime": "t0", "cards": [], "error": False}
        r = wb.check_staleness(self.dir)
        ac = r["accel"]
        self.assertEqual(ac["dataCards"], 3)
        self.assertEqual(ac["datasets"], 2)
        self.assertAlmostEqual(ac["reuseRate"], 0.667)
        self.assertEqual(ac["filteredCards"], 1)
        self.assertEqual(ac["datasetLevelCards"], 2)

    def test_accel_stats_legacy_without_filtered(self):
        # 旧档案无 filtered 字段：分级记 None（提示重新学习补齐），复用率照算
        doc = {"看板A": {"cards": [{"cdId": "c1", "type": "PIE", "dsId": "ds1"},
                                   {"cdId": "c2", "type": "PIE", "dsId": "ds1"}]},
               "_meta": {}}
        ac = wb._accel_stats(doc)
        self.assertAlmostEqual(ac["reuseRate"], 1.0)
        self.assertIsNone(ac["filteredCards"])

    def test_accel_stats_none_without_dsid(self):
        self.assertIsNone(wb._accel_stats({"看板A": {"cards": [{"cdId": "c1", "type": "PIE"}]}}))


class TestCollectAndSave(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))

    def test_collect_reads_meta_and_files(self):
        write_json(self.dir, "cards.json", {"_meta": {"biBaseUrl": "https://bi.example.com",
                                                      "pages": {"pgA": {"title": "P", "mtime": "t"}}},
                                            "P": {"pgId": "pgA", "cards": {}}})
        write_json(self.dir, "metrics.json", {"metrics": [{"name": "x"}]})
        with open(os.path.join(self.dir, "businessKnowledge.md"), "w", encoding="utf-8") as f:
            f.write("1. 口径一\n2. 口径二\n")
        data = wb.collect(self.dir)
        self.assertEqual(data["biBaseUrl"], "https://bi.example.com")  # meta 提供，不触发 guancli
        self.assertIn("metrics.json", data["files"])
        self.assertIn("businessKnowledge.md", data["files"])
        self.assertIn("P", data["assets"])

    def test_save_file_backup_and_whitelist(self):
        fp = os.path.join(self.dir, "businessKnowledge.md")
        with open(fp, "w", encoding="utf-8") as f:
            f.write("旧内容")
        write_json(self.dir, "metrics.json", {"metrics": []})
        save = wb.make_save_file(self.dir)
        r = save("businessKnowledge.md", "新内容")
        self.assertTrue(r["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, r["backup"])))
        with open(fp, encoding="utf-8") as f:
            self.assertEqual(f.read(), "新内容")
        # 白名单外/路径穿越拒绝
        self.assertFalse(save("evil.py", "x")["ok"])
        self.assertFalse(save("../escape.md", "x")["ok"])
        # 非法 JSON 拒绝且不落盘
        with self.assertRaises(json.JSONDecodeError):
            save("metrics.json", "{not json")

    def _make_memory(self, parent):
        memdir = os.path.join(parent, "memory")
        os.makedirs(memdir, exist_ok=True)
        with open(os.path.join(memdir, "profile.md"), "w", encoding="utf-8") as f:
            f.write("# 用户画像\n\n## 关注重点\n- 收入\n")
        with open(os.path.join(memdir, "qa-log.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"ts":"2026-09-25T10:00:00+08:00","question":"华东收入多少","route":"《销售》/卡1","note":"710万"}\n')
            f.write('坏行不是JSON\n')
        write_json(memdir, "corrections.json", {"corrections": [
            {"ts": "2026-09-25T11:00:00+08:00", "type": "口径",
             "before": "÷收入", "after": "÷GMV", "target": "metrics.json"}]})
        return memdir

    def test_collect_reads_memory_in_workdir(self):
        write_json(self.dir, "cards.json", {"_meta": {"biBaseUrl": "https://bi.example.com"}})
        self._make_memory(self.dir)
        data = wb.collect(self.dir)
        mem = data["memory"]
        self.assertIsNotNone(mem)
        self.assertIn("用户画像", mem["profile"])
        self.assertEqual(mem["qaLogTotal"], 1)          # 坏行跳过
        self.assertEqual(mem["qaLog"][0]["note"], "710万")
        self.assertEqual(mem["corrections"][0]["after"], "÷GMV")

    def test_collect_memory_via_references_parent(self):
        # 交付包形态：workdir 是 <pkg>/references，memory/ 在包根
        pkg = os.path.join(self.dir, "agent-demo")
        ref = os.path.join(pkg, "references")
        os.makedirs(ref)
        write_json(ref, "cards.json", {"_meta": {"biBaseUrl": "https://bi.example.com"}})
        self._make_memory(pkg)
        data = wb.collect(ref)
        self.assertIsNotNone(data["memory"])
        self.assertEqual(data["memory"]["qaLogTotal"], 1)

    def test_save_memory_profile_with_backup(self):
        pkg = os.path.join(self.dir, "agent-demo")
        ref = os.path.join(pkg, "references")
        os.makedirs(ref)
        write_json(ref, "cards.json", {"_meta": {"biBaseUrl": "https://bi.example.com"}})
        memdir = self._make_memory(pkg)
        save = wb.make_save_file(ref)
        r = save("memory/profile.md", "# 改后的画像\n")
        self.assertTrue(r["ok"])
        with open(os.path.join(memdir, "profile.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# 改后的画像\n")
        self.assertTrue(os.path.exists(os.path.join(memdir, os.path.basename(r["backup"]))))
        # 流水与台账是 append-only，工作台禁止写
        self.assertFalse(save("memory/qa-log.jsonl", "x")["ok"])
        self.assertFalse(save("memory/corrections.json", "{}")["ok"])
        self.assertFalse(save("memory/_meta.json", "{}")["ok"])

    def test_save_memory_profile_rejected_without_memory_dir(self):
        write_json(self.dir, "cards.json", {"_meta": {"biBaseUrl": "https://bi.example.com"}})
        save = wb.make_save_file(self.dir)
        self.assertFalse(save("memory/profile.md", "x")["ok"])


if __name__ == "__main__":
    unittest.main()
