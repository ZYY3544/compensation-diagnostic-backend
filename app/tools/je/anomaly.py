"""
JE 职级图谱异常检测。

输入：当前 workspace 的所有 Job 列表
输出：告警列表（按严重程度排序）

三类规则：
1. inversion  —— 职级倒挂：同部门内，按头衔关键词排序，下级岗位职级 ≥ 上级岗位
                 例："PM 经理 G13 < PM 高级 G14" 是常见症状
2. inflation  —— 跨部门膨胀：某部门的职级中位数比公司中位高 ≥ 3 级
                 隐含信号是该部门"职级注水"
3. missing_tier —— 部门内职级断层：部门覆盖的职级范围里出现 ≥ 2 级的连续空洞

每条告警包含：
- severity: 'high' | 'medium' | 'low'
- type: 'inversion' | 'inflation' | 'missing_tier'
- title / message: 给前端直接展示的中文文案
- evidence: 涉及的岗位 id 列表，便于前端高亮

设计取舍：
- 不依赖"上下级关系"显式数据（Job 没有 reports_to 字段），用头衔关键词做近似
- 阈值用常见经验值（中位差 3、连续空洞 2），后续可以改成 workspace 级配置
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Iterable


# 头衔级别关键词从低到高。同部门内出现这些词的岗位之间应该满足
# rank_index 越大 → 职级越高。出现违反就是 inversion。
# 注意顺序：检索时用第一个命中的关键词作为 rank，所以"高级总监"要排在"总监"前。
_TITLE_RANK_KEYWORDS: list[tuple[str, int]] = [
    ('实习', 0),
    ('助理', 1), ('助手', 1),
    ('初级', 2), ('junior', 2),
    ('专员', 3),
    ('中级', 4),
    ('工程师', 5),  # 兜底名词，没有前缀的"工程师"算中段
    ('高级', 6), ('senior', 6),
    ('资深', 7),
    ('主管', 8),
    ('经理', 9), ('manager', 9),
    ('高级经理', 10),
    ('总监', 11), ('director', 11),
    ('高级总监', 12),
    ('vp', 13), ('副总裁', 13), ('副总', 13),
    ('总裁', 14), ('president', 14),
    ('cto', 15), ('cfo', 15), ('coo', 15), ('cmo', 15), ('chro', 15),
]


def _title_rank(title: str) -> int | None:
    """返回头衔的级别索引（越大越高），找不到关键词则返回 None。"""
    if not title:
        return None
    t = title.lower()
    # 优先匹配多字关键词（"高级总监" 比 "总监" 优先）→ 按关键词长度倒序
    for keyword, rank in sorted(_TITLE_RANK_KEYWORDS, key=lambda x: -len(x[0])):
        if keyword in t:
            return rank
    return None


def detect_anomalies(jobs: Iterable[dict]) -> list[dict]:
    """
    输入 jobs：每个元素需要至少有 {id, title, department, result.job_grade} 这几个字段
    （由 _serialize_job 序列化后的形态即可直接传入）

    返回 list[dict]，按 severity 降序。
    """
    rows = []
    for j in jobs:
        grade = (j.get('result') or {}).get('job_grade')
        if grade is None:
            continue
        rows.append({
            'id': j['id'],
            'title': j.get('title') or '',
            'department': j.get('department') or '未分组',
            'grade': int(grade),
        })

    if not rows:
        return []

    anomalies: list[dict] = []
    anomalies.extend(_detect_inversions(rows))
    anomalies.extend(_detect_inflation(rows))
    anomalies.extend(_detect_missing_tiers(rows))

    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    anomalies.sort(key=lambda a: severity_order.get(a['severity'], 99))
    return anomalies


# ---------- 1. 职级倒挂 ----------

def _detect_inversions(rows: list[dict]) -> list[dict]:
    """同部门内按头衔关键词排序，相邻头衔的职级应该单调不降；违反就是 inversion。"""
    by_dept: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        rank = _title_rank(r['title'])
        if rank is None:
            continue
        by_dept[r['department']].append({**r, 'rank': rank})

    out = []
    for dept, items in by_dept.items():
        # 同一 rank 可能多个岗位（部门里好几个"经理"），按 rank 分组取最高 grade 做比较
        # 这样"经理岗里有 G14 也有 G13"不会自我倒挂误报
        rank_to_max_grade: dict[int, dict] = {}
        for it in items:
            cur = rank_to_max_grade.get(it['rank'])
            if cur is None or it['grade'] > cur['grade']:
                rank_to_max_grade[it['rank']] = it

        ordered = sorted(rank_to_max_grade.values(), key=lambda x: x['rank'])
        for i in range(len(ordered) - 1):
            lower = ordered[i]
            upper = ordered[i + 1]
            if lower['grade'] >= upper['grade']:
                out.append({
                    'severity': 'high',
                    'type': 'inversion',
                    'title': f'{dept}：职级倒挂',
                    'message': (
                        f'{lower["title"]}（G{lower["grade"]}）'
                        f' ≥ {upper["title"]}（G{upper["grade"]}），'
                        f'下级岗位职级不低于上级岗位'
                    ),
                    'evidence': [lower['id'], upper['id']],
                    'department': dept,
                })
    return out


# ---------- 2. 跨部门膨胀 ----------

def _detect_inflation(rows: list[dict]) -> list[dict]:
    """部门职级中位高于公司中位 ≥ 3 级，标 medium。"""
    if len(rows) < 5:
        return []  # 数据太少，比较没有意义

    company_median = median(r['grade'] for r in rows)
    by_dept: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        by_dept[r['department']].append(r['grade'])

    out = []
    for dept, grades in by_dept.items():
        if len(grades) < 3:
            continue  # 部门里岗位太少，单点抬高中位很正常
        dept_median = median(grades)
        gap = dept_median - company_median
        if gap >= 3:
            evidence_ids = [r['id'] for r in rows if r['department'] == dept]
            out.append({
                'severity': 'medium',
                'type': 'inflation',
                'title': f'{dept}：职级偏高',
                'message': (
                    f'{dept} 职级中位 G{int(dept_median)}，'
                    f'公司中位 G{int(company_median)}，'
                    f'高出 {int(gap)} 级，疑似职级膨胀'
                ),
                'evidence': evidence_ids,
                'department': dept,
            })
    return out


# ---------- 3. 部门内职级断层 ----------

def _detect_missing_tiers(rows: list[dict]) -> list[dict]:
    """部门覆盖的职级 [min, max] 区间里，连续 ≥ 2 级没岗位的视为断层。"""
    by_dept: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        by_dept[r['department']].add(r['grade'])

    out = []
    for dept, grade_set in by_dept.items():
        if len(grade_set) < 3:
            continue
        gmin, gmax = min(grade_set), max(grade_set)
        if gmax - gmin < 3:
            continue  # 区间本身就窄，无法判断断层

        gaps: list[tuple[int, int]] = []
        cur_gap_start = None
        for g in range(gmin, gmax + 1):
            if g not in grade_set:
                if cur_gap_start is None:
                    cur_gap_start = g
            else:
                if cur_gap_start is not None:
                    gaps.append((cur_gap_start, g - 1))
                    cur_gap_start = None
        # 区间内不会出现尾部 gap（因为 gmax 必在集合里）

        for start, end in gaps:
            if end - start + 1 >= 2:
                out.append({
                    'severity': 'low',
                    'type': 'missing_tier',
                    'title': f'{dept}：职级断层',
                    'message': f'{dept} 在 G{start}-G{end} 区间没有岗位，可能存在中层断层',
                    'evidence': [],
                    'department': dept,
                })
    return out
