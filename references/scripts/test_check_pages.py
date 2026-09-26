#!/usr/bin/env python3
"""check_pages.py 的单测：评分四维度纯函数、权重重分摊、冲突降档、红线/边界分级、硬门槛不评分"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_pages as cp


def mk_chart(name, ds="ds1", rows=(), metrics=(), filters=()):
    return {"cdId": f"cd-{name}", "cdType": "CHART", "name": name,
            "content": {"dsId": ds, "meta": {"chartMain": {"zoneData": {
                "row": [{"name": r} for r in rows],
                "metric": [dict(m) for m in metrics],
                "filters": [{"fdId": f} for f in filters]}}}}}


def mk_selector(name, field=""):
    return {"cdId": f"cd-{name}", "cdType": "SELECTOR", "name": name,
            "content": {"source": {"field": {"name": field}}}}


def mk_dsinfo(ds_id, dims=(), metrics_cols=(), utime=""):
    cols = [{"fdId": f"fd-{n}", "name": n, "metaType": "DIM"} for n in dims]
    cols += [{"fdId": f"fd-{n}", "name": n, "metaType": "METRIC"} for n in metrics_cols]
    return {"dsId": ds_id, "name": ds_id, "columns": cols, "utime": utime}


def mk_data(cards, ds_infos=(), pg_type="PAGE", name="测试看板"):
    return {"name": name, "pgType": pg_type, "cards": cards,
            "dsInfos": list(ds_infos), "meta": {}}


class TestNormalize(unittest.TestCase):
    def test_case_and_space_insensitive(self):
        self.assertEqual(cp.normalize_formula("SUM([金额]) / sum( [数量] )"),
                         cp.normalize_formula("sum([金额])/sum([数量])"))

    def test_bracket_content_preserved(self):
        self.assertIn("[金额]", cp.normalize_formula("SUM([金额])"))


class TestFindConflicts(unittest.TestCase):
    def test_same_name_two_formulas_is_conflict(self):
        ms = [{"display": "退款率", "name": "退款额", "alias": "退款率",
               "formula": "sum([退款])/sum([销售])", "aggrType": "", "advType": ""},
              {"display": "退款率", "name": "退款率", "alias": "",
               "formula": "sum([退款])/count(distinct [订单])", "aggrType": "", "advType": ""}]
        # 第一条别名==展示名但 alias != name……不应被排除的情形由下一个用例覆盖；此处两条都参与
        ms[0]["alias"] = ""
        ms[0]["display"] = "退款率"
        conflicts = cp.find_conflicts(ms)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["name"], "退款率")
        self.assertEqual(len(conflicts[0]["variants"]), 2)

    def test_same_formula_normalized_no_conflict(self):
        base = {"display": "销售额", "name": "销售额", "alias": "", "aggrType": "", "advType": ""}
        ms = [dict(base, formula="SUM([金额])"), dict(base, formula="sum( [金额] )")]
        self.assertEqual(cp.find_conflicts(ms), [])

    def test_presentation_derived_excluded(self):
        # 别名≠本名（如"年同比"基于"销售额"）是展示层派生，不参与冲突判定
        ms = [{"display": "年同比", "name": "销售额", "alias": "年同比",
               "formula": "sum([金额])", "aggrType": "", "advType": "COMPARATIVE"},
              {"display": "年同比", "name": "销售额", "alias": "年同比",
               "formula": "sum([成本])", "aggrType": "", "advType": "COMPARATIVE"}]
        self.assertEqual(cp.find_conflicts(ms), [])

    def test_physical_aggr_diff_not_conflict(self):
        # 纯物理字段不同聚合方式（MIN/MAX 分作起止）属正常使用差异
        ms = [{"display": "日期", "name": "日期", "alias": "", "formula": "", "aggrType": "MIN", "advType": ""},
              {"display": "日期", "name": "日期", "alias": "", "formula": "", "aggrType": "MAX", "advType": ""}]
        self.assertEqual(cp.find_conflicts(ms), [])


class TestReuseRate(unittest.TestCase):
    def test_shared_dataset(self):
        data = mk_data([mk_chart("a", ds="ds1"), mk_chart("b", ds="ds1"), mk_chart("c", ds="ds2")])
        self.assertAlmostEqual(cp.reuse_rate(data), 2 / 3)

    def test_all_dedicated(self):
        data = mk_data([mk_chart("a", ds="ds1"), mk_chart("b", ds="ds2")])
        self.assertAlmostEqual(cp.reuse_rate(data), 0.0)

    def test_no_ds_info_returns_none(self):
        data = mk_data([{"cdId": "x", "cdType": "CHART", "name": "x", "content": {}}])
        self.assertIsNone(cp.reuse_rate(data))


class TestGrainCoverage(unittest.TestCase):
    def test_rows_filters_selectors_counted(self):
        data = mk_data(
            [mk_chart("a", rows=("区域",), filters=("fd-渠道",)),
             mk_selector("s1", field="月份")],
            [mk_dsinfo("ds1", dims=("区域", "渠道", "月份", "客户"))])
        self.assertAlmostEqual(cp.grain_coverage(data), 3 / 4)

    def test_no_dim_columns_returns_none(self):
        data = mk_data([mk_chart("a")], [mk_dsinfo("ds1", dims=(), metrics_cols=("金额",))])
        self.assertIsNone(cp.grain_coverage(data))

    def test_no_dsinfos_full_when_dims_used(self):
        # dsInfos 缺失（文本回退场景）时无法定义全集，返回 None 重分摊
        data = mk_data([mk_chart("a", rows=("区域",))])
        self.assertIsNone(cp.grain_coverage(data))


class TestGovernedRate(unittest.TestCase):
    def test_name_match(self):
        ms = [{"display": "销售额", "name": "销售额", "alias": "", "formula": "", "aggrType": "SUM", "advType": ""},
              {"display": "退款率", "name": "退款率", "alias": "", "formula": "", "aggrType": "", "advType": ""}]
        rate, hit = cp.governed_rate(ms, {"销售额"})
        self.assertAlmostEqual(rate, 0.5)
        self.assertEqual(hit, ["销售额"])

    def test_no_measures_returns_none(self):
        rate, hit = cp.governed_rate([], {"销售额"})
        self.assertIsNone(rate)
        self.assertEqual(hit, [])


class TestAgentReady(unittest.TestCase):
    def good_page(self):
        return mk_data(
            [mk_chart("a", ds="ds1", rows=("区域",),
                      metrics=[{"name": "销售额", "alias": "销售额", "aggrType": "SUM"}]),
             mk_chart("b", ds="ds1", rows=("区域",),
                      metrics=[{"name": "销售额", "alias": "销售额", "aggrType": "SUM"}])],
            [mk_dsinfo("ds1", dims=("区域",))])

    def test_perfect_page_scores_high(self):
        ar = cp.agent_ready(self.good_page(), {"销售额"})
        self.assertEqual(ar["score"], 100)
        self.assertEqual(ar["grade"], "高")
        self.assertEqual(ar["redLines"], [])

    def test_conflict_caps_grade_and_red_line(self):
        data = mk_data(
            [mk_chart("a", ds="ds1", rows=("区域",),
                      metrics=[{"name": "退款率", "alias": "", "formula": "sum([a])/sum([b])", "aggrType": ""}]),
             mk_chart("b", ds="ds1", rows=("区域",),
                      metrics=[{"name": "退款率", "alias": "", "formula": "sum([a])/count([c])", "aggrType": ""}])],
            [mk_dsinfo("ds1", dims=("区域",))])
        ar = cp.agent_ready(data, {"退款率"})
        self.assertEqual(ar["dims"]["conflicts"], 1)
        self.assertEqual(ar["grade"], "中")  # 其他维度满分也被压到「中」
        self.assertEqual(len(ar["redLines"]), 1)
        self.assertIn("退款率", ar["redLines"][0])

    def test_governed_unavailable_weight_redistributed(self):
        # 不查指标中心：25 分权重按比例摊给其余维度，满分页面仍是 100
        ar = cp.agent_ready(self.good_page(), None)
        self.assertEqual(ar["score"], 100)
        self.assertEqual(ar["dims"]["governed"], "unavailable")

    def test_zero_governed_adds_boundary(self):
        ar = cp.agent_ready(self.good_page(), set())
        self.assertEqual(ar["dims"]["governedRate"], 0.0)
        self.assertTrue(any("指标中心" in b for b in ar["boundaries"]))

    def test_low_grain_adds_boundary(self):
        data = mk_data(
            [mk_chart("a", ds="ds1", rows=("区域",),
                      metrics=[{"name": "销售额", "alias": "销售额", "aggrType": "SUM"}]),
             mk_chart("b", ds="ds1",
                      metrics=[{"name": "销售额", "alias": "销售额", "aggrType": "SUM"}])],
            [mk_dsinfo("ds1", dims=("区域", "渠道", "客户", "月份", "产品"))])
        ar = cp.agent_ready(data, {"销售额"})
        self.assertLess(ar["dims"]["grainCoverage"], 0.3)
        self.assertTrue(any("覆盖不足" in b for b in ar["boundaries"]))


class TestEvaluate(unittest.TestCase):
    def test_hard_gate_pages_not_scored(self):
        r = cp.evaluate("p1", mk_data([], pg_type="LARGE_SCREEN"), None, 90)
        self.assertEqual(r["verdict"], "⛔")
        self.assertNotIn("agentReady", r)
        r2 = cp.evaluate("p2", None, "超时", 90)
        self.assertEqual(r2["verdict"], "⛔")
        self.assertNotIn("agentReady", r2)

    def test_normal_page_scored_with_governed_union(self):
        data = mk_data(
            [mk_chart("a", ds="ds1", rows=("区域",),
                      metrics=[{"name": "销售额", "alias": "销售额", "aggrType": "SUM"}]),
             mk_chart("b", ds="ds1", rows=("区域",),
                      metrics=[{"name": "销售额", "alias": "销售额", "aggrType": "SUM"}])],
            [mk_dsinfo("ds1", dims=("区域",), utime="2026-09-20 10:00:00")])
        r = cp.evaluate("p1", data, None, 90, governed={"ds1": {"销售额"}})
        self.assertIn("agentReady", r)
        self.assertEqual(r["agentReady"]["dims"]["governedRate"], 1.0)

    def test_governed_fetch_failed_falls_back(self):
        data = mk_data(
            [mk_chart("a", ds="ds1", metrics=[{"name": "销售额", "alias": "销售额", "aggrType": "SUM"}])],
            [mk_dsinfo("ds1", dims=("区域",))])
        # governed 字典不含本页任何数据集 = 指标中心查询全部失败 → 权重重分摊
        r = cp.evaluate("p1", data, None, 90, governed={"other-ds": {"销售额"}})
        self.assertEqual(r["agentReady"]["dims"]["governed"], "unavailable")


if __name__ == "__main__":
    unittest.main()
