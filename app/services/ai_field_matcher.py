"""
AI 字段识别器：传用户 Excel 的表头 + 每列前 5 行样本，让 AI 判断每列对应哪个标准字段。
"""
import os
import json
from app.services.standard_fields import (
    STANDARD_FIELDS, FIELD_BY_KEY, REQUIRED_KEYS, summary_for_ai_prompt,
)


def suggest_field_mapping(columns: list, sample_rows: list) -> dict:
    """
    参数：
      columns: 用户 Excel 的表头列表 ["姓名", "base", "level", ...]
      sample_rows: 前 5 行数据（每行是一个 dict: {列名: 值}）
    返回：
      {
        'mappings': [{'user_column': '姓名', 'system_field': 'employee_id', 'confidence': 0.95}, ...],
        'unmapped': ['备注', '籍贯'],
        'missing_required': ['annual_fixed_bonus'],
        'missing_optional': ['direct_manager', 'is_key_position'],
      }
    AI 失败时 fallback 到关键词匹配（即原来的 _detect_fields）。
    """
    columns = [c for c in (columns or []) if c]  # 过滤空列名

    # 构建每列样本摘要：{列名: [前 5 个非空值]}
    col_samples = _collect_samples(columns, sample_rows)

    mappings = None
    if os.getenv('OPENROUTER_API_KEY', '').strip():
        try:
            mappings = _call_ai(columns, col_samples)
        except Exception as e:
            print(f'[AIFieldMatcher] AI failed, fallback to keyword match: {e}')

    if mappings is None:
        mappings = _keyword_fallback(columns, col_samples)

    return _finalize(mappings, columns)


def _collect_samples(columns: list, sample_rows: list) -> dict:
    """{col: [v1, v2, v3, v4, v5]}"""
    out: dict = {c: [] for c in columns}
    for row in (sample_rows or [])[:5]:
        data = row.get('data', row) if isinstance(row, dict) else {}
        for c in columns:
            v = data.get(c)
            if v is None or str(v).strip() == '':
                continue
            s = str(v).strip()
            if len(s) > 40:
                s = s[:40] + '…'
            if len(out[c]) < 5 and s not in out[c]:
                out[c].append(s)
    return out


def _call_ai(columns: list, col_samples: dict) -> list:
    """调 AI 返回 list[{'user_column', 'system_field', 'confidence'}]"""
    from app.agents.base_agent import BaseAgent
    agent = BaseAgent(temperature=0.1)

    sample_lines = []
    for c in columns:
        samples = col_samples.get(c, [])
        sample_lines.append(f'  - "{c}": {samples if samples else "(空)"}')
    columns_block = '\n'.join(sample_lines)

    system_prompt = (
        "你是铭曦薪酬诊断产品的数据解析器。用户上传了一份 Excel，"
        "你需要判断每一列对应哪个标准字段。"
    )
    user_prompt = f"""标准字段列表（key: 中文标签 + 提示）：
{summary_for_ai_prompt()}

用户 Excel 的列和前几行样本：
{columns_block}

判断规则：
- 列名和样本数据结合判断，**样本更重要**。例如列名是"level"但数据是"A, B+, B, C"，
  大概率是 performance_rating（绩效），不是 grade（职级）。
- 列名是"薪资"但数据是"15000, 20000, 35000"这种小数字，大概率是月度基本工资 base_salary。
- 一列只能映射到一个标准字段；一个标准字段只能被一列占用。
- 如果一列确实不能匹配任何标准字段，放到 unmapped 里。
- 如果某个标准字段没有任何列能匹配上，不要编造映射。

输出严格 JSON：
{{
  "mappings": [
    {{"user_column": "姓名", "system_field": "employee_id", "confidence": 0.95}},
    {{"user_column": "base", "system_field": "base_salary", "confidence": 0.90}}
  ],
  "unmapped": ["备注", "籍贯"]
}}

只输出 JSON，不要其他内容。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = agent.call_llm(messages).strip()

    if '```json' in response:
        response = response.split('```json', 1)[1].split('```', 1)[0]
    elif '```' in response:
        response = response.split('```', 1)[1].split('```', 1)[0]

    parsed = json.loads(response.strip())
    return parsed.get('mappings', [])


def _keyword_fallback(columns: list, col_samples: dict) -> list:
    """AI 不可用时用关键词模式做 best-effort 匹配"""
    # 关键词表：standard_key → 命中关键词
    patterns = {
        'employee_id': ['工号', '姓名', '员工', 'name', 'employee', 'emp_id'],
        'job_title': ['岗位', '职位', '头衔', 'title', 'position'],
        'grade': ['职级', '级别', '层级', 'level', 'grade', '等级'],
        'department_l1': ['一级部门', '部门（一级）', '一级'],
        'department_l2': ['二级部门', '部门（二级）', '二级'],
        'department_l3': ['三级部门', '部门（三级）', '三级'],
        'base_salary': ['月度基本工资', '月基本', '月薪', '基本工资', 'base salary', 'monthly base'],
        'annual_fixed_bonus': ['年固定奖金', '固定奖金', '13薪', '十三薪', '年节礼金'],
        'annual_variable_bonus': ['年浮动奖金', '浮动奖金', '绩效奖金', '年终奖', '奖金', '年终'],
        'annual_allowance': ['年度现金津贴', '现金津贴', '津贴', 'allowance'],
        'annual_reimbursement': ['年津贴报销', '津贴报销', '报销', 'reimbursement'],
        'performance_rating': ['绩效', '考核', '评级', 'performance', 'rating'],
        'hire_date': ['入职', '入司', 'hire', 'start date', '入职日期'],
        'direct_manager': ['上级', '直属', '汇报', 'manager', 'supervisor'],
        'management_or_professional': ['管理岗', '专业岗', '序列', '通道'],
        'is_key_position': ['关键岗位', '核心岗位', 'key position'],
        'management_complexity': ['管理复杂度', '复杂度'],
        'base_city': ['工作城市', '所在城市', '城市', 'city', 'location'],
        'age': ['年龄', 'age'],
        'education': ['学历', '教育', 'education'],
        'job_family': ['职位族', '岗位族', '职能族', 'family'],
        'job_class': ['职位类', '岗位类', '职能类', 'class'],
    }
    mappings: list = []
    used_fields: set = set()
    for col in columns:
        col_lower = col.lower()
        for key, kws in patterns.items():
            if key in used_fields:
                continue
            if any(kw.lower() in col_lower for kw in kws):
                mappings.append({'user_column': col, 'system_field': key, 'confidence': 0.6})
                used_fields.add(key)
                break
    return mappings


def _finalize(mappings: list, columns: list) -> dict:
    """去重、计算 unmapped / missing_required / missing_optional"""
    # 去重：同一 system_field 只留 confidence 最高那条
    by_field: dict = {}
    for m in mappings:
        fld = m.get('system_field')
        if not fld or fld not in FIELD_BY_KEY:
            continue
        conf = float(m.get('confidence', 0))
        if fld not in by_field or conf > by_field[fld]['confidence']:
            by_field[fld] = {
                'user_column': m['user_column'],
                'system_field': fld,
                'confidence': conf,
            }
    final_mappings = list(by_field.values())

    mapped_cols = {m['user_column'] for m in final_mappings}
    mapped_fields = {m['system_field'] for m in final_mappings}

    unmapped = [c for c in columns if c not in mapped_cols]
    missing_required = [k for k in REQUIRED_KEYS if k not in mapped_fields]
    missing_optional = [
        k for k in FIELD_BY_KEY
        if k not in mapped_fields and not FIELD_BY_KEY[k]['required']
    ]
    return {
        'mappings': final_mappings,
        'unmapped': unmapped,
        'missing_required': missing_required,
        'missing_optional': missing_optional,
    }
