#!/usr/bin/env python3
"""
归因计算引擎：所有归因算术脚本化，LLM 只负责解释计算结果
（LLM 口算贡献占比是"归因必须量化"方法论最大的可靠性漏洞）

两种拆解模式:

1) add 加法拆解 —— 总量变化 = 各维度成员变化之和
   场景: "集团收入下降 34 万"拆解到各渠道/各 BU 的贡献
   用法:
     python3 attribute.py add data.csv 渠道 上月收入 本月收入
     python3 attribute.py add data.csv --dim 渠道 --base 上月收入 --curr 本月收入
     python3 attribute.py add data.json --dim 渠道 --base-key 与 --curr-key 均可用 --base/--curr
   贡献率符号约定:
     贡献率 = 成员变化额 ÷ 总变化额。正贡献率 = 与总变化同向（拉动），
     负贡献率 = 与总变化反向（拖累）。总变化为负时该约定同样成立：
     例如总变化 -34 万，某成员变化 -20 万，贡献率 +58.8%（同为下降方向，是主要拖累源——
     此时"贡献率"衡量的是对总变化的解释份额，方向列另用 ↑/↓ 标注增减）。
   闭环校验: Σ成员变化额 恒等于 总变化额，输出中展示验证结果。

2) mul 乘法拆解 —— 指标 = 因子1 × 因子2 (× 因子3 × 因子4)
   场景: "业绩 = 店数 × 单店业绩"、"GMV = 客流 × 转化率 × 客单价"
   方法: Shapley 值（所有因子排序的连环替代边际贡献之平均）。
     相比固定顺序的连环替代法，Shapley 具备:
       - 完备性: Σ各因子贡献 精确等于 总变化
       - 对称性: 贡献与因子排列顺序无关
     支持 2~4 个因子（4! = 24 种排序，枚举成本可忽略）。
     因子从 0 起步（如新店从 0 到 N）属于合法输入，Shapley 天然处理。
   用法:
     python3 attribute.py mul --factors 店数,单店业绩 --base 100,0.71 --curr 100,0.37
     python3 attribute.py mul data.csv --factors 店数,单店业绩 --base-row 0 --curr-row 1

通用:
  - 输入文件支持 .csv 与 .json（数组对象），按扩展名自动判断
  - 数值容忍千分位逗号、百分号、中文单位"万/亿":
    "1,234.5" → 1234.5；"35%" → 0.35（百分数转为小数）；"71万" → 710000；"1.2亿" → 120000000
  - 默认输出对齐表格，--json 输出结构化结果（供 LLM 二次加工）
退出码: 0 正常；1 用法错误；2 输入/数据错误
"""
import csv, json, sys, os, unicodedata
from itertools import permutations

EPS = 1e-9  # 总变化额绝对值小于此值视为"接近 0"，贡献率无意义


def parse_num(v, ctx=''):
    """解析业务数值：容忍千分位逗号、百分号、中文单位万/亿。失败抛 ValueError"""
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        raise ValueError('空值')
    s = str(v).strip()
    if not s:
        raise ValueError('空值')
    mult = 1.0
    if s.endswith('万'):
        mult, s = 1e4, s[:-1]
    elif s.endswith('亿'):
        mult, s = 1e8, s[:-1]
    pct = s.endswith('%')
    if pct:
        s = s[:-1]
    s = s.replace(',', '').replace('，', '').strip()
    if s.startswith('(') and s.endswith(')'):  # 会计负数写法 (123)
        s = '-' + s[1:-1]
    try:
        x = float(s)
    except ValueError:
        raise ValueError(f"无法解析数值 {v!r}" + (f"（{ctx}）" if ctx else ''))
    x *= mult
    if pct:
        x /= 100.0
    return x


def fmt_num(v):
    """数值显示：整数带千分位，小数保留至多 4 位有效精度"""
    if v is None:
        return '—'
    if abs(v) >= 1e15:
        return f'{v:.4g}'
    if v == int(v) and abs(v) < 1e15:
        return f'{int(v):,}'
    s = f'{v:,.4f}'.rstrip('0').rstrip('.')
    return s


def fmt_pct(v):
    return '—' if v is None else f'{v * 100 + 0.0:.1f}%'


def dw(s):
    """显示宽度（中文按 2 列计），用于表格对齐"""
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in str(s))


def pad(s, width, align='<'):
    s = str(s)
    gap = max(0, width - dw(s))
    return (' ' * gap + s) if align == '>' else (s + ' ' * gap)


def print_table(headers, rows, aligns=None):
    aligns = aligns or ['<'] * len(headers)
    widths = [dw(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], dw(c))
    line = '  '.join(pad(h, widths[i]) for i, h in enumerate(headers))
    print(line)
    print('  '.join('─' * widths[i] for i in range(len(headers))))
    for r in rows:
        print('  '.join(pad(c, widths[i], aligns[i]) for i, c in enumerate(r)))


def load_rows(path):
    """按扩展名读取 CSV/JSON，返回 list[dict]。错误抛 ValueError"""
    if not os.path.isfile(path):
        raise ValueError(f'文件不存在: {path}')
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == '.csv':
            with open(path, encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
        elif ext == '.json':
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('rows'), list):
                data = data['rows']
            if not isinstance(data, list):
                raise ValueError('JSON 必须是对象数组（或含 rows 数组的对象）')
            rows = data
        else:
            raise ValueError(f'不支持的文件类型 {ext!r}，仅支持 .csv / .json')
    except json.JSONDecodeError as e:
        raise ValueError(f'JSON 解析失败: {e}')
    except UnicodeDecodeError:
        raise ValueError('文件编码不是 UTF-8，请先转换编码')
    if not rows:
        raise ValueError('文件中没有数据行')
    return rows


def pick_col(rows, name, role):
    """校验列存在，返回列名"""
    cols = list(rows[0].keys())
    if name in cols:
        return name
    for c in cols:  # 容忍前后空格
        if c.strip() == name.strip():
            return c
    raise ValueError(f'找不到{role}列 {name!r}，可用列: {", ".join(cols)}')


# ---------- add 模式 ----------

def cmd_add(args, as_json):
    path, dim, base, curr = None, None, None, None
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ('--dim', '--base', '--curr', '--base-key', '--curr-key'):
            if i + 1 >= len(args):
                sys.exit(f'用法错误: {a} 缺少数值')
            key = {'--dim': 'dim', '--base': 'base', '--curr': 'curr',
                   '--base-key': 'base', '--curr-key': 'curr'}[a]
            if key == 'dim':
                dim = args[i + 1]
            elif key == 'base':
                base = args[i + 1]
            else:
                curr = args[i + 1]
            i += 2
        elif a.startswith('-'):
            sys.exit(f'用法错误: 未知参数 {a}')
        else:
            pos.append(a)
            i += 1
    if pos:
        path = pos[0]
        if len(pos) >= 4:
            dim, base, curr = pos[1], pos[2], pos[3]
        elif len(pos) > 1:
            sys.exit('用法错误: 位置参数需为 <文件> <dim列> <base列> <curr列>，或只用 <文件> 配合 --dim/--base/--curr')
    if not all([path, dim, base, curr]):
        sys.exit('用法: python3 attribute.py add <文件.csv|json> <dim列> <base列> <curr列>\n'
                 '      python3 attribute.py add <文件> --dim 渠道 --base 上月收入 --curr 本月收入')
    try:
        rows = load_rows(path)
        dim, base, curr = pick_col(rows, dim, '维度'), pick_col(rows, base, '基期'), pick_col(rows, curr, '现期')
        members = []
        for idx, r in enumerate(rows):
            d = str(r.get(dim, '')).strip() or f'(第{idx}行)'
            b = parse_num(r.get(base), f'{dim}={d} 的 {base}')
            c = parse_num(r.get(curr), f'{dim}={d} 的 {curr}')
            members.append({'dim': d, 'base': b, 'curr': c, 'change': c - b})
    except ValueError as e:
        print(f'❌ 输入错误: {e}', file=sys.stderr)
        sys.exit(2)
    if len(members) < 2:
        print('❌ 至少需要 2 个维度成员才能做加法拆解', file=sys.stderr)
        sys.exit(2)

    total_change = sum(m['change'] for m in members)
    total_base = sum(m['base'] for m in members)
    total_curr = sum(m['curr'] for m in members)
    meaningful = abs(total_change) > EPS
    for m in members:
        m['rate'] = (m['change'] / total_change) if meaningful else None
        if not meaningful:
            m['direction'] = '·'
        elif m['change'] * total_change > 0:
            m['direction'] = '拉动↑' if total_change > 0 else '拖累↓'
        elif abs(m['change']) <= EPS:
            m['direction'] = '持平·'
        else:
            m['direction'] = '拖累↓' if total_change > 0 else '拉动↑'
    members.sort(key=lambda m: abs(m['rate']) if m['rate'] is not None else abs(m['change']),
                 reverse=True)
    top = members[0]['dim']
    # 闭环校验（浮点求和容差）
    closure = sum(m['change'] for m in members)
    closed = abs(closure - total_change) <= max(EPS, abs(total_change) * 1e-9)

    if as_json:
        print(json.dumps({
            'mode': 'add', 'dim_column': dim, 'base_column': base, 'curr_column': curr,
            'total_base': total_base, 'total_curr': total_curr, 'total_change': total_change,
            'contribution_rate_meaningful': meaningful,
            'members': [{'dim': m['dim'], 'base': m['base'], 'curr': m['curr'],
                         'change': m['change'],
                         'contribution_rate': m['rate'], 'direction': m['direction'],
                         'is_top': m['dim'] == top} for m in members],
            'closure_check': {'sum_member_change': closure, 'total_change': total_change,
                              'passed': closed},
        }, ensure_ascii=False, indent=2))
        return

    print(f'📊 加法拆解（{dim}）: {fmt_num(total_base)} → {fmt_num(total_curr)}，总变化 {fmt_num(total_change)}')
    if not meaningful:
        print('⚠️ 总变化额 ≈ 0：各成员变化相互抵消，贡献率无数学意义，请直接看变化额')
    print_table(
        ['排名', dim, '基期', '现期', '变化额', '贡献率', '方向', '备注'],
        [[str(i + 1), m['dim'], fmt_num(m['base']), fmt_num(m['curr']),
          ('+' if m['change'] > 0 else '') + fmt_num(m['change']),
          fmt_pct(m['rate']), m['direction'],
          '🏆 Top 贡献者' if m['dim'] == top else '']
         for i, m in enumerate(members)],
        aligns=['>', '<', '>', '>', '>', '>', '<', '<'])
    # 方向列注释
    if meaningful:
        note = ('正贡献率 = 与总变化同向' if total_change > 0
                else '总变化为负：正贡献率 = 该成员同向下降/增长（与总变化同号），负贡献率 = 反向对冲')
        print(f'注: 贡献率 = 成员变化额 ÷ 总变化额（{note}）')
    mark = '✅' if closed else '❌'
    print(f'{mark} 闭环验证: Σ成员变化额 {fmt_num(closure)} = 总变化额 {fmt_num(total_change)}')
    if not closed:
        sys.exit(2)


# ---------- mul 模式 ----------

def shapley_contributions(base, curr):
    """Shapley 值拆解 ∏curr - ∏base。返回每个因子的贡献额（与因子顺序无关，Σ贡献=总变化）"""
    n = len(base)
    contrib = [0.0] * n
    for perm in permutations(range(n)):
        state = list(base)

        def prod(s):
            p = 1.0
            for x in s:
                p *= x
            return p

        prev = prod(state)
        for i in perm:
            state[i] = curr[i]
            new = prod(state)
            contrib[i] += new - prev
            prev = new
    fact = 1
    for k in range(2, n + 1):
        fact *= k
    return [c / fact for c in contrib]


def cmd_mul(args, as_json):
    path, factors, base_s, curr_s = None, None, None, None
    base_row, curr_row = None, None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ('--factors', '--base', '--curr', '--base-row', '--curr-row'):
            if i + 1 >= len(args):
                sys.exit(f'用法错误: {a} 缺少数值')
            v = args[i + 1]
            if a == '--factors':
                factors = [x.strip() for x in v.split(',') if x.strip()]
            elif a == '--base':
                base_s = v
            elif a == '--curr':
                curr_s = v
            elif a == '--base-row':
                base_row = v
            else:
                curr_row = v
            i += 2
        elif a.startswith('-'):
            sys.exit(f'用法错误: 未知参数 {a}')
        else:
            if path is not None:
                sys.exit(f'用法错误: 多余的位置参数 {a!r}')
            path = a
            i += 1
    if not factors:
        sys.exit('用法: python3 attribute.py mul --factors 店数,单店业绩 --base 100,0.71 --curr 100,0.37\n'
                 '      python3 attribute.py mul data.csv --factors 店数,单店业绩 --base-row 0 --curr-row 1')
    if not (2 <= len(factors) <= 4):
        print(f'❌ 因子个数需为 2~4，当前 {len(factors)} 个', file=sys.stderr)
        sys.exit(2)

    try:
        if path:
            rows = load_rows(path)
            if base_row is None or curr_row is None:
                sys.exit('用法错误: 文件输入需同时指定 --base-row 与 --curr-row（行号从 0 开始）')
            try:
                br, cr = int(base_row), int(curr_row)
                rb, rc = rows[br], rows[cr]
            except (ValueError, IndexError):
                raise ValueError(f'行号无效（共 {len(rows)} 行，可用 0~{len(rows) - 1}）: base-row={base_row}, curr-row={curr_row}')
            for f_ in factors:
                pick_col(rows, f_, '因子')
            base = [parse_num(rb[f_], f'第{br}行 {f_}') for f_ in factors]
            curr = [parse_num(rc[f_], f'第{cr}行 {f_}') for f_ in factors]
        else:
            if base_s is None or curr_s is None:
                sys.exit('用法错误: 直接传值需同时指定 --base 与 --curr（逗号分隔，与 --factors 一一对应）')
            base = [parse_num(x, 'base') for x in base_s.split(',')]
            curr = [parse_num(x, 'curr') for x in curr_s.split(',')]
            if len(base) != len(factors) or len(curr) != len(factors):
                raise ValueError(f'--base/--curr 的数值个数须与因子数一致（{len(factors)}），'
                                 f'实际 base={len(base)}, curr={len(curr)}')
    except ValueError as e:
        print(f'❌ 输入错误: {e}', file=sys.stderr)
        sys.exit(2)

    def prod(xs):
        p = 1.0
        for x in xs:
            p *= x
        return p

    base_total, curr_total = prod(base), prod(curr)
    total_change = curr_total - base_total
    contrib = shapley_contributions(base, curr)
    closure = sum(contrib)
    closed = abs(closure - total_change) <= max(EPS, abs(total_change) * 1e-9)
    meaningful = abs(total_change) > EPS
    items = []
    for f_, b, c, ct in zip(factors, base, curr, contrib):
        items.append({
            'factor': f_, 'base': b, 'curr': c, 'contribution': ct,
            'share': (ct / total_change) if meaningful else None,
            'direction': ('拉动↑' if ct > EPS else ('拖累↓' if ct < -EPS else '持平·')),
        })
    items.sort(key=lambda x: abs(x['contribution']), reverse=True)
    top = items[0]['factor'] if items else None

    if as_json:
        print(json.dumps({
            'mode': 'mul', 'method': 'shapley（所有因子排序的连环替代边际贡献平均；完备且与顺序无关）',
            'factors': factors, 'base': base, 'curr': curr,
            'base_total': base_total, 'curr_total': curr_total, 'total_change': total_change,
            'contribution_share_meaningful': meaningful,
            'contributions': [{**it, 'is_top': it['factor'] == top} for it in items],
            'closure_check': {'sum_contributions': closure, 'total_change': total_change,
                              'passed': closed},
        }, ensure_ascii=False, indent=2))
        return

    print(f'📊 乘法拆解（{" × ".join(factors)}）: {fmt_num(base_total)} → {fmt_num(curr_total)}，总变化 {fmt_num(total_change)}')
    print('方法: Shapley 值（所有排序的连环替代平均），Σ贡献 精确等于总变化、与因子顺序无关')
    if not meaningful:
        print('⚠️ 总变化额 ≈ 0：各因子贡献相互抵消，贡献占比无数学意义，请直接看贡献额')
    if any(b == 0 for b in base) or any(c == 0 for c in curr):
        print('ℹ️ 检测到因子为 0（如新店从 0 起步），Shapley 已按边际贡献正常分摊')
    print_table(
        ['排名', '因子', '基期', '现期', '贡献额', '贡献占比', '方向', '备注'],
        [[str(i + 1), it['factor'], fmt_num(it['base']), fmt_num(it['curr']),
          ('+' if it['contribution'] > 0 else '') + fmt_num(it['contribution']),
          fmt_pct(it['share']), it['direction'],
          '🏆 Top 贡献者' if it['factor'] == top else '']
         for i, it in enumerate(items)],
        aligns=['>', '<', '>', '>', '>', '>', '<', '<'])
    mark = '✅' if closed else '❌'
    print(f'{mark} 闭环验证: Σ因子贡献 {fmt_num(closure)} = 总变化额 {fmt_num(total_change)}')
    if not closed:
        sys.exit(2)


def main():
    args = sys.argv[1:]
    as_json = '--json' in args
    if as_json:
        args.remove('--json')
    if not args or args[0] not in ('add', 'mul'):
        sys.exit('用法: python3 attribute.py <add|mul> ... [--json]\n'
                 '  add 加法拆解: add <文件> <dim列> <base列> <curr列>\n'
                 '  mul 乘法拆解: mul --factors 店数,单店业绩 --base 100,0.71 --curr 100,0.37\n'
                 '详见脚本头部 docstring')
    if args[0] == 'add':
        cmd_add(args[1:], as_json)
    else:
        cmd_mul(args[1:], as_json)


if __name__ == '__main__':
    main()
