#!/usr/bin/env python3
"""
卡片数据质量校验器：把已踩过的坑变成自动检查
用法: python3 validate_cards.py <card-data目录>
校验项:
  1. 单位探测: 数值量级 >1e6 的字段标记"疑似元，引用需 /10000"
  2. 合计闭环: 含"总计"行的卡片，校验各维度值合计 ≈ 总计（判断全景 vs 下钻局部）
  3. 0 行卡片: 标记"依赖筛选器上下文，需在同看板找替代卡片"
  4. 空值率: 关键列空值率 >50% 提示数据稀疏
输出: 控制台报告 + <目录>/_validation.json
"""
import json, sys, os, glob, re

def to_num(v):
    if v is None or v == '':
        return None
    s = str(v).replace(',', '').replace('%', '')
    try:
        return float(s)
    except ValueError:
        return None

def main():
    data_dir = sys.argv[1]
    report = {}
    for fp in sorted(glob.glob(os.path.join(data_dir, '*.json'))):
        name = os.path.basename(fp)[:-5]
        if name.startswith('_'):
            continue
        with open(fp, encoding='utf-8') as f:
            payload = json.load(f)
        truncated_note = None
        if isinstance(payload, dict) and 'rows' in payload:
            truncated_note = payload.get('_totalRows')
            rows = payload['rows']
        else:
            rows = payload
        issues = []
        if truncated_note:
            issues.append({"level": "INFO", "type": "truncated",
                           "msg": f"采样已截断（共 {truncated_note} 行，仅落盘前 {len(rows)} 行），合计类校验基于截断样本"})
        if not isinstance(rows, list) or not rows:
            issues.append({"level": "WARN", "type": "empty",
                           "msg": "0 行数据：依赖筛选器上下文或数据为空，需确认或找替代卡片"})
            report[name] = {"issues": issues}
            continue
        # 1. 单位探测
        big = []
        for r in rows[:50]:
            for k, v in r.items():
                n = to_num(v)
                if n is not None and abs(n) > 1e6 and '%' not in str(v):
                    big.append(k)
        if big:
            issues.append({"level": "WARN", "type": "unit",
                           "msg": f"疑似元单位（引用需 /10000 转万）: {sorted(set(big))[:5]}"})
        # 2. 合计闭环：找"总计"行，校验维度列合计（仅对绝对值列；比率/占比/达成率列不可加总）
        #    截断样本上行数不全，合计必然不闭环，跳过该校验
        RATIO_HINT = ('率', '占比', '同比', '达成', '差额', '缺口', '费比')
        total_rows = [r for r in rows if any(str(v) in ('总计', '合计', 'Total') for v in r.values())]
        if total_rows and len(rows) > 2 and not truncated_note:
            t = total_rows[0]
            others = [r for r in rows if r not in total_rows]
            closed, not_closed = [], []
            for k, v in t.items():
                if any(h in str(k) for h in RATIO_HINT) or '%' in str(v):
                    continue  # 比率类列跳过加总校验
                tn = to_num(v)
                if tn is None or tn == 0:
                    continue
                s = sum(x for x in (to_num(r.get(k)) for r in others) if x is not None)
                if s == 0:
                    continue
                ratio = s / tn
                (closed if 0.98 <= ratio <= 1.02 else not_closed).append((k, s, tn, ratio))
            if not_closed:
                detail = "; ".join(f"{k}: 合计{s:,.0f} vs 总计{t2:,.0f} ({r0:.0%})" for k, s, t2, r0 in not_closed[:3])
                issues.append({"level": "ERROR", "type": "closure",
                               "msg": f"合计不闭环（疑似下钻/局部数据，禁止当全景）: {detail}"})
            elif closed:
                issues.append({"level": "OK", "type": "closure",
                               "msg": f"合计闭环 ✓（{len(closed)} 个绝对值列验证通过，可作全景使用）"})
        # 3. 空值率
        cols = list(rows[0].keys())
        for c in cols[:15]:
            empty = sum(1 for r in rows if r.get(c) in (None, ''))
            if len(rows) >= 5 and empty / len(rows) > 0.5:
                issues.append({"level": "INFO", "type": "sparse",
                               "msg": f"列「{c}」空值率 {empty/len(rows):.0%}，数据稀疏"})
        report[name] = {"rows": len(rows), "issues": issues}
    # 输出
    n_err = sum(1 for v in report.values() for i in v['issues'] if i['level'] == 'ERROR')
    n_warn = sum(1 for v in report.values() for i in v['issues'] if i['level'] == 'WARN')
    for name, v in report.items():
        for i in v['issues']:
            if i['level'] == 'OK':
                print(f"  ✅ {name}: {i['msg']}")
        for i in v['issues']:
            if i['level'] != 'OK':
                icon = '❌' if i['level'] == 'ERROR' else ('⚠️' if i['level'] == 'WARN' else 'ℹ️')
                print(f"  {icon} {name}: {i['msg']}")
    with open(os.path.join(data_dir, '_validation.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n校验完成: {len(report)} 张卡片, {n_err} 个错误, {n_warn} 个警告")
    if n_err:
        print("存在合计不闭环的卡片，必须在资产目录中标记为「下钻/局部数据」后才能继续")
        sys.exit(2)

if __name__ == '__main__':
    main()
