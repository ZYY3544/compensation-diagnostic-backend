"""
职级体系对照服务：把用户上传的"现行体系"跟 AI 评估出的岗位职级做对比。

输入：用户的 Excel（岗位名 + 现职级 + 可选部门）
处理：
  1. 解析 Excel → [(title, current_grade, department?)]
  2. 跟当前 workspace 的 jobs 用 fuzzy match 配对
     · 岗位名规范化后精确匹配 → title 同名 → 双向 substring
  3. 解析"现职级"为数字（支持 'G12' / '12' / 12 三种写法；非数字格式标记需用户改）
  4. 算差距：gap = ai_grade - current_grade
  5. 按差距分类输出

输出：
  {
    matched: [{ title, current_grade, ai_grade, gap, status, job_id, ... }],
    unmatched_legacy: 用户体系里有但 AI 没评估的岗位（建议补评）
    unmatched_ai:     AI 评了但现体系没列的岗位（信息差异）
    summary: 各分类计数
  }

简化设计：
- 不做体系映射（P 序列 ↔ G 数字这种），要求用户 Excel 里直接给数字
- 大版本 v2 可以加体系字典（"P5"="G14"）让用户配置映射
"""
from __future__ import annotations

import re
from typing import Optional

import openpyxl

from app.services.je_match import _normalize, _substring_match


# Excel 列别名
_COLUMN_ALIASES = {
    'title':    ('岗位', '职位', 'title', 'job_title', 'position'),
    'grade':    ('职级', 'grade', '级别', 'level', '等级'),
    'department': ('部门', 'dept', 'department'),
}

# gap 分类阈值
GAP_ALIGN = 1     # |gap| ≤ 1 视为对齐


def parse_legacy_excel(file_path: str) -> tuple[list[dict], list[str]]:
    """
    解析现行体系 Excel。

    Returns:
        (rows, errors)
        rows: [{title, current_grade, department?, raw_grade}]
              current_grade 是数字（解析失败为 None，raw_grade 保留原始字符串）
        errors: 字符串列表
    """
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    if len(all_rows) < 2:
        return [], ['Excel 至少需要表头 + 1 行数据']

    header = list(all_rows[0])
    mapping = _detect_columns(header)

    if 'title' not in mapping:
        return [], ['必填列未识别到：岗位名（表头需要包含"岗位"、"职位"等关键词）']
    if 'grade' not in mapping:
        return [], ['必填列未识别到：现行职级（表头需要包含"职级"、"级别"等关键词）']

    rows: list[dict] = []
    errors: list[str] = []
    for line_no, raw in enumerate(all_rows[1:], start=2):
        title = _cell(raw, mapping.get('title'))
        grade_raw = _cell(raw, mapping.get('grade'))
        department = _cell(raw, mapping.get('department'))

        if not title:
            if any([grade_raw, department]):
                errors.append(f'第 {line_no} 行：缺少岗位名')
            continue

        parsed_grade = _parse_grade_to_number(grade_raw)
        if parsed_grade is None and grade_raw:
            errors.append(f'第 {line_no} 行（{title}）：职级 "{grade_raw}" 无法解析成数字（建议改成 G12 / 12 / Hay 12 这类格式）')

        rows.append({
            'title': title.strip(),
            'current_grade': parsed_grade,
            'raw_grade': grade_raw or None,
            'department': (department or '').strip() or None,
        })
    return rows, errors


def _detect_columns(header: list) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalized = [(i, str(h or '').strip().lower()) for i, h in enumerate(header)]
    for field, aliases in _COLUMN_ALIASES.items():
        for idx, name in normalized:
            if not name:
                continue
            if any(alias.lower() in name for alias in aliases):
                mapping[field] = idx
                break
    return mapping


def _cell(row: tuple, idx: Optional[int]) -> str:
    if idx is None or idx >= len(row):
        return ''
    v = row[idx]
    return str(v).strip() if v is not None else ''


def _parse_grade_to_number(raw: str) -> Optional[int]:
    """
    解析职级字符串成 Hay grade 数字。
    支持: 'G12', 'g12', '12', 'Hay 12', 'L12'。
    P 序列 / M 序列没法直接转 — 建议用户先在 Excel 里换算。
    """
    if not raw:
        return None
    m = re.search(r'(\d+)', raw)
    if not m:
        return None
    n = int(m.group(1))
    # Hay grade 范围检验（防止用户填了完全不相关的数字）
    if n < 1 or n > 30:
        return None
    return n


# ---------------------------------------------------------------------------
# 跟当前 workspace 的 jobs 对比
# ---------------------------------------------------------------------------

def compare_to_jobs(legacy_rows: list[dict], jobs: list[dict]) -> dict:
    """
    把用户上传的现行体系跟 AI 评估的岗位列表对比。

    Returns:
        {
            matched: [...],           # 双方都有的岗位（核心对比）
            unmatched_legacy: [...],  # 用户给了但 AI 没评估
            unmatched_ai: [...],      # AI 评了但用户没给
            summary: {aligned, ai_higher, ai_lower, parse_failed, ...}
        }
    """
    # 索引 AI jobs：dept + 规范化 title → job dict；title → list[job]
    by_dept_title: dict[tuple, dict] = {}
    by_title: dict[str, list[dict]] = {}
    for j in jobs:
        title_n = _normalize(j.get('title') or '')
        dept = (j.get('department') or '').strip()
        if not title_n:
            continue
        if dept:
            by_dept_title[(dept, title_n)] = j
        by_title.setdefault(title_n, []).append(j)

    matched: list[dict] = []
    matched_job_ids: set[str] = set()
    unmatched_legacy: list[dict] = []

    aligned = ai_higher = ai_lower = parse_failed = 0

    for row in legacy_rows:
        title = row['title']
        title_n = _normalize(title)
        dept = (row.get('department') or '').strip()

        match: Optional[dict] = None
        match_strategy = ''

        if dept and (dept, title_n) in by_dept_title:
            match = by_dept_title[(dept, title_n)]
            match_strategy = 'dept+title'
        elif title_n in by_title:
            match = by_title[title_n][0]
            match_strategy = 'title'
        else:
            for j in jobs:
                if _substring_match(title_n, _normalize(j.get('title') or '')):
                    match = j
                    match_strategy = 'fuzzy'
                    break

        if not match:
            unmatched_legacy.append(row)
            continue

        matched_job_ids.add(match['id'])
        ai_grade = (match.get('result') or {}).get('job_grade')
        current_grade = row['current_grade']
        gap = (ai_grade - current_grade) if (ai_grade is not None and current_grade is not None) else None

        if gap is None:
            status = 'parse_failed'
            parse_failed += 1
        elif abs(gap) <= GAP_ALIGN:
            status = 'aligned'
            aligned += 1
        elif gap > 0:
            status = 'ai_higher'
            ai_higher += 1
        else:
            status = 'ai_lower'
            ai_lower += 1

        matched.append({
            'title': title,
            'current_grade': current_grade,
            'raw_grade': row.get('raw_grade'),
            'ai_grade': ai_grade,
            'gap': gap,
            'status': status,
            'match_strategy': match_strategy,
            'job_id': match['id'],
            'job_title': match['title'],
            'department': match.get('department'),
            'function': match.get('function'),
        })

    unmatched_ai = [
        {'job_id': j['id'], 'title': j['title'], 'department': j.get('department'),
         'ai_grade': (j.get('result') or {}).get('job_grade')}
        for j in jobs if j['id'] not in matched_job_ids
    ]

    return {
        'matched': matched,
        'unmatched_legacy': unmatched_legacy,
        'unmatched_ai': unmatched_ai,
        'summary': {
            'total_legacy': len(legacy_rows),
            'total_ai': len(jobs),
            'matched_count': len(matched),
            'unmatched_legacy_count': len(unmatched_legacy),
            'unmatched_ai_count': len(unmatched_ai),
            'aligned': aligned,
            'ai_higher': ai_higher,
            'ai_lower': ai_lower,
            'parse_failed': parse_failed,
        },
    }
