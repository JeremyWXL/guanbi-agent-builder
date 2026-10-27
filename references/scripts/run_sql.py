#!/usr/bin/env python3
"""
只读 SQL 执行器：guancli ds execute-sql 的安全包装层
SQL 直查一律走本脚本，禁止直接调用 guancli ds execute-sql——
prompt 红线靠自觉，本脚本提供脚本层强制：只允许单条 SELECT/WITH 查询，
且数据集必须在助手覆盖范围内（范围守卫白名单，越界 exit 3 拦截）。
用法:
  python3 run_sql.py <数据集ID> '<SQL>'            # 表格输出（默认）
  python3 run_sql.py <数据集ID> '<SQL>' -f json    # 透传 guancli 输出格式
  python3 run_sql.py <数据集ID> '<SQL>' --no-scope # 仅独立调试显式跳过范围校验
  python3 run_sql.py --check-scope <数据集ID>      # 只验白名单不执行 SQL（体检/冒烟用）：
                                                   # 在覆盖范围内 exit 0，越界或 scope 缺失 exit 3
校验规则（违反即 exit 3，不执行）:
  1. 去除注释与字符串字面量后，必须以 SELECT 或 WITH 开头
  2. 禁止多语句（; 后还有内容）
  3. 禁止写操作/管理操作关键字（INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/...）
  4. 范围守卫：数据集 ID 必须在 scope 白名单内（看板模式从 cards.json 的 dsUsage 派生，
     数据集直通模式从 datasets.json 已学条目派生；找不到 scope 默认拒绝，
     脱离交付包的独立调试须显式传 --no-scope）
执行层辅助:
  - 裸中文表名自动补反引号（字符串字面量段不动；已带引号的不重复补）
  - 平台报错提炼友好文案（TABLE_OR_VIEW_NOT_FOUND 等 500 堆栈 → 可行动结论），
    成功时 stdout/stderr 原样透传
"""
import os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scope as scope_mod
except ImportError:
    scope_mod = None  # 缺失时 scope_check 默认拒绝；独立调试须显式 --no-scope

BLOCKED = ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE',
           'GRANT', 'REVOKE', 'MERGE', 'REPLACE', 'CALL', 'EXEC', 'EXECUTE',
           'SET', 'USE', 'SHOW', 'DESCRIBE', 'EXPLAIN')

CJK_TABLE_RE = re.compile(r'(?i)\b(FROM|JOIN)\s+(?![`"\'])([一-鿿][\w一-鿿.\-]*)')
_STRING_SEG_RE = re.compile(r"('(?:[^'\\]|\\.|'')*')")


def quote_cjk_tables(sql):
    """裸中文表名自动补反引号（平台要求中文表名加反引号，v4.3.0 遗留 P2）。
    已带反引号/引号的不动；字符串字面量段（如 WHERE col='FROM 表X'）不动。
    返回 (改写后 SQL, [补了反引号的表名])"""
    added = []

    def _wrap(m):
        added.append(m.group(2))
        return f"{m.group(1)} `{m.group(2)}`"

    parts = _STRING_SEG_RE.split(sql)
    for i, part in enumerate(parts):
        if i % 2 == 1:  # 奇数段是字符串字面量
            continue
        parts[i] = CJK_TABLE_RE.sub(_wrap, part)
    return "".join(parts), added


def friendly_error(raw, sql, ds_id):
    """平台报错提炼：把 500 堆栈里可行动的结论挖出来，而不是整段 stack trace 倒给用户
    （v4.8.0 挂账 P2：TABLE_OR_VIEW_NOT_FOUND 埋在 details 里）"""
    text = raw or ""
    if "TABLE_OR_VIEW_NOT_FOUND" in text:
        tables = re.findall(r'(?i)\b(?:FROM|JOIN)\s+`?([^\s,`()]+)`?', sql)
        hint = f"——SQL 引用的表：{'、'.join(tables)}" if tables else ""
        return (f"❌ 表或视图不存在{hint}\n"
                f"  用 `guancli ds get {ds_id} --brief` 核对数据集实际表名；"
                f"中文表名需反引号包裹（本脚本已自动补，仍失败则表名本身不对）")
    m = re.search(r'"?message"?\s*[=:]\s*"?([^,}\n"]+)', text)
    if m:
        return f"❌ SQL 执行失败: {m.group(1).strip()}"
    return f"❌ SQL 执行失败（平台报错摘录）: {text.strip()[:300]}"


def strip_literals_and_comments(sql):
    """单次扫描：先识别字面量，再识别注释，注释标记不能改变字面量边界。"""
    out = []
    i = 0
    n = len(sql)
    while i < n:
        if sql.startswith("--", i):
            end = sql.find("\n", i + 2)
            i = n if end < 0 else end
            out.append(" ")
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
            continue
        char = sql[i]
        if char in ("'", '"', "`"):
            quote = char
            out.append(quote * 2)
            i += 1
            while i < n:
                if sql[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def validate(sql):
    """返回 None（通过）或错误信息"""
    cleaned = strip_literals_and_comments(sql).strip()
    if not cleaned:
        return "SQL 为空"
    first = cleaned.split(None, 1)[0].upper().rstrip('(')
    if first not in ('SELECT', 'WITH'):
        return f"只允许 SELECT/WITH 查询，检测到以 {first!r} 开头"
    body = cleaned.rstrip().rstrip(';')
    if ';' in body:
        return "禁止多语句执行（检测到分号后的额外语句）"
    for kw in BLOCKED:
        if re.search(rf'\b{kw}\b', body, re.I):
            return f"检测到被禁止的关键字 {kw}（本工具仅支持只读查询）"
    return None


def scope_check(ds_id, allow_no_scope=False, scope_path=None):
    """白名单 dry 校验；默认 fail closed，独立调试须显式 --no-scope。"""
    if allow_no_scope:
        print("⚠️ 已显式指定 --no-scope：本次不校验数据集白名单", file=sys.stderr)
        return None
    candidates = [scope_path] if scope_path else None
    scope = scope_mod.load_scope(candidates=candidates) if scope_mod is not None else None
    if scope is None:
        return "未找到范围档案，已拒绝 SQL 取数；请传 --scope <cards.json/cards-raw.json/datasets-raw.json> 或显式 --no-scope"
    if ds_id not in scope["dsIds"]:
        src = os.path.basename(scope.get("source") or "")
        hint = ("references/datasets.json 的已学数据集" if src == "datasets.json"
                else "references/cards.json 的 dsUsage")
        return (f"数据集 {ds_id} 不在本助手覆盖范围（脚本层白名单拦截）\n"
                f"覆盖范围见 {hint}；如需接入新数据，回到搭建向导说「增量学习」。")
    return None


def main():
    args = sys.argv[1:]
    allow_no_scope = "--no-scope" in args
    args = [arg for arg in args if arg != "--no-scope"]
    scope_path = None
    if "--scope" in args:
        i = args.index("--scope")
        if i + 1 >= len(args):
            sys.exit("--scope 需要 cards.json/cards-raw.json/datasets-raw.json 路径")
        scope_path = args[i + 1]
        args = args[:i] + args[i + 2:]
    # --check-scope <数据集ID>：只验白名单不调 guancli（check_package 功能冒烟用）
    if "--check-scope" in args:
        i = args.index("--check-scope")
        if i + 1 >= len(args):
            sys.exit("用法: python3 run_sql.py --check-scope <数据集ID>")
        err = scope_check(args[i + 1], scope_path=scope_path)
        if err:
            print(f"❌ {err}", file=sys.stderr)
            sys.exit(3)
        print(f"✅ 数据集 {args[i + 1]} 在覆盖范围内")
        sys.exit(0)
    fmt = "table"
    if "-f" in args:
        i = args.index("-f")
        fmt = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) < 2:
        sys.exit("用法: python3 run_sql.py <数据集ID> '<SQL>' [-f table|json|csv]")
    ds_id, sql = args[0], args[1]
    # 范围守卫：覆盖外的数据集禁止当答案（信噪比纪律的脚本层强制）
    err = scope_check(ds_id, allow_no_scope=allow_no_scope, scope_path=scope_path)
    if err:
        print(f"❌ {err}", file=sys.stderr)
        sys.exit(3)
    err = validate(sql)
    if err:
        print(f"❌ SQL 被只读校验拦截: {err}", file=sys.stderr)
        print("SQL 直查仅支持单条 SELECT 查询；如需写操作请改用 BI 平台。", file=sys.stderr)
        sys.exit(3)
    sql, quoted = quote_cjk_tables(sql)
    if quoted:
        print(f"ℹ️ 已自动为中文表名补反引号：{'、'.join(quoted)}", file=sys.stderr)
    r = subprocess.run(["guancli", "ds", "execute-sql", "-inputs", ds_id,
                        "-sql", sql, "-f", fmt], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(friendly_error(r.stderr or r.stdout or "", sql, ds_id), file=sys.stderr)
        sys.exit(r.returncode)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    sys.exit(0)


if __name__ == '__main__':
    main()
