#!/usr/bin/env python3
"""
示例回归评测器：看板改版重新学习后，一键重跑 examples.json 里的典型问题，
回答"新 agent 和旧 agent 一样准吗"。
用法:
  python3 eval_examples.py <工作目录>                  # 全量回归
  python3 eval_examples.py <工作目录> --scenario 问数   # 只跑某场景
  python3 eval_examples.py <工作目录> --json           # 结构化 JSON 输出
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


def eval_card(base_dir, ex):
    """fetch.type=card：读采样文件核验。返回 (status, reasons, answerPoints)。
    base_dir = examples.json 所在目录（工作目录，或交付包的 references/）"""
    fetch = ex.get('fetch') or {}
    rel = fetch.get('file')
    if not rel:
        return 'fail', ["fetch.file 缺失"], ex.get('answerPoints') or []
    path = os.path.join(base_dir, rel)
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


def main():
    args = sys.argv[1:]
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

    if as_json:
        print(json.dumps({
            "workdir": workdir,
            "scenarioFilter": scenario_filter,
            "scenarios": {n: {**per_scenario[n], "items": results[n]} for n in results},
            "total": {**total, "passRate": pass_rate},
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
        if total['fail']:
            print("结论: ❌ 存在数据层失败——新 agent 与旧 agent 表现不一致，需排查失败条目（可能看板已改版需重新学习）")
        elif total['pending']:
            print("结论: ✅ 数据层全部通过；仍有结论要点待人工确认，请核对上方 📋 清单后把 humanConfirmed 置为 true")
        else:
            print("结论: ✅ 全部通过——新 agent 与旧 agent 一样准")

    sys.exit(1 if total['fail'] else 0)


if __name__ == '__main__':
    main()
