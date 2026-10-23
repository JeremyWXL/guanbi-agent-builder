#!/usr/bin/env python3
"""audit_insight_pages.py 的单测（夹具驱动，不依赖 BI 网络）

覆盖计划 7.1 的 16 项：缺 cards-raw exit 2 / 11 页 R-01 / 无联动筛选器 R-02 /
有联动筛选器不误报 / 隐藏筛选器只告警 / 无时间筛选 P0 / 21 卡 P0 与 13 卡 P1 /
明细 12000 行 P0 与未采样 P2 / 跨页口径冲突 / PARAM_DEPENDENT 无承接 / 跨页重复卡 /
跨页无共享维度 / 卡名问题 / 评分确定性与等级边界 / --seed-advice 结构 /
真实夹具 _preview/_sandbox-v4.9.1 可跑通且不误报 R-02。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_insight_pages as audit_mod

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_insight_pages.py")
FIXTURE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "_preview", "_sandbox-v4.9.1"))
RECENT = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d 10:00:00+0800")


# ───────────────────────────── 夹具构造 ─────────────────────────────

def make_chart(name, cd_id, dims=("区域",), measures=("销售额", "销量"),
               ds="ds1", ctype="BASIC_BAR", params=()):
    return {"name": name, "cdId": cd_id, "type": ctype, "dsId": ds,
            "dims": list(dims),
            "measures": [{"name": m, "alias": "", "fdId": ""} for m in measures],
            "filters": [], "filterDetails": [],
            "dynamicParams": [{"dpId": p, "name": p} for p in params]}


def make_selector(name, cd_id, field="区域", in_bar=True, linked=3, stype="DS_ELEMENTS"):
    return {"name": name, "cdId": cd_id, "type": "SELECTOR", "dsId": "",
            "dims": [], "measures": [],
            "filters": [field] if field else [],
            "filterDetails": [{"field": field, "selectorType": stype}] if field else [],
            "dynamicParams": [], "inFilterBar": in_bar, "linkedCardCount": linked,
            "defaultValueType": "FIXED_VALUE", "multiSelect": True, "selectorType": stype}


def make_time_selector(name="日期", cd_id="time1", in_bar=True, linked=10, stype="CALENDAR"):
    return make_selector(name, cd_id, field="", in_bar=in_bar, linked=linked, stype=stype)


def make_page(pg_id, cards, mtime=RECENT):
    return {"pgId": pg_id, "mtime": mtime, "dsIds": [], "dsUsage": {}, "cards": cards}


def simple_page(name="主看板", pg="pg1", card_count=6, ds="ds1",
                dims=("区域",), extra_cards=(), extra_selectors=(), with_time=True):
    cards = [make_chart(f"指标{i}", f"c{i}", dims=(dims[i % len(dims)],), ds=ds)
             for i in range(card_count)]
    cards += [make_selector("区域", "s-region", dims[0])]
    if with_time:
        cards += [make_time_selector()]
    cards += list(extra_cards) + list(extra_selectors)
    return make_page(pg, cards)


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_json(self, rel_path, doc):
        path = os.path.join(self.tmp, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def run_audit(self, *args):
        proc = subprocess.run([sys.executable, SCRIPT, self.tmp] + list(args),
                              capture_output=True, text=True)
        audit_path = os.path.join(self.tmp, "insight-audit.json")
        audit = None
        if os.path.exists(audit_path):
            with open(audit_path, encoding="utf-8") as f:
                audit = json.load(f)
        return proc, audit

    def run_ok(self, *args):
        proc, audit = self.run_audit(*args)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIsNotNone(audit)
        return audit

    @staticmethod
    def findings(audit, rule=None, level=None, scope=None):
        out = []
        for f in audit["findings"]:
            if rule and f["rule"] != rule:
                continue
            if level and f["level"] != level:
                continue
            if scope and not f["scope"].startswith(scope):
                continue
            out.append(f)
        return out

    @staticmethod
    def page(audit, name):
        for page in audit["pages"]:
            if page["name"] == name:
                return page
        raise AssertionError(f"页面 {name} 不在体检结果里: {[p['name'] for p in audit['pages']]}")


# ───────────────────────────── 1. 输入哨兵 ─────────────────────────────

class TestInputGuard(AuditCase):
    def test_missing_cards_raw_exits_2(self):
        proc, audit = self.run_audit()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("parse_page.py", proc.stderr)
        self.assertIsNone(audit)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "insight-audit.json")))

    def test_invalid_cards_raw_exits_2(self):
        with open(os.path.join(self.tmp, "cards-raw.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        proc, audit = self.run_audit()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cards-raw.json", proc.stderr)
        self.assertIsNone(audit)

    def test_cards_raw_wrong_shape_exits_2(self):
        self.write_json("cards-raw.json", [{"pgId": "pg1"}])
        proc, audit = self.run_audit()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("结构不符", proc.stderr)
        self.assertIsNone(audit)

    def test_corrupted_optional_inputs_degrade_without_crash(self):
        self.write_json("cards-raw.json", {"降级页": simple_page("降级页", pg="pg1")})
        for rel in ("page-check.json", "formulas.json",
                    "card-data/_sample_index.json"):
            path = os.path.join(self.tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("[broken")
        audit = self.run_ok()
        self.assertEqual(audit["meta"]["inputs"],
                         {"pageCheck": False, "formulas": False, "samples": False})
        skipped = " ".join(audit["meta"]["skippedRules"])
        self.assertIn("损坏", skipped)
        r06 = self.findings(audit, rule="R-06", level="P2")
        self.assertTrue(any("未实测" in f["evidence"] for f in r06))


# ───────────────────────────── 2. R-01 页数预算 ─────────────────────────────

class TestPageBudget(AuditCase):
    def test_eleven_pages_trigger_r01_blocker(self):
        doc = {f"看板{i:02d}": simple_page(f"看板{i:02d}", pg=f"pg{i}", card_count=6)
               for i in range(11)}
        self.write_json("cards-raw.json", doc)
        audit = self.run_ok()
        self.assertEqual(audit["meta"]["pageCount"], 11)
        self.assertEqual(audit["meta"]["maxPages"], 10)
        r01 = self.findings(audit, rule="R-01")
        self.assertEqual(len(r01), 1)
        self.assertEqual(r01[0]["level"], "blocker")
        self.assertIn("11", r01[0]["evidence"])
        self.assertEqual(audit["portfolio"]["overall"], 49)
        self.assertEqual(audit["portfolio"]["grade"], "不建议直接配置")

    def test_custom_max_pages_lowers_budget(self):
        doc = {f"看板{i}": simple_page(f"看板{i}", pg=f"pg{i}", card_count=6)
               for i in range(2)}
        self.write_json("cards-raw.json", doc)
        proc = subprocess.run([sys.executable, SCRIPT, self.tmp, "--max-pages", "1"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        with open(os.path.join(self.tmp, "insight-audit.json"), encoding="utf-8") as f:
            audit = json.load(f)
        self.assertEqual(audit["meta"]["maxPages"], 1)
        self.assertEqual(audit["meta"]["officialMaxPages"], 10)
        self.assertEqual(len(self.findings(audit, rule="R-01")), 1)
        self.assertLessEqual(audit["portfolio"]["overall"], 49)
        self.assertIn("官方上限", proc.stdout)


# ───────────────────────────── 3-5. R-02 联动筛选器 ─────────────────────────────

class TestLinkageSelector(AuditCase):
    def test_no_linkage_selector_blocks(self):
        cards = [make_chart("销售额", "c1"),
                 make_selector("区域", "s1", in_bar=True, linked=0),
                 make_time_selector(linked=0)]
        self.write_json("cards-raw.json", {"无联动页": make_page("pg1", cards)})
        audit = self.run_ok()
        r02 = self.findings(audit, rule="R-02")
        self.assertEqual(len(r02), 1)
        self.assertEqual(r02[0]["level"], "blocker")
        self.assertIn("linkedCardCount", r02[0]["evidence"])
        self.assertEqual(self.page(audit, "无联动页")["verdict"], "blocker")
        self.assertLessEqual(audit["portfolio"]["overall"], 64)
        self.assertEqual(audit["portfolio"]["grade"], "需改造")

    def test_r02_caps_high_scoring_page_at_64(self):
        # 结构分很高（层级/明细齐全、无口径问题），但无联动筛选器 → 总分仍封顶 64
        dims = ("区域", "省份", "城市", "门店编码", "商品名称", "渠道")
        cards = [make_chart(f"指标{i}", f"c{i}", dims=(dims[i % len(dims)],))
                 for i in range(8)]
        cards += [make_selector("区域", "s1", linked=0),
                  make_selector("商品名称", "s2", field="商品名称", linked=0),
                  make_time_selector(linked=0)]
        self.write_json("cards-raw.json", {"高分无联动页": make_page("pg1", cards)})
        audit = self.run_ok()
        page = self.page(audit, "高分无联动页")
        self.assertGreaterEqual(page["rawTotal"], 65)
        self.assertEqual(page["total"], 64)
        self.assertEqual(audit["portfolio"]["overall"], 64)
        self.assertEqual(audit["portfolio"]["grade"], "需改造")

    def test_filter_bar_linkage_does_not_trigger_r02(self):
        cards = [make_chart("销售额", "c1"),
                 make_selector("区域", "s1", in_bar=True, linked=7),
                 make_time_selector(linked=10)]
        self.write_json("cards-raw.json", {"合规页": make_page("pg1", cards)})
        audit = self.run_ok()
        self.assertEqual(self.findings(audit, rule="R-02"), [])
        self.assertNotEqual(self.page(audit, "合规页")["verdict"], "blocker")
        self.assertEqual(self.page(audit, "合规页")["facts"]["linkageSelectors"], 2)

    def test_hidden_linkage_only_warns(self):
        # linkedCardCount>0 但不在筛选栏：只告警（P2），不算通过、不阻断
        cards = [make_chart("销售额", "c1"),
                 make_selector("区域", "s1", in_bar=False, linked=5),
                 make_time_selector(in_bar=True, linked=0)]
        self.write_json("cards-raw.json", {"隐藏筛选页": make_page("pg1", cards)})
        audit = self.run_ok()
        r02 = self.findings(audit, rule="R-02")
        self.assertEqual(len(r02), 1)
        self.assertEqual(r02[0]["level"], "P2")
        self.assertIn("inFilterBar=false", r02[0]["evidence"])
        page = self.page(audit, "隐藏筛选页")
        self.assertEqual(page["verdict"], "warn")
        self.assertEqual(page["facts"]["linkageSelectors"], 0)
        self.assertLess(page["scores"]["linkage"], 25)
        self.assertEqual([f for f in r02 if f["level"] == "blocker"], [])


# ───────────────────────────── 6. R-09 时间筛选 ─────────────────────────────

class TestTimeFilter(AuditCase):
    def test_missing_time_filter_is_p0(self):
        cards = [make_chart("销售额", "c1"), make_selector("区域", "s1", linked=5)]
        self.write_json("cards-raw.json", {"无时间页": make_page("pg1", cards)})
        audit = self.run_ok()
        r09 = self.findings(audit, rule="R-09")
        self.assertEqual(len(r09), 1)
        self.assertEqual(r09[0]["level"], "P0")
        self.assertIn("时间", r09[0]["evidence"])

    def test_time_parameter_on_card_counts(self):
        cards = [make_chart("销售额", "c1", params=("开始时间", "结束时间")),
                 make_selector("区域", "s1", linked=5)]
        self.write_json("cards-raw.json", {"参数时间页": make_page("pg1", cards)})
        audit = self.run_ok()
        self.assertEqual(self.findings(audit, rule="R-09"), [])


# ───────────────────────────── 7-8. R-06 上下文可控 ─────────────────────────────

class TestContextLimits(AuditCase):
    def test_twenty_one_cards_is_p0(self):
        self.write_json("cards-raw.json", {"大页": simple_page(card_count=21)})
        audit = self.run_ok()
        hits = [f for f in self.findings(audit, rule="R-06", level="P0")
                if "21" in f["evidence"] and "数据卡" in f["evidence"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("超过 20", hits[0]["evidence"])

    def test_thirteen_cards_is_p1(self):
        self.write_json("cards-raw.json", {"临界页": simple_page(card_count=13)})
        audit = self.run_ok()
        hits = [f for f in self.findings(audit, rule="R-06", level="P1")
                if "13" in f["evidence"] and "数据卡" in f["evidence"]]
        self.assertEqual(len(hits), 1)
        self.assertEqual(self.findings(audit, rule="R-06", level="P0"), [])

    def test_detail_table_12000_rows_is_p0(self):
        table = make_chart("订单明细", "t1", dims=("订单号", "商品名称"),
                           ctype="TABLE", measures=("销售额", "销量"))
        page = make_page("明细页", [table,
                                  make_selector("商品名称", "s1", field="商品名称", linked=4),
                                  make_time_selector()])
        self.write_json("cards-raw.json", {"明细页": page})
        self.write_json("card-data/_sample_index.json", {
            "明细页__订单明细__t1.json": {"cdId": "t1", "type": "TABLE", "rows": 12000,
                                       "sampledRows": 200, "truncated": True,
                                       "cols": 2, "columns": ["订单号", "商品名称"],
                                       "profile": {}}})
        audit = self.run_ok()
        hits = [f for f in self.findings(audit, rule="R-06", level="P0")
                if "12000" in f["evidence"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("订单明细", hits[0]["evidence"])
        self.assertEqual(self.page(audit, "明细页")["facts"]["maxRawRows"], 12000)

    def test_detail_table_without_samples_is_p2_unmeasured(self):
        table = make_chart("订单明细", "t1", dims=("订单号", "商品名称"),
                           ctype="TABLE", measures=("销售额", "销量"))
        page = make_page("明细页", [table,
                                  make_selector("商品名称", "s1", field="商品名称", linked=4),
                                  make_time_selector()])
        self.write_json("cards-raw.json", {"明细页": page})
        audit = self.run_ok()
        self.assertFalse(audit["meta"]["inputs"]["samples"])
        unmeasured = [f for f in self.findings(audit, rule="R-06", level="P2")
                      if "未实测" in f["evidence"]]
        self.assertEqual(len(unmeasured), 1)
        self.assertIn("sample_index.json", unmeasured[0]["evidence"])


# ───────────────────────────── 9-10. R-05 / R-08 指标可直读 ─────────────────────────────

class TestMetricReadiness(AuditCase):
    def test_cross_page_formula_conflict_is_p0(self):
        pages = {}
        for name, pg in (("看板A", "pg-a"), ("看板B", "pg-b")):
            cards = [make_chart("退款率卡", f"{pg}-c1", dims=("区域",),
                                measures=("退款率", "销售额")),
                     make_selector("区域", f"{pg}-s1", linked=3),
                     make_time_selector(f"日期-{pg}", f"{pg}-t1")]
            pages[name] = make_page(pg, cards)
        self.write_json("cards-raw.json", pages)
        self.write_json("formulas.json", {"conflicts": [{
            "name": "退款率",
            "variants": [
                {"formula": "sum([退款])/sum([销售])", "sources": ["《看板A》退款率卡"]},
                {"formula": "sum([退款])/count(distinct [订单])", "sources": ["《看板B》退款率卡"]},
            ]}]})
        audit = self.run_ok()
        self.assertTrue(audit["meta"]["inputs"]["formulas"])
        r05 = self.findings(audit, rule="R-05", level="P0")
        self.assertEqual(len(r05), 1)
        self.assertIn("退款率", r05[0]["evidence"])
        self.assertIn("sum([退款])", r05[0]["evidence"])
        self.assertEqual(audit["cross"]["conflicts"][0]["metric"], "退款率")
        self.assertEqual(set(audit["cross"]["conflicts"][0]["pages"]), {"看板A", "看板B"})

    def test_param_dependent_without_parameter_selector_is_p0(self):
        cards = [make_chart("趋势图", "c1", dims=("区域",), measures=("指标",)),
                 make_selector("区域", "s1", linked=3),
                 make_time_selector()]
        self.write_json("cards-raw.json", {"参数页": make_page("pg1", cards)})
        self.write_json("formulas.json", {"metrics": [{
            "name": "指标", "classification": "PARAM_DEPENDENT", "consensus": True,
            "occurrences": 1,
            "formula": "case when [DYNAMIC_PARAMS.趋势指标]='销量' then sum([销量]) end",
            "sources": [{"page": "参数页", "card": "趋势图", "dims": ["区域"], "scope": []}],
        }]})
        audit = self.run_ok()
        hits = self.findings(audit, rule="R-08", level="P0")
        self.assertEqual(len(hits), 1)
        self.assertIn("趋势指标", hits[0]["evidence"])
        self.assertIn("趋势图", hits[0]["evidence"])

    def test_param_dependent_with_parameter_selector_passes(self):
        param_sel = make_selector("可选指标", "p1", field="", in_bar=True,
                                  linked=3, stype="PARAMETER")
        cards = [make_chart("趋势图", "c1", dims=("区域",), measures=("指标",)),
                 make_selector("区域", "s1", linked=3),
                 make_time_selector(), param_sel]
        self.write_json("cards-raw.json", {"参数页": make_page("pg1", cards)})
        self.write_json("formulas.json", {"metrics": [{
            "name": "指标", "classification": "PARAM_DEPENDENT", "consensus": True,
            "occurrences": 1,
            "formula": "case when [DYNAMIC_PARAMS.趋势指标]='销量' then sum([销量]) end",
            "sources": [{"page": "参数页", "card": "趋势图", "dims": ["区域"], "scope": []}],
        }]})
        audit = self.run_ok()
        self.assertEqual(self.findings(audit, rule="R-08", level="P0"), [])


# ───────────────────────────── 11-12. 跨页冗余与共享维度 ─────────────────────────────

class TestCrossPage(AuditCase):
    def test_duplicate_cards_across_pages_merge_suggestion(self):
        pages = {}
        for name, pg in (("重复A", "pg-a"), ("重复B", "pg-b")):
            cards = [make_chart("区域销售一", f"{pg}-c1", dims=("区域",), ds="ds-shared"),
                     make_chart("区域销售二", f"{pg}-c2", dims=("区域",), ds="ds-shared"),
                     make_selector("区域", f"{pg}-s1", linked=2),
                     make_time_selector(f"日期-{pg}", f"{pg}-t1")]
            pages[name] = make_page(pg, cards)
        self.write_json("cards-raw.json", pages)
        audit = self.run_ok(*["--seed-advice"])
        self.assertTrue(audit["cross"]["overlaps"], audit["cross"])
        first = audit["cross"]["overlaps"][0]
        self.assertEqual(first["pages"], ["重复A", "重复B"])
        self.assertTrue(any("区域销售一" in card for card in first["cards"]))
        r07 = [f for f in self.findings(audit, rule="R-07") if "重复" in f["evidence"]]
        self.assertEqual(len(r07), 1)
        self.assertEqual(r07[0]["level"], "P0")  # 4/4 张卡重复，占比 100%
        with open(os.path.join(self.tmp, "insight-advice.seed.json"), encoding="utf-8") as f:
            seed = json.load(f)
        self.assertTrue(any(a["type"] == "合并" for a in seed["crossPageActions"]))

    def test_no_shared_linkage_dims_is_p0(self):
        pages = {
            "无共享A": make_page("pg-a", [
                make_chart("区域销售", "a-c1", dims=("区域",)),
                make_selector("区域", "a-s1", field="区域", linked=2),
                make_time_selector("日期-A", "a-t1")]),
            "无共享B": make_page("pg-b", [
                make_chart("品类销售", "b-c1", dims=("商品品类",)),
                make_selector("商品品类", "b-s1", field="商品品类", linked=2),
                make_time_selector("日期-B", "b-t1")]),
        }
        self.write_json("cards-raw.json", pages)
        audit = self.run_ok()
        self.assertEqual(audit["cross"]["sharedLinkageDims"], [])
        r13 = self.findings(audit, rule="R-13")
        self.assertEqual(len(r13), 1)
        self.assertEqual(r13[0]["level"], "P0")
        self.assertIn("无交集", r13[0]["evidence"])

    def test_shared_business_dim_recorded(self):
        pages = {}
        for name, pg in (("共享A", "pg-a"), ("共享B", "pg-b")):
            pages[name] = make_page(pg, [
                make_chart("区域销售", f"{pg}-c1", dims=("区域",)),
                make_selector("区域", f"{pg}-s1", field="区域", linked=2),
                make_time_selector(f"日期-{pg}", f"{pg}-t1")])
        self.write_json("cards-raw.json", pages)
        audit = self.run_ok()
        fields = [s["field"] for s in audit["cross"]["sharedLinkageDims"]]
        self.assertIn("区域", fields)
        self.assertEqual(self.findings(audit, rule="R-13"), [])


# ───────────────────────────── 13. R-10 卡名 ─────────────────────────────

class TestCardNames(AuditCase):
    def test_duplicate_risky_and_locked_names(self):
        cards = [
            make_chart("销售额", "c1"), make_chart("销售额", "c2"),
            make_chart("副本-销售额", "c3"),
            make_chart("8月销售", "c4"),
            make_chart("图1", "c5"),
            make_chart("", "c6"),
            make_selector("区域", "s1", linked=3),
            make_time_selector(),
        ]
        self.write_json("cards-raw.json", {"命名页": make_page("pg1", cards)})
        audit = self.run_ok()
        r10 = self.findings(audit, rule="R-10")
        p1 = [f for f in r10 if f["level"] == "P1"]
        p2 = [f for f in r10 if f["level"] == "P2"]
        self.assertTrue(any("重名" in f["evidence"] for f in p1), [f["evidence"] for f in r10])
        self.assertTrue(any("副本" in f["evidence"] for f in p1), [f["evidence"] for f in r10])
        self.assertTrue(any("空/纯编号" in f["evidence"] for f in p1), [f["evidence"] for f in r10])
        self.assertTrue(any("图1" in f["evidence"] for f in p1), [f["evidence"] for f in r10])
        self.assertEqual(len(p2), 1)
        self.assertIn("8月销售", p2[0]["evidence"])


# ───────────────────────────── 14. 评分确定性 / 等级边界 ─────────────────────────────

class TestScoring(AuditCase):
    def test_grade_boundaries(self):
        self.assertEqual(audit_mod.grade_for(100), "可直接配置")
        self.assertEqual(audit_mod.grade_for(80), "可直接配置")
        self.assertEqual(audit_mod.grade_for(79), "小改后配置")
        self.assertEqual(audit_mod.grade_for(65), "小改后配置")
        self.assertEqual(audit_mod.grade_for(64), "需改造")
        self.assertEqual(audit_mod.grade_for(50), "需改造")
        self.assertEqual(audit_mod.grade_for(49), "不建议直接配置")

    def test_repeat_runs_are_deterministic(self):
        pages = {}
        for name, pg in (("稳定A", "pg-a"), ("稳定B", "pg-b")):
            pages[name] = make_page(pg, [
                make_chart("区域销售", f"{pg}-c1", dims=("区域", "省份")),
                make_chart("品类销售", f"{pg}-c2", dims=("商品品类",)),
                make_selector("区域", f"{pg}-s1", field="区域", linked=2),
                make_selector("商品品类", f"{pg}-s2", field="商品品类", linked=2),
                make_time_selector(f"日期-{pg}", f"{pg}-t1")])
        self.write_json("cards-raw.json", pages)
        first = self.run_ok()
        first["meta"].pop("builtAt")
        second = self.run_ok()
        second["meta"].pop("builtAt")
        self.assertEqual(json.dumps(first, ensure_ascii=False, sort_keys=True),
                         json.dumps(second, ensure_ascii=False, sort_keys=True))


# ───────────────────────────── 15. 建议底稿 ─────────────────────────────

class TestSeedAdvice(AuditCase):
    def test_seed_advice_structure(self):
        pages = {
            "种子A": make_page("pg-a", [
                make_chart("区域销售", "a-c1", dims=("区域",), ds="ds1"),
                make_selector("区域", "a-s1", field="区域", linked=2),
                make_time_selector("日期-A", "a-t1")]),
            "种子B": make_page("pg-b", [
                make_chart("区域销售", "b-c1", dims=("区域",), ds="ds1"),
                make_selector("区域", "b-s1", field="区域", linked=2),
                make_time_selector("日期-B", "b-t1")]),
        }
        self.write_json("cards-raw.json", pages)
        audit = self.run_ok("--scenario", "门店经营异常定位", "--seed-advice")
        with open(os.path.join(self.tmp, "insight-advice.seed.json"), encoding="utf-8") as f:
            seed = json.load(f)
        for key in ("auditBuiltAt", "scenario", "businessScope", "mode", "targetArchitecture",
                    "pageActions", "crossPageActions", "configHandoff", "roadmap",
                    "openQuestions"):
            self.assertIn(key, seed)
        self.assertEqual(seed["auditBuiltAt"], audit["meta"]["builtAt"])
        self.assertEqual(seed["scenario"], "门店经营异常定位")
        self.assertEqual(seed["roadmap"], [])
        self.assertEqual(seed["openQuestions"], [])
        self.assertIn(seed["mode"]["primary"],
                      {"一张宽表", "多层下钻", "主从Agent", "批量分治", "链路复盘"})
        self.assertEqual(len(seed["pageActions"]), 2)
        for action in seed["pageActions"]:
            for key in ("pgId", "name", "verdict", "priority", "actions", "evidence",
                        "expectedEffect"):
                self.assertIn(key, action)
            self.assertIn(action["verdict"], {"保留", "改造", "拆分", "合并", "新建", "移出"})
            for fid in action["evidence"]:
                self.assertIn(fid, {f["id"] for f in audit["findings"]})
        for key in ("agentType", "defaultThinking", "stepPlan", "exploratoryRules",
                    "reportFramework", "questionExamples", "outputRequirements"):
            self.assertIn(key, seed["configHandoff"])
        self.assertEqual(seed["configHandoff"]["agentType"], "")
        self.assertEqual(seed["configHandoff"]["stepPlan"], [])
        links = seed["configHandoff"]["linkageFilters"]
        self.assertTrue(links)
        # 每条联动筛选器必须真实存在且 linkedCardCount>0
        for item in links:
            for key in ("pgId", "name", "field", "cdId"):
                self.assertIn(key, item)
            page = next(p for p in pages.values() if p["pgId"] == item["pgId"])
            sel = next((c for c in page["cards"] if c["cdId"] == item["cdId"]), None)
            self.assertIsNotNone(sel, item)
            self.assertTrue(sel["inFilterBar"])
            self.assertGreater(sel["linkedCardCount"], 0)

    def test_custom_out_path(self):
        self.write_json("cards-raw.json", {"输出页": simple_page("输出页", pg="pg1")})
        out_path = os.path.join(self.tmp, "sub", "custom-audit.json")
        proc, default_audit = self.run_audit("--out", out_path)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIsNone(default_audit)
        self.assertTrue(os.path.exists(out_path))
        with open(out_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["meta"]["pageCount"], 1)

    def test_seed_advice_not_written_without_flag(self):
        self.write_json("cards-raw.json", {"无种子页": simple_page("无种子页", pg="pg1")})
        self.run_ok()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "insight-advice.seed.json")))


# ───────────────────────────── 附：不可用页不进入页级均分 ─────────────────────────────

class TestUnavailablePage(AuditCase):
    def test_zero_data_card_page_excluded_from_page_mean(self):
        empty_text = {"name": "说明", "cdId": "t1", "type": "TEXT", "dsId": "",
                      "dims": [], "measures": [], "filters": [], "filterDetails": [],
                      "dynamicParams": []}
        pages = {
            "正常页": simple_page("正常页", pg="pg-good", card_count=6),
            "空页": make_page("pg-empty", [empty_text]),
        }
        self.write_json("cards-raw.json", pages)
        audit = self.run_ok()
        empty = self.page(audit, "空页")
        good = self.page(audit, "正常页")
        self.assertTrue(empty.get("unavailable"))
        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["verdict"], "blocker")
        self.assertTrue(any(f["rule"] == "R-06" and f["level"] == "blocker"
                            for f in audit["findings"]))
        # 总分只由可用页均分计算（不可用页不拉低/抬高）
        expected = round(good["total"] * 0.6 + audit["portfolio"]["score"] * 0.4)
        self.assertEqual(audit["portfolio"]["overall"], expected)

    def test_page_check_unreachable_page_marked_unavailable(self):
        self.write_json("cards-raw.json", {"取不到页": simple_page("取不到页", pg="pg1")})
        self.write_json("page-check.json", {"pages": [{
            "pgId": "pg1", "verdict": "⛔", "name": "取不到页",
            "reasons": ["看板内容取不到（timeout）——无法学习"], "signals": {}}]})
        audit = self.run_ok()
        page = self.page(audit, "取不到页")
        self.assertTrue(page.get("unavailable"))
        self.assertEqual(page["total"], 0)
        self.assertLessEqual(audit["portfolio"]["overall"], 49)
        self.assertEqual(audit["portfolio"]["grade"], "不建议直接配置")


# ───────────────────────────── 16. 附：停更与下钻承接 ─────────────────────────────

class TestStalenessAndDrill(AuditCase):
    def test_page_check_data_utime_preferred_for_stale_signal(self):
        old = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
        self.write_json("cards-raw.json", {"停更页": simple_page("停更页", pg="pg1")})
        self.write_json("page-check.json", {"pages": [{
            "pgId": "pg1", "verdict": "⚠️", "name": "停更页", "reasons": [],
            "signals": {"dataUtime": old}}]})
        audit = self.run_ok()
        r16 = self.findings(audit, rule="R-16")
        self.assertEqual(len(r16), 1)
        self.assertEqual(r16[0]["level"], "P1")
        self.assertIn(old, r16[0]["evidence"])
        self.assertLess(self.page(audit, "停更页")["scores"]["ops"], 10)

    def test_stale_page_mtime_without_page_check(self):
        old_mtime = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d 09:00:00+0800")
        page = simple_page("仅mtime页", pg="pg1")
        page["mtime"] = old_mtime
        self.write_json("cards-raw.json", {"仅mtime页": page})
        audit = self.run_ok()
        r16 = self.findings(audit, rule="R-16")
        self.assertEqual(len(r16), 1)
        self.assertIn(old_mtime[:10], r16[0]["evidence"])

    def test_drill_card_without_hierarchy_selector_is_p1(self):
        drill = make_chart("门店下钻", "d1", dims=("门店编码",), ctype="DRILL")
        page = make_page("下钻页", [drill,
                                  make_selector("区域", "s1", field="区域", linked=2),
                                  make_time_selector()])
        self.write_json("cards-raw.json", {"下钻页": page})
        audit = self.run_ok()
        r12 = [f for f in self.findings(audit, rule="R-12") if f["scope"] == "page:下钻页"]
        self.assertEqual(len(r12), 1)
        self.assertEqual(r12[0]["level"], "P1")
        self.assertIn("门店下钻", r12[0]["evidence"])


# ───────────────────────────── 17. 真实夹具 ─────────────────────────────

class TestRealFixture(AuditCase):
    def test_sandbox_v491_fixture_runs_without_false_r02(self):
        for name in ("cards-raw.json", "formulas.json"):
            shutil.copy(os.path.join(FIXTURE_DIR, name), os.path.join(self.tmp, name))
        os.makedirs(os.path.join(self.tmp, "card-data"), exist_ok=True)
        shutil.copy(os.path.join(FIXTURE_DIR, "card-data", "_sample_index.json"),
                    os.path.join(self.tmp, "card-data", "_sample_index.json"))
        audit = self.run_ok("--scenario", "月度经营分析")
        self.assertEqual(audit["meta"]["pageCount"], 2)
        self.assertEqual(audit["meta"]["builderVersion"], "4.11.0")
        self.assertEqual(audit["meta"]["inputs"],
                         {"pageCheck": False, "formulas": True, "samples": True})
        cards = {p["name"]: p["facts"]["dataCards"] for p in audit["pages"]}
        self.assertEqual(cards, {"【月报】饮品分析": 40, "【月报】周边分析": 22})
        # 两页都有筛选栏内联动筛选器：R-02 不误报
        self.assertEqual(self.findings(audit, rule="R-02"), [])
        # 62/34 卡的大页应触发上下文拆分（P0）
        split = [f for f in self.findings(audit, rule="R-06", level="P0")
                 if "数据卡" in f["evidence"]]
        self.assertEqual(len(split), 2)
        self.assertTrue(audit["cross"]["sharedLinkageDims"])
        self.assertIn("城市", [s["field"] for s in audit["cross"]["sharedLinkageDims"]])
        for finding in audit["findings"]:
            self.assertTrue(finding["evidence"])
            self.assertIn(finding["level"], {"blocker", "P0", "P1", "P2"})


if __name__ == "__main__":
    unittest.main()
