#!/usr/bin/env python3
"""
只读 SQL 执行器：guancli ds execute-sql 的安全包装层
SQL 直查一律走本脚本，禁止直接调用 guancli ds execute-sql——
prompt 红线靠自觉，本脚本提供脚本层强制：只允许单条 SELECT/WITH 查询，
且数据集必须在助手覆盖范围内（范围守卫白名单，越界 exit 3 拦截）。
用法:
  python3 run_sql.py <数据集ID> '<SQL>'            # 表格输出（默认）
  python3 run_sql.py <数据集ID> '<SQL>' -f json    # 透传 guancli 输出格式
  python3 run_sql.py --check-scope <数据集ID>      # 只验白名单不执行 SQL（体检/冒烟用）：
                                                   # 在覆盖范围内 exit 0，越界 exit 3，scope 缺失降级 exit 0
校验规则（违反即 exit 3，不执行）:
  1. 去除注释与字符串字面量后，必须以 SELECT 或 WITH 开头
  2. 禁止多语句（; 后还有内容）
  3. 禁止写操作/管理操作关键字（INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/...）
  4. 范围守卫：数据集 ID 必须在 scope 白名单内（看板模式从 cards.json 的 dsUsage 派生，
     数据集直通模式从 datasets.json 已学条目派生；
     找不到 scope 文件时跳过本校验，不阻断脱离交付包的独立使用）
"""
import os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scope as scope_mod
except ImportError:
    scope_mod = None  # scope.py 未随包复制时降级跳过白名单校验，不阻断只读 SQL 主功能

BLOCKED = ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE',
           'GRANT', 'REVOKE', 'MERGE', 'REPLACE', 'CALL', 'EXEC', 'EXECUTE',
           'SET', 'USE', 'SHOW', 'DESCRIBE', 'EXPLAIN')


def strip_literals_and_comments(sql):
    """去掉字符串字面量与注释，避免误判（如 'a;drop' 字符串里的分号）"""
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    s = re.sub(r"'(?:[^'\\]|\\.|'')*'", "''", s)
    s = re.sub(r'"(?:[^"\\]|\\.|"")*"', '""', s)
    return s


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


def scope_check(ds_id):
    """白名单 dry 校验：在覆盖范围内返回 None；越界返回错误信息；scope 缺失返回 None（降级）"""
    scope = scope_mod.load_scope() if scope_mod is not None else None
    if scope is not None and ds_id not in scope["dsIds"]:
        # 越界文案按白名单来源区分：看板模式指向 cards.json 的 dsUsage，直通模式指向 datasets.json
        src = os.path.basename(scope.get("source") or "")
        hint = ("references/datasets.json 的已学数据集" if src == "datasets.json"
                else "references/cards.json 的 dsUsage")
        return (f"数据集 {ds_id} 不在本助手覆盖范围（脚本层白名单拦截）\n"
                f"覆盖范围见 {hint}；如需接入新数据，回到搭建向导说「增量学习」。")
    return None


def main():
    args = sys.argv[1:]
    # --check-scope <数据集ID>：只验白名单不调 guancli（check_package 功能冒烟用）
    if "--check-scope" in args:
        i = args.index("--check-scope")
        if i + 1 >= len(args):
            sys.exit("用法: python3 run_sql.py --check-scope <数据集ID>")
        err = scope_check(args[i + 1])
        if err:
            print(f"❌ {err}", file=sys.stderr)
            sys.exit(3)
        print(f"✅ 数据集 {args[i + 1]} 在覆盖范围内（或 scope 缺失降级放行）")
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
    err = scope_check(ds_id)
    if err:
        print(f"❌ {err}", file=sys.stderr)
        sys.exit(3)
    err = validate(sql)
    if err:
        print(f"❌ SQL 被只读校验拦截: {err}", file=sys.stderr)
        print("SQL 直查仅支持单条 SELECT 查询；如需写操作请改用 BI 平台。", file=sys.stderr)
        sys.exit(3)
    r = subprocess.run(["guancli", "ds", "execute-sql", "-inputs", ds_id,
                        "-sql", sql, "-f", fmt], timeout=180)
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()
