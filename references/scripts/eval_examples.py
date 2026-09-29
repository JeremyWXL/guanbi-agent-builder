#!/usr/bin/env python3
"""
示例回归评测器：看板改版重新学习后，一键重跑 examples.json 里的典型问题，
回答"新 agent 和旧 agent 一样准吗"。
用法:
  python3 eval_examples.py <工作目录>                  # 全量回归
  python3 eval_examples.py <工作目录> --scenario 问数   # 只跑某场景
  python3 eval_examples.py <工作目录> --json           # 结构化 JSON 输出
  python3 eval_examples.py <工作目录> --suggest [题目ID]        # 打印取数源里的显著数值（回填候选）
  python3 eval_examples.py <工作目录> --record <题目ID> --values "41990, 3.64" [--keywords "净收入,实际"]
                                                          # 第 7 步验收回填：数值必须能在取数源中找到
                                                          # （容差内匹配，找不到即拒绝——幻觉数字进不了基准），
                                                          # 回填后该题 humanConfirmed 重置为 false
  python3 eval_examples.py <工作目录> --confirm <题目ID> | --confirm-all
                                                          # 用户验收通过后置 humanConfirmed=true
                                                          #（wizard_state confirm --step 7 的硬性依据）
判定逻辑:
  1. 数据层自动核验（脚本可判）:
     - fetch.type=card: 读 card-data 采样文件，检查 expect.values 每个数值
       是否能在数据中找到（容差范围内匹配任意单元格）、keywords 是否出现
     - fetch.type=sql: 调用 run_sql.py 重跑（优先 <工作目录>/references/scripts/run_sql.py，
       回退与本脚本同目录的 run_sql.py），对结果文本做同样匹配；
       run_sql.py 不可用时该条记 skip 而非 fail
     - 数值匹配容忍货币符号（￥1,234）、千分位（1,234.5）、百分号（35% ≈ 0.35）、中文单位（71万 ≈ 710000）
  2. 结论层人工核对: answerPoints 无法自动判，逐条打印为核对清单；
     humanConfirmed=false 的条目单独统计「待人工确认」
工作目录形态:
  examples.json 优先取 <工作目录>/examples.json；缺失时回退 <工作目录>/references/examples.json
  （交付包形态），fetch.file 相对 examples.json 所在目录解析——交付包根目录直接
  `python3 references/eval_examples.py .` 即可，无需软链
退出码: 0=全部通过（或仅有待确认项）, 1=存在数据层失败, 2=examples.json 缺失/格式错误
"""
import json, os, re, subprocess, sys

DEFAULT_TOLERANCE = 0.02
SQL_TIMEOUT = 180
NUM_TOKEN = re.compile(r'[￥$¥]?\s*-?\d[\d,]*(?:\.\d+)?\s*(?:%|万|亿)?')


def num_candidates(v):
    """把单元格/文本值解析成候选浮点数，容忍货币符号（￥/$/¥）、千分位、百分号、中文单位（万/亿）"""
    if isinstance(v, bool):
        return []
    if isinstance(v, (int, float)):
        return [float(v)]
    s = str(v).strip()
    if not s:
        return []
    mult = 1.0
    if '亿' in s:
        mult = 1e8
    elif '万' in s:
        mult = 1e4
    pct = '%' in s
    cleaned = (s.replace(',', '').replace('%', '').replace('万', '').replace('亿', '')
               .replace('￥', '').replace('$', '').replace('¥', '').strip())
    try:
        n = float(cleaned)
    except ValueError:
        return []
    cands = [n * mult]
    if pct:
        cands.append(n * mult / 100.0)
    return cands


def collect_candidates(obj, acc):
    """递归遍历 JSON 结构，把所有叶子值解析成候选数值"""
    if isinstance(obj, dict):
        for v in obj.values():
            collect_candidates(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            collect_candidates(v, acc)
    else:
        acc.extend(num_candidates(obj))


def value_hit(expected, candidates, tol):
    """期望值是否在候选数值中出现（相对容差）"""
    return any(abs(c - expected) <= tol * max(abs(expected), 1e-9) for c in candidates)


def check_expect(ex, text, candidates):
    """返回 (ok, reasons)。text 用于关键词匹配，candidates 用于数值匹配"""
    expect = ex.get('expect') or {}
    tol = expect.get('tolerance', DEFAULT_TOLERANCE)
    reasons = []
    for v in expect.get('values') or []:
        if not value_hit(float(v), candidates, tol):
            sample = ', '.join(f'{c:,.4g}' for c in candidates[:8]) or '（无数值）'
            reasons.append(f"期望值 {v} 未在数据中找到（容差 {tol:.0%}）；数据中的数值样本: {sample}")
    for kw in expect.get('keywords') or []:
        if str(kw) not in text:
            reasons.append(f"关键词「{kw}」未在数据中出现")
    return (not reasons), reasons


def safe_join(base_dir, rel):
    """fetch.file 目录边界校验：拒绝绝对路径与 ../ / 符号链接逃逸。
    realpath 后必须仍落在 base_dir 内，否则返回 None。"""
    if not rel or os.path.isabs(rel):
        return None
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, rel))
    try:
        if os.path.commonpath([base, target]) != base:
            return None
    except ValueError:  # 路径形态无法比较（如跨盘符），一律拒绝
        return None
    return target


def eval_card(base_dir, ex):
    """fetch.type=card：读采样文件核验。返回 (status, reasons, answerPoints)。
    base_dir = examples.json 所在目录（工作目录，或交付包的 references/）"""
    fetch = ex.get('fetch') or {}
    rel = fetch.get('file')
    if not rel:
        return 'fail', ["fetch.file 缺失"], ex.get('answerPoints') or []
    path = safe_join(base_dir, rel)
    if path is None:
        return 'fail', [f"fetch.file 路径越界（拒绝绝对路径/../ 逃逸）: {rel}"], ex.get('answerPoints') or []
    if not os.path.isfile(path):
        return 'fail', [f"采样文件缺失: {rel}（看板可能已改版，需要重新学习）"], ex.get('answerPoints') or []
    try:
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return 'fail', [f"采样文件无法解析: {rel}（{e}）"], ex.get('answerPoints') or []
    text = json.dumps(payload, ensure_ascii=False)
    candidates = []
    collect_candidates(payload, candidates)
    ok, reasons = check_expect(ex, text, candidates)
    return ('pass' if ok else 'fail'), reasons, ex.get('answerPoints') or []


def find_run_sql(workdir, script_dir):
    """run_sql.py 定位：优先工作目录产物包内，回退与本脚本同目录"""
    for cand in (os.path.join(workdir, 'references', 'scripts', 'run_sql.py'),
                 os.path.join(script_dir, 'run_sql.py')):
        if os.path.isfile(cand):
            return cand
    return None


def eval_sql(workdir, ex, script_dir):
    """fetch.type=sql：经 run_sql.py 重跑核验。run_sql 不可用记 skip"""
    fetch = ex.get('fetch') or {}
    sql, ds_id = fetch.get('sql'), fetch.get('dsId')
    if not sql or not ds_id:
        return 'fail', ["fetch.sql / fetch.dsId 缺失"], ex.get('answerPoints') or []
    run_sql = find_run_sql(workdir, script_dir)
    if not run_sql:
        return 'skip', ["run_sql.py 不可用（既不在 <工作目录>/references/scripts/ 也不在本脚本同目录），跳过 SQL 重跑"], ex.get('answerPoints') or []
    try:
        r = subprocess.run([sys.executable, run_sql, str(ds_id), sql, '-f', 'json'],
                           capture_output=True, text=True, timeout=SQL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 'skip', [f"run_sql.py 执行失败（{e}），跳过"], ex.get('answerPoints') or []
    if r.returncode != 0:
        return 'fail', [f"run_sql.py 返回非 0（exit {r.returncode}）: {(r.stderr or r.stdout)[:200]}"], ex.get('answerPoints') or []
    text = r.stdout
    candidates = []
    for tok in NUM_TOKEN.findall(text):
        candidates.extend(num_candidates(tok))
    ok, reasons = check_expect(ex, text, candidates)
    return ('pass' if ok else 'fail'), reasons, ex.get('answerPoints') or []


MISSING_HINT = (
    "未找到 examples.json。请先在搭建向导第 5/7 步与用户确认典型问题并沉淀示例，"
    "或从 references/templates/examples.json 复制起步，填写后置于 <工作目录>/examples.json"
)


# ---------- 第 7 步验收回填工具（--suggest / --record / --confirm） ----------

def load_examples(workdir):
    """定位并解析 examples.json（工作目录根优先，回退交付包 references/）。返回 (路径, base_dir, doc)"""
    ex_path = os.path.join(workdir, 'examples.json')
    if not os.path.isfile(ex_path):
        alt = os.path.join(workdir, 'references', 'examples.json')
        if os.path.isfile(alt):
            ex_path = alt
    if not os.path.isfile(ex_path):
        print(f"❌ {MISSING_HINT}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(ex_path, encoding='utf-8') as f:
            doc = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        print(f"❌ examples.json 格式错误，无法解析: {e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(doc.get('scenarios'), dict):
        print("❌ examples.json 缺少 scenarios 对象，格式错误", file=sys.stderr)
        sys.exit(2)
    return ex_path, os.path.dirname(ex_path), doc


def find_item(doc, qid):
    """按 id 找题目。返回 (item, 场景名)；找不到 exit 2 并列出可用 id"""
    for sname, items in doc['scenarios'].items():
        for it in items or []:
            if isinstance(it, dict) and it.get('id') == qid:
                return it, sname
    avail = [it.get('id') for items in doc['scenarios'].values()
             for it in (items or []) if isinstance(it, dict)]
    print(f"❌ 找不到题目「{qid}」；已有题目: {'、'.join(avail) or '（空）'}", file=sys.stderr)
    sys.exit(2)


def source_text_and_candidates(workdir, base_dir, ex, script_dir):
    """取数源的文本与数值候选（--record 的防幻觉校验基准）。返回 (ok, text, candidates, err)"""
    fetch = ex.get('fetch') or {}
    if fetch.get('type', 'card') == 'sql':
        sql, ds_id = fetch.get('sql'), fetch.get('dsId')
        if not sql or not ds_id:
            return False, "", [], "fetch.sql / fetch.dsId 缺失"
        run_sql = find_run_sql(workdir, script_dir)
        if not run_sql:
            return False, "", [], "run_sql.py 不可用，无法校验 SQL 取数源"
        try:
            r = subprocess.run([sys.executable, run_sql, str(ds_id), sql, '-f', 'json'],
                               capture_output=True, text=True, timeout=SQL_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, "", [], f"run_sql.py 执行失败（{e}）"
        if r.returncode != 0:
            return False, "", [], f"run_sql.py 返回非 0: {(r.stderr or r.stdout)[:200]}"
        text = r.stdout
        candidates = []
        for tok in NUM_TOKEN.findall(text):
            candidates.extend(num_candidates(tok))
        return True, text, candidates, ""
    rel = fetch.get('file')
    if not rel:
        return False, "", [], "fetch.file 缺失"
    path = safe_join(base_dir, rel)
    if path is None:
        return False, "", [], f"fetch.file 路径越界（拒绝绝对路径/../ 逃逸）: {rel}"
    if not os.path.isfile(path):
        return False, "", [], f"采样文件缺失: {rel}"
    try:
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return False, "", [], f"采样文件无法解析: {rel}（{e}）"
    text = json.dumps(payload, ensure_ascii=False)
    candidates = []
    collect_candidates(payload, candidates)
    return True, text, candidates, ""


def match_source_value(tok, candidates, tol):
    """输入数值文本 → 取数源中的真实值（千分位/%/万/亿 任一解释在容差内命中即返回源值；未命中 None）"""
    for ic in num_candidates(tok):
        for sc in candidates:
            if abs(sc - ic) <= tol * max(abs(ic), 1e-9):
                return sc
    return None


def save_examples(ex_path, doc):
    from datetime import date
    doc['updatedAt'] = date.today().isoformat()
    with open(ex_path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")


def fmt_num(c):
    """显著数值展示：整数带千分位，小数保留有效位（不用科学计数法）"""
    if c == int(c) and abs(c) < 1e15:
        return f"{int(c):,}"
    return f"{c:,.6g}"


def cmd_suggest(workdir, qid, script_dir):
    """打印取数源里的显著数值（按绝对值降序 Top 12），辅助挑选 --record 的期望值"""
    _, base_dir, doc = load_examples(workdir)
    items = []
    for sname, rows in doc['scenarios'].items():
        for it in rows or []:
            if isinstance(it, dict) and (qid is None or it.get('id') == qid):
                items.append((sname, it))
    if qid and not items:
        find_item(doc, qid)  # 走到这必然 exit 2
    for sname, it in items:
        ok, _, candidates, err = source_text_and_candidates(workdir, base_dir, it, script_dir)
        print(f"【{sname}】{it.get('id')} 「{it.get('question', '')}」")
        if not ok:
            print(f"   ⚠️ 取数源不可用: {err}")
            continue
        uniq = sorted({round(c, 6) for c in candidates}, key=abs, reverse=True)[:12]
        print(f"   显著数值: {'、'.join(fmt_num(c) for c in uniq) or '（无）'}")
        print(f"   回填命令: --record {it.get('id')} --values \"<从上面挑验收过的数值>\" [--keywords \"关键词1,关键词2\"]")


def cmd_record(workdir, qid, values_str, keywords_str, tol_override, script_dir):
    """验收回填：期望值必须在取数源中真实存在（容差内），否则拒绝——幻觉数字进不了回归基准"""
    ex_path, base_dir, doc = load_examples(workdir)
    item, sname = find_item(doc, qid)
    ok, text, candidates, err = source_text_and_candidates(workdir, base_dir, item, script_dir)
    if not ok:
        print(f"❌ 无法校验取数源: {err}", file=sys.stderr)
        sys.exit(2)
    tol = tol_override if tol_override is not None \
        else (item.get('expect') or {}).get('tolerance', DEFAULT_TOLERANCE)
    tokens = [t.strip() for t in NUM_TOKEN.findall(values_str or "") if t.strip()]
    if not tokens:
        print(f"❌ --values 未解析到数值: {values_str!r}", file=sys.stderr)
        sys.exit(2)
    matched, missed = [], []
    for tok in tokens:
        sc = match_source_value(tok, candidates, tol)
        if sc is None:
            missed.append(tok)
        elif sc not in matched:
            matched.append(sc)
    if missed:
        sample = '、'.join(fmt_num(c) for c in sorted({round(c, 6) for c in candidates},
                                                     key=abs, reverse=True)[:10]) or '（无）'
        print(f"❌ 以下数值在取数源中找不到（容差 {tol:.0%}），拒绝回填: {'、'.join(missed)}\n"
              f"   取数源中的显著数值: {sample}\n"
              f"   ——期望值必须来自真实取数结果，禁止把记忆/推算的数字写进验收基准",
              file=sys.stderr)
        sys.exit(2)
    keywords = None
    if keywords_str is not None:
        keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
        absent = [k for k in keywords if k not in text]
        if absent:
            print(f"❌ 关键词未在取数源文本中出现，拒绝回填: {'、'.join(absent)}", file=sys.stderr)
            sys.exit(2)
    expect = item.setdefault('expect', {})
    expect['values'] = matched
    if tol_override is not None:
        expect['tolerance'] = tol_override
    if keywords is not None:
        expect['keywords'] = keywords
    was = bool(item.get('humanConfirmed'))
    item['humanConfirmed'] = False  # 新期望需重新验收
    save_examples(ex_path, doc)
    print(f"✅ 已回填【{sname}】{qid}: values={matched}"
          + (f"，keywords={keywords}" if keywords is not None else ""))
    if was:
        print("   该题原已验收，期望值变更后 humanConfirmed 已重置——请用户重新验收")
    print(f"   用户验收通过后执行: --confirm {qid}")


def cmd_confirm(workdir, qid):
    """用户验收通过后置 humanConfirmed=true；expect 为空的题拒绝确认（无数据断言的基准形同虚设）"""
    ex_path, _, doc = load_examples(workdir)
    targets = []
    if qid is None:  # --confirm-all
        for rows in doc['scenarios'].values():
            targets.extend(it for it in (rows or []) if isinstance(it, dict))
    else:
        targets.append(find_item(doc, qid)[0])
    for it in targets:
        expect = it.get('expect') or {}
        if not expect.get('values') and not expect.get('keywords'):
            print(f"❌ {it.get('id', '?')} 的 expect.values/keywords 均空——先 --record 回填数据层断言，再确认",
                  file=sys.stderr)
            sys.exit(2)
    for it in targets:
        it['humanConfirmed'] = True
    save_examples(ex_path, doc)
    print(f"✅ 已确认 {len(targets)} 题（humanConfirmed=true）——验收基准可用于交付与回归")


def main():
    args = sys.argv[1:]
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # ---- 验收回填模式（--suggest / --record / --confirm）----
    if any(f in args for f in ('--record', '--confirm', '--confirm-all', '--suggest')):
        if not args or args[0].startswith('--'):
            sys.exit("用法: python3 eval_examples.py <工作目录> --record <题目ID> --values \"...\" "
                     "[--keywords \"...\"] [--tolerance 0.02] | --confirm <题目ID> | --confirm-all | --suggest [题目ID]")
        workdir = os.path.abspath(args[0])
        rest = args[1:]
        def opt_value(flag):
            if flag in rest:
                i = rest.index(flag)
                if i + 1 < len(rest):
                    return rest[i + 1]
                sys.exit(f"{flag} 需要跟一个值")
            return None
        if '--suggest' in rest:
            i = rest.index('--suggest')
            qid = rest[i + 1] if i + 1 < len(rest) and not rest[i + 1].startswith('--') else None
            cmd_suggest(workdir, qid, script_dir)
            return
        if '--confirm-all' in rest:
            cmd_confirm(workdir, None)
            return
        if '--confirm' in rest:
            cmd_confirm(workdir, opt_value('--confirm'))
            return
        tol = None
        tol_str = opt_value('--tolerance')
        if tol_str is not None:
            try:
                tol = float(tol_str)
            except ValueError:
                sys.exit(f"--tolerance 必须是数字: {tol_str!r}")
        cmd_record(workdir, opt_value('--record'), opt_value('--values'),
                   opt_value('--keywords'), tol, script_dir)
        return

    # ---- 回归评测模式 ----
    as_json = '--json' in args
    if as_json:
        args.remove('--json')
    scenario_filter = None
    if '--scenario' in args:
        i = args.index('--scenario')
        try:
            scenario_filter = args[i + 1]
        except IndexError:
            sys.exit("--scenario 需要跟一个场景名（如：问数）")
        args = args[:i] + args[i + 2:]
    if not args:
        sys.exit("用法: python3 eval_examples.py <工作目录> [--scenario 场景名] [--json]")
    workdir = os.path.abspath(args[0])
    script_dir = os.path.dirname(os.path.abspath(__file__))

    ex_path = os.path.join(workdir, 'examples.json')
    if not os.path.isfile(ex_path):
        # 交付包形态：examples.json 与 card-data/ 都在 references/ 下
        alt = os.path.join(workdir, 'references', 'examples.json')
        if os.path.isfile(alt):
            ex_path = alt
    if not os.path.isfile(ex_path):
        print(f"❌ {MISSING_HINT}", file=sys.stderr)
        sys.exit(2)
    base_dir = os.path.dirname(ex_path)  # fetch.file 相对 examples.json 所在目录解析
    try:
        with open(ex_path, encoding='utf-8') as f:
            doc = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        print(f"❌ examples.json 格式错误，无法解析: {e}", file=sys.stderr)
        print("   请对照 references/templates/examples.json 检查 JSON 结构", file=sys.stderr)
        sys.exit(2)
    scenarios = doc.get('scenarios')
    if not isinstance(scenarios, dict):
        print("❌ examples.json 缺少 scenarios 对象，格式错误", file=sys.stderr)
        sys.exit(2)
    if scenario_filter and scenario_filter not in scenarios:
        print(f"❌ 场景「{scenario_filter}」不存在；已有场景: {', '.join(scenarios) or '（空）'}", file=sys.stderr)
        sys.exit(2)

    # 逐条评测
    results = {}  # scenario -> [item]
    fetch_mix = {"card": 0, "sql": 0}  # v4.2 取数路径统计：card=应答缓存（成本近零），sql=现算
    for name, items in scenarios.items():
        if scenario_filter and name != scenario_filter:
            continue
        if not isinstance(items, list):
            continue
        rows = []
        for ex in items:
            if not isinstance(ex, dict):
                continue
            fetch_type = (ex.get('fetch') or {}).get('type', 'card')
            fetch_mix["sql" if fetch_type == 'sql' else "card"] += 1
            if fetch_type == 'sql':
                status, reasons, points = eval_sql(workdir, ex, script_dir)
            else:
                status, reasons, points = eval_card(base_dir, ex)
            rows.append({
                "id": ex.get('id', '?'),
                "question": ex.get('question', ''),
                "status": status,
                "reasons": reasons,
                "answerPoints": points,
                "humanConfirmed": bool(ex.get('humanConfirmed')),
            })
        results[name] = rows

    # 汇总
    def tally(rows):
        t = {"pass": 0, "fail": 0, "skip": 0, "pending": 0}
        for r in rows:
            t[r['status']] += 1
            if not r['humanConfirmed']:
                t['pending'] += 1
        return t

    total = {"pass": 0, "fail": 0, "skip": 0, "pending": 0}
    per_scenario = {}
    for name, rows in results.items():
        t = tally(rows)
        per_scenario[name] = t
        for k in total:
            total[k] += t[k]

    judged = total['pass'] + total['fail']
    pass_rate = (total['pass'] / judged) if judged else None
    n_fetch = fetch_mix['card'] + fetch_mix['sql']
    cache_share = (fetch_mix['card'] / n_fetch) if n_fetch else None

    if as_json:
        print(json.dumps({
            "workdir": workdir,
            "scenarioFilter": scenario_filter,
            "scenarios": {n: {**per_scenario[n], "items": results[n]} for n in results},
            "total": {**total, "passRate": pass_rate},
            "fetchMix": {**fetch_mix, "cacheShare": cache_share},
        }, ensure_ascii=False, indent=1))
    else:
        print("===== 示例回归评测报告 =====")
        print(f"工作目录: {workdir}" + (f"（仅场景: {scenario_filter}）" if scenario_filter else ""))
        for name, rows in results.items():
            t = per_scenario[name]
            d = t['pass'] + t['fail']
            rate = f"{t['pass']/d:.0%}" if d else "—"
            print(f"\n【{name}】通过 {t['pass']} / 失败 {t['fail']} / 跳过 {t['skip']} / 待人工确认 {t['pending']}（通过率 {rate}，跳过不计）")
            for r in rows:
                icon = {'pass': '✅', 'fail': '❌', 'skip': '⏭️'}[r['status']]
                print(f"  {icon} {r['id']} 「{r['question']}」")
                for reason in r['reasons']:
                    print(f"      {reason}")
                if r['answerPoints']:
                    mark = '已确认' if r['humanConfirmed'] else '待人工确认'
                    print(f"      📋 结论核对清单（{mark}）:")
                    for p in r['answerPoints']:
                        print(f"         - {p}")
        print(f"\n总体: 通过 {total['pass']} / 失败 {total['fail']} / 跳过 {total['skip']} / 待人工确认 {total['pending']}")
        if n_fetch:
            print(f"取数路径: 卡片缓存 {fetch_mix['card']} 条 / SQL 直查 {fetch_mix['sql']} 条"
                  f"（缓存占比 {cache_share:.0%}——缓存条目命中卡片形态，回归取数成本近零）")
        if total['fail']:
            print("结论: ❌ 存在数据层失败——新 agent 与旧 agent 表现不一致，需排查失败条目（可能看板已改版需重新学习）")
        elif total['pending']:
            print("结论: ✅ 数据层全部通过；仍有结论要点待人工确认，请核对上方 📋 清单后把 humanConfirmed 置为 true")
        else:
            print("结论: ✅ 全部通过——新 agent 与旧 agent 一样准")

    sys.exit(1 if total['fail'] else 0)


if __name__ == '__main__':
    main()
