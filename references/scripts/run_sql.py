#!/usr/bin/env python3
"""
只读 SQL 执行器：guancli ds execute-sql 的安全包装层
SQL 直查一律走本脚本，禁止直接调用 guancli ds execute-sql——
prompt 红线靠自觉，本脚本提供脚本层强制：只允许单条 SELECT/WITH 查询。
用法:
  python3 run_sql.py <数据集ID> '<SQL>'            # 表格输出（默认）
  python3 run_sql.py <数据集ID> '<SQL>' -f json    # 透传 guancli 输出格式
校验规则（违反即 exit 3，不执行）:
  1. 去除注释与字符串字面量后，必须以 SELECT 或 WITH 开头
  2. 禁止多语句（; 后还有内容）
  3. 禁止写操作/管理操作关键字（INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/...）
"""
import re, subprocess, sys

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


def main():
    args = sys.argv[1:]
    fmt = "table"
    if "-f" in args:
        i = args.index("-f")
        fmt = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) < 2:
        sys.exit("用法: python3 run_sql.py <数据集ID> '<SQL>' [-f table|json|csv]")
    ds_id, sql = args[0], args[1]
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
