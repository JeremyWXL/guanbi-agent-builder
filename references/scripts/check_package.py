#!/usr/bin/env python3
"""
交付包体检（交付总闸门）：对组装好的 data agent 交付包做三层校验——
  L1 结构层：文件齐全性（SKILL.md / workbench.html / memory 四文件 / references 内容与脚本）
  L2 内容层：档案 schema 与跨文件一致性（cards.json 富结构、双闸门、examples 验收回填、
             SKILL.md 必需章节、模板占位符残留）
  L3 功能冒烟层：不只看结构，实测"功能还活着"——scope 白名单非空、run_sql --check-scope
             双向断言、make_link --list 找得到筛选器、eval_examples 回归通过、memory status 正常
             （--check-scope 冒烟对不支持该 flag 的旧版 run_sql.py 降级 ⚠️，见下「版本兼容」）
用法:
  python3 check_package.py <交付包路径> [--json]
退出码: 0 通过（可有 ⚠️）/ 1 存在 ❌ / 2 用法或 IO 错误
设计原则: 把"review 一个交付包"变成确定性检查——交付前必跑（build_package.py 内置调用，
  wizard_state confirm --step 8 要求其通过凭证）。模型组装出的包若有结构缺陷或功能瘫痪，
  在此必然报警（fail loud at the gate），不依赖模型自觉。
模式识别: references/cards.json 存在 → 看板模式；references/datasets.json → 数据集直通模式。
版本兼容: 包 _meta.builderVersion 低于特性引入版本时，对应检查降级为 ⚠️（旧档案不硬拦）。
"""
import importlib.util, json, os, re, subprocess, sys

# 与 SKILL.md frontmatter 的 version 保持同步
BUILDER_VERSION = "4.8.1"

# 复制进交付包的脚本清单（(文件名, 看板模式必需, 直通模式必需, 引入版本)）
SCRIPT_LIST = [
    ("attribute.py", True, True, "0"),
    ("make_link.py", True, False, "0"),
    ("memory.py", True, True, "0"),
    ("check_metrics.py", True, True, "0"),
    ("check_dims.py", True, True, "0"),
    ("eval_examples.py", True, True, "0"),
    ("sample_cards.py", True, False, "0"),
    ("run_sql.py", True, True, "0"),
    ("run_metric.py", True, True, "4.8.0"),
    ("workbench.py", True, True, "0"),
    ("scope.py", True, True, "4.5.0"),
    ("scope_audit.py", True, True, "4.5.0"),
    ("feedback.py", True, True, "4.6.0"),
    ("check_package.py", True, True, "4.7.0"),
]
# SKILL.md 必需章节（(章节名, 判定正则, 缺失级别)）——执行流程/维护是交付模板的骨干，缺失即 ❌
SKILL_SECTIONS = [
    ("使用方式", r"^##\s*[^\n]*使用方式", "warn"),
    ("对话体验规范", r"^##\s*[^\n]*对话体验规范", "error"),
    ("记忆系统", r"^##\s*[^\n]*记忆系统", "error"),
    ("前置检查", r"^##\s*[^\n]*前置检查", "warn"),
    ("执行流程", r"^##\s*[^\n]*执行流程", "error"),
    ("数据红线", r"^##\s*[^\n]*数据.*红线", "warn"),
    ("维护", r"^##\s*[^\n]*维护", "error"),
]
PLACEHOLDER_RE = re.compile(r"\{[^{}\n]{1,30}\}")
OUT_OF_SCOPE_PROBE = "zz-out-of-scope-probe"


def ver_tuple(v):
    try:
        return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])
    except ValueError:
        return (0,)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def run_cmd(argv, timeout=120):
    """子进程执行，返回 (returncode, stdout+stderr)。异常视为 -1。"""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def load_module(path, name):
    """按路径动态 import（不污染 sys.path）"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def safe_join(base_dir, rel):
    """fetch.file 目录边界校验（与 eval_examples.py 同一口径）：拒绝绝对路径与
    ../ / 符号链接逃逸，realpath 后必须仍落在 base_dir 内，否则返回 None。"""
    if not rel or os.path.isabs(rel):
        return None
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, rel))
    try:
        if os.path.commonpath([base, target]) != base:
            return None
    except ValueError:
        return None
    return target


class PackageCheck:
    def __init__(self, pkg):
        self.pkg = os.path.abspath(pkg)
        self.refs = os.path.join(self.pkg, "references")
        self.errors = []
        self.warns = []
        self.mode = None
        self.pkg_version = "0"
        self.scope = None  # L3 冒烟提取的白名单

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warns.append(msg)

    # ---------- L1 结构层 ----------
    def check_structure(self):
        if not os.path.isdir(self.pkg):
            self.err(f"交付包目录不存在: {self.pkg}")
            return
        if not os.path.isdir(self.refs):
            self.err(f"交付包缺少 references/ 目录: {self.pkg}")
            return
        # 模式识别
        if os.path.isfile(os.path.join(self.refs, "cards.json")):
            self.mode = "dashboard"
        elif os.path.isfile(os.path.join(self.refs, "datasets.json")):
            self.mode = "dataset"
        else:
            self.err("references/ 下既无 cards.json（看板模式）也无 datasets.json（数据集直通）——无法识别交付包模式")
            return
        dash = self.mode == "dashboard"

        for fn in ("SKILL.md", "workbench.html"):
            if not os.path.isfile(os.path.join(self.pkg, fn)):
                self.err(f"缺少 {fn}")
        wh = os.path.join(self.pkg, "workbench.html")
        if os.path.isfile(wh) and os.path.getsize(wh) < 10 * 1024:
            self.warn("workbench.html 不足 10KB，疑似生成不完整")
        for fn in ("profile.md", "qa-log.jsonl", "corrections.json", "_meta.json"):
            if not os.path.isfile(os.path.join(self.pkg, "memory", fn)):
                self.err(f"memory/ 缺少 {fn}（记忆区四文件是交付结构的一部分）")
        meta = load_json(os.path.join(self.pkg, "memory", "_meta.json"))
        if meta is not None and "memorySchema" not in meta:
            self.warn("memory/_meta.json 缺少 memorySchema 字段")

        content_files = ["formulas.json", "metrics.json", "dimensions.json",
                         "learningResult.md", "businessKnowledge.md", "insightThinking.md",
                         "examples.json"]
        if dash:
            content_files.append("cards.json")
        else:
            content_files.append("datasets.json")
        for fn in content_files:
            if not os.path.isfile(os.path.join(self.refs, fn)):
                self.err(f"references/ 缺少 {fn}")
        for fn in ("outputFormat.json", "sql-guide.md"):
            if not os.path.isfile(os.path.join(self.refs, fn)):
                self.warn(f"references/ 缺少 {fn}")
        if dash:
            cd = os.path.join(self.refs, "card-data")
            if not os.path.isdir(cd) or not any(f.endswith(".json") for f in os.listdir(cd)):
                self.err("references/card-data/ 缺失或为空——卡片采样是应答缓存与回归基准的数据源")
            elif not os.path.isfile(os.path.join(cd, "_sample_index.json")):
                self.warn("card-data/ 缺少 _sample_index.json（列画像：取值消歧与维度回填的原料）")

        # 脚本齐全性 + 与当前 builder 的漂移
        cards = load_json(os.path.join(self.refs, "cards.json" if dash else "datasets.json")) or {}
        self.pkg_version = (cards.get("_meta") or {}).get("builderVersion") or "0"
        here = os.path.dirname(os.path.abspath(__file__))
        for fn, need_dash, need_ds, since in SCRIPT_LIST:
            if not (need_dash if dash else need_ds):
                continue
            pp = os.path.join(self.refs, fn)
            if not os.path.isfile(pp):
                if ver_tuple(self.pkg_version) < ver_tuple(since):
                    self.warn(f"references/ 缺少 {fn}（{since} 引入；本包搭建于 {self.pkg_version}，可在搭建向导说「升级脚本」补齐）")
                else:
                    self.err(f"references/ 缺少脚本 {fn}")
                continue
            local = os.path.join(here, fn)
            if os.path.isfile(local) and os.path.abspath(local) != os.path.abspath(pp):
                with open(local, "rb") as f:
                    a = f.read()
                with open(pp, "rb") as f:
                    b = f.read()
                if a != b:
                    self.warn(f"脚本 {fn} 与当前 builder（{BUILDER_VERSION}）不一致——交付后可在搭建向导说「升级脚本」更新")

    # ---------- L2 内容层 ----------
    def check_cards_schema(self):
        cards = load_json(os.path.join(self.refs, "cards.json"))
        if cards is None:
            self.err("cards.json 无法解析")
            return
        meta = cards.get("_meta") or {}
        if not meta.get("builderVersion"):
            self.warn("cards.json._meta 缺少 builderVersion（升级提示与体检版本对比的依据）")
        pages_meta = meta.get("pages") or {}
        if not pages_meta:
            self.err("cards.json._meta.pages 为空——范围守卫 pgIds 与超范围话术失去依据")
        else:
            for pid, p in pages_meta.items():
                if not p.get("cardHash"):
                    self.warn(f"_meta.pages[{pid}] 缺少 cardHash（资产体检的改版对比依据）")
                for c in p.get("cards") or []:
                    if not isinstance(c, dict) or not c.get("cdId"):
                        self.err(f"_meta.pages[{pid}].cards 存在无 cdId 的条目")
                        break
        if not meta.get("dsFormulas"):
            self.warn("cards.json._meta 缺少 dsFormulas（SQL 内联口径的来源）")

        pages = {k: v for k, v in cards.items()
                 if not k.startswith("_") and isinstance(v, dict) and "cards" in v}
        if not pages:
            self.err("cards.json 没有任何看板条目")
            return
        new_archive = ver_tuple(self.pkg_version) >= (4, 2, 0)  # filtered/dsUsage 自 v4.2 引入
        for name, page in pages.items():
            cl = page.get("cards")
            if isinstance(cl, dict):
                self.err(f"《{name}》cards 是「名字→摘要」字典形态（{len(cl)} 张）——cdId/measures/"
                         "filtered/filterDetails/筛选器交互字段全部丢失，run_sql 白名单、make_link、"
                         "sample_cards 连锁瘫痪。cards.json 必须由 cards-raw.json 整体复制派生"
                         "（build_package.py），禁止手工重构/裁剪")
                continue
            if not isinstance(cl, list) or not cl:
                self.err(f"《{name}》cards 为空或不是数组")
                continue
            bad = [c for c in cl if not isinstance(c, dict)]
            if bad:
                self.err(f"《{name}》cards 有 {len(bad)} 个条目不是对象（只剩卡片名字符串）——"
                         "cards.json 必须保留完整卡片结构（cdId/measures/filtered/filterDetails/"
                         "筛选器交互字段），否则 run_sql 白名单、make_link、sample_cards 全部瘫痪。"
                         "cards.json 应由 cards-raw.json 整体复制派生（build_package.py），禁止手工裁剪")
                continue
            data = [c for c in cl if c.get("type") != "SELECTOR"]
            sels = [c for c in cl if c.get("type") == "SELECTOR"]
            for c in data:
                if not c.get("cdId") or not c.get("name"):
                    self.err(f"《{name}》存在缺 cdId/name 的数据卡")
                    break
            if data and not any(c.get("measures") for c in data):
                self.err(f"《{name}》所有数据卡都没有 measures——口径字典与 SQL 内联公式失去来源")
            if new_archive and data and not any("filtered" in c for c in data):
                self.err(f"《{name}》数据卡缺少 filtered 标记（v4.2 取数分层：带筛选卡禁止二次加工）")
            if new_archive and not page.get("dsUsage"):
                self.err(f"《{name}》缺少 dsUsage 分级——scope 白名单 dsIds 将从空集派生，"
                         "run_sql 会拦截全部数据集（SQL 直查瘫痪）")
            if sels and not any("inFilterBar" in c and "linkedCardCount" in c for c in sels):
                self.err(f"《{name}》筛选器卡片缺少 inFilterBar/linkedCardCount——"
                         "make_link 判不出可用筛选器（直达链接瘫痪）")

    def check_gates(self):
        """双闸门：用交付包内的校验器自证（references 即工作目录布局）"""
        for gate in ("check_metrics.py", "check_dims.py"):
            gp = os.path.join(self.refs, gate)
            if not os.path.isfile(gp):
                continue  # L1 已报缺失
            code, out = run_cmd([sys.executable, gp, self.refs])
            if code != 0:
                tail = "\n".join(out.strip().splitlines()[-6:])
                self.err(f"{gate} 未通过（exit {code}）:\n{tail}")

    def check_examples(self):
        ex = load_json(os.path.join(self.refs, "examples.json"))
        if ex is None:
            self.err("examples.json 无法解析")
            return
        scenarios = ex.get("scenarios")
        if not isinstance(scenarios, dict) or not scenarios:
            self.err("examples.json 缺少 scenarios——验收基准库为空")
            return
        for name, items in scenarios.items():
            if not isinstance(items, list) or not items:
                self.err(f"场景「{name}」没有示例题——每场景至少 1 题实测验收")
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                tag = f"场景「{name}」{it.get('id', '?')}"
                if not it.get("humanConfirmed"):
                    self.err(f"{tag} humanConfirmed=false——第 7 步验收实测未回填确认"
                             "（eval_examples.py --record/--confirm 回填后再交付）")
                expect = it.get("expect") or {}
                if not expect.get("values") and not expect.get("keywords"):
                    self.err(f"{tag} expect.values/keywords 均空——数据层断言缺失，回归基准形同虚设")
                fetch = it.get("fetch") or {}
                if fetch.get("type", "card") == "card":
                    rel = fetch.get("file")
                    if not rel:
                        self.err(f"{tag} fetch.file 缺失")
                    elif safe_join(self.refs, rel) is None:
                        self.err(f"{tag} fetch.file 路径越界（拒绝绝对路径/../ 逃逸）: {rel}")
                    elif not os.path.isfile(os.path.join(self.refs, rel)):
                        self.err(f"{tag} 引用的采样文件不存在: {rel}——交付即带 broken 回归基准")

    def check_skill_md(self):
        fp = os.path.join(self.pkg, "SKILL.md")
        if not os.path.isfile(fp):
            return  # L1 已报
        with open(fp, encoding="utf-8") as f:
            text = f.read()
        for sec_name, pattern, level in SKILL_SECTIONS:
            if not re.search(pattern, text, re.M):
                msg = (f"SKILL.md 缺少章节「{sec_name}」——交付助手 SKILL.md 必须由模板渲染"
                       "（render_agent_skill.py），禁止自由撰写")
                (self.err if level == "error" else self.warn)(msg)
        leftover = PLACEHOLDER_RE.findall(text)
        if leftover:
            self.err(f"SKILL.md 残留未填充的模板占位符: {'、'.join(sorted(set(leftover))[:5])}")
        if "agent_created: true" not in text:
            self.warn("SKILL.md frontmatter 缺少 agent_created: true")
        for fn in ("learningResult.md", "businessKnowledge.md", "insightThinking.md"):
            fp2 = os.path.join(self.refs, fn)
            if not os.path.isfile(fp2):
                continue
            with open(fp2, encoding="utf-8") as f:
                t = f.read()
            if len(t) < 300:
                self.warn(f"{fn} 内容过短（<300 字符），疑似未实质填写")
            leftover = PLACEHOLDER_RE.findall(t)
            if leftover:
                self.err(f"{fn} 残留未填充的模板占位符: {'、'.join(sorted(set(leftover))[:5])}")

    @staticmethod
    def _script_has_flag(path, flag):
        """检测包内脚本源码是否含某 flag 字面量——旧版脚本功能冒烟的双保险判据"""
        try:
            with open(path, encoding="utf-8") as f:
                return flag in f.read()
        except OSError:
            return False

    # ---------- L3 功能冒烟层 ----------
    def check_smoke(self):
        # scope 白名单：dsIds/cdIds/pgIds 必须从档案实际派生出来
        scope_py = os.path.join(self.refs, "scope.py")
        if not os.path.isfile(scope_py):
            return  # L1 已报
        try:
            scope_mod = load_module(scope_py, "pkg_scope")
            src = "cards.json" if self.mode == "dashboard" else "datasets.json"
            self.scope = scope_mod.load_scope(candidates=[os.path.join(self.refs, src)])
        except Exception as e:  # noqa: BLE001——冒烟层要把任何异常变成 ❌
            self.err(f"scope.py 加载/执行失败: {e}")
            return
        if self.scope is None:
            self.err("scope.load_scope 返回 None——范围守卫整体降级，取数越界拦截失效")
            return
        if not self.scope.get("dsIds"):
            self.err("scope 白名单 dsIds 为空——run_sql 将拦截全部数据集（SQL 直查瘫痪）；"
                     "检查 cards.json 各页 dsUsage 是否丢失")
        if self.mode == "dashboard" and not self.scope.get("cdIds"):
            self.err("scope 白名单 cdIds 为空——sample_cards --scope 将整批拒绝；"
                     "检查 cards.json 卡片条目是否被裁成纯名字")
        if not self.scope.get("pgIds") and self.mode == "dashboard":
            self.err("scope 白名单 pgIds 为空——检查 cards.json._meta.pages")

        # run_sql --check-scope 双向断言：白名单内放行、白名单外拦截。
        # --check-scope 自 builder 4.7.0 引入——包版本过旧或包内脚本源码无该 flag 字面量时
        # 降级 ⚠️（双判据取保守，pkg_version 缺失/为 "0" 同样 graceful），
        # 否则旧脚本会把 "--check-scope" 当 dsId 报 exit 3，误报成「白名单误拦」
        run_sql = os.path.join(self.refs, "run_sql.py")
        if os.path.isfile(run_sql) and self.scope.get("dsIds"):
            version_ok = ver_tuple(self.pkg_version) >= (4, 7, 0)
            has_flag = self._script_has_flag(run_sql, "--check-scope")
            if version_ok and has_flag:
                good = sorted(self.scope["dsIds"])[0]
                code, out = run_cmd([sys.executable, run_sql, "--check-scope", good])
                if code != 0:
                    self.err(f"run_sql --check-scope 误拦白名单内数据集 {good}（exit {code}）: {out.strip()[:200]}")
                code, _ = run_cmd([sys.executable, run_sql, "--check-scope", OUT_OF_SCOPE_PROBE])
                if code != 3:
                    self.err(f"run_sql --check-scope 未拦截白名单外数据集（exit {code}，应为 3）——范围守卫失效")
            else:
                reasons = []
                if not version_ok:
                    reasons.append(f"本包搭建于 builder {self.pkg_version}（--check-scope 自 4.7.0 引入）")
                if not has_flag:
                    reasons.append("包内 run_sql.py 源码无 --check-scope 字面量（旧版脚本）")
                self.warn("跳过 run_sql --check-scope 冒烟：" + "；".join(reasons) +
                          "——在搭建向导说「升级脚本」更新后再体检")

        # run_metric --check-scope 双向断言（仅当档案含 governedRef——无引用时白名单为空，
        # 脚本按设计降级放行，无可断言对象）
        run_metric = os.path.join(self.refs, "run_metric.py")
        metric_ids = self.scope.get("metricIds") or set()
        if os.path.isfile(run_metric) and metric_ids:
            good = sorted(metric_ids)[0]
            code, out = run_cmd([sys.executable, run_metric, "--check-scope", good])
            if code != 0:
                self.err(f"run_metric --check-scope 误拦白名单内指标 {good}（exit {code}）: {out.strip()[:200]}")
            code, _ = run_cmd([sys.executable, run_metric, "--check-scope", OUT_OF_SCOPE_PROBE])
            if code != 3:
                self.err(f"run_metric --check-scope 未拦截白名单外指标（exit {code}，应为 3）——"
                         "指标中心口径白名单失效")

        # make_link --list：至少一张看板有可用筛选器（看板模式）
        if self.mode == "dashboard":
            make_link = os.path.join(self.refs, "make_link.py")
            cards = load_json(os.path.join(self.refs, "cards.json")) or {}
            titles = [k for k, v in cards.items()
                      if not k.startswith("_") and isinstance(v, dict) and "cards" in v]
            usable_total = 0
            if os.path.isfile(make_link):
                for t in titles:
                    code, out = run_cmd([sys.executable, make_link, self.refs, "--list", t])
                    if code != 0:
                        self.err(f"make_link --list 《{t}》执行失败（exit {code}）: {out.strip()[:200]}")
                        continue
                    usable_total += sum(1 for ln in out.splitlines()
                                        if ln.startswith("  ") and not ln.startswith("  ✗")
                                        and "可用筛选器" not in ln)
                if titles and usable_total == 0:
                    self.warn("所有看板都没有可用筛选器——直达链接功能不可用"
                              "（若 cards.json 筛选器字段完整仍如此，属页面本身无联动筛选器）")

        # eval_examples 回归：交付即带 broken 基准是不允许的
        eval_py = os.path.join(self.refs, "eval_examples.py")
        if os.path.isfile(eval_py):
            code, out = run_cmd([sys.executable, eval_py, self.pkg], timeout=300)
            if code == 1:
                tail = "\n".join(out.strip().splitlines()[-8:])
                self.err(f"eval_examples 回归存在数据层失败（exit 1）:\n{tail}")
            elif code not in (0, 1):
                self.err(f"eval_examples 执行异常（exit {code}）: {out.strip()[:200]}")

        # memory status：记忆系统脚本可用
        mem_py = os.path.join(self.refs, "memory.py")
        if os.path.isfile(mem_py):
            code, out = run_cmd([sys.executable, mem_py, "status", self.pkg])
            if code != 0:
                self.err(f"memory.py status 执行失败（exit {code}）: {out.strip()[:200]}")

    def run(self):
        self.check_structure()
        if self.mode == "dashboard":
            self.check_cards_schema()
        self.check_gates()
        self.check_examples()
        self.check_skill_md()
        if self.mode:
            self.check_smoke()
        return self


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = len(args) != len(sys.argv) - 1
    if not args:
        sys.exit("用法: python3 check_package.py <交付包路径> [--json]")
    chk = PackageCheck(args[0]).run()
    result = "fail" if chk.errors else "pass"
    if as_json:
        print(json.dumps({
            "package": chk.pkg, "mode": chk.mode, "builderVersion": chk.pkg_version,
            "result": result, "errors": chk.errors, "warnings": chk.warns,
        }, ensure_ascii=False, indent=1))
    else:
        mode_label = {"dashboard": "看板模式", "dataset": "数据集直通模式"}.get(chk.mode, "未知")
        print(f"\n交付包体检（{chk.pkg}）")
        print("=" * 60)
        print(f"模式: {mode_label}｜包搭建于 builder {chk.pkg_version}｜当前 builder {BUILDER_VERSION}")
        for e in chk.errors:
            print(f"  ❌ {e}")
        for w in chk.warns:
            print(f"  ⚠️  {w}")
        if chk.errors:
            print(f"\n{len(chk.errors)} 个 ❌ 未清零——禁止交付；修复后重跑本脚本")
        else:
            print(f"\n✅ 体检通过" + (f"（{len(chk.warns)} 条 ⚠️ 需告知用户）" if chk.warns else ""))
    sys.exit(1 if chk.errors else 0)


if __name__ == "__main__":
    main()
