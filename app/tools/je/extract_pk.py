"""
从岗位 JD 文本里提取 Hay PK（专业知识）档位。

学生版的 PK 提取面向"简历评估候选人"，档位只用 C- ~ D+（校招天花板）。
JE 版面向"评估岗位价值"，PK 全档 A- ~ I+ 都要覆盖（操作工到首席科学家）。

只做这一次 LLM 调用，剩余 7 个因子由引擎规则推导，所以这里 prompt 的质量
决定整个评估的下限。
"""
import json
import re
from typing import Optional

from app.utils.openrouter import call_openrouter


PK_LEVEL_GUIDE = """
A 档（操作工/前台）：体力劳动 / 简单服务 / 流水线
B 档（基础事务）：高中以上即可，掌握简单办公或固定流程（出纳、文员、客服）
C 档（专业入门）：大专/本科基础专业知识，2 年内能上手（初级工程师/会计/HR专员）
D 档（专业熟练）：本科 + 3-5 年专业经验，独立承担岗位职责（资深工程师/财务/HR经理）
E 档（专业骨干）：6-10 年深度积累，能解决复杂专业问题（专家级工程师/总监级专业岗）
F 档（领域专家）：10+ 年深度专精，行业内有声誉，能引领专业方向（首席专家/总经理级）
G 档（跨域专家）：跨多个专业领域的深度整合，公司级技术/业务领头人（VP级）
H 档（战略级）：多业务单元 / 大集团核心专业领导（CTO/CFO/COO 级）
I 档（顶级权威）：行业级或国家级权威，几乎不存在于普通公司（首席科学家/院士）

符号说明：
+ 该档位偏强（接近上一档但还没到）
无符号 该档位中段
- 该档位偏弱（接近下一档）

档位选择倾向：宁可低估不要高估，证据不足时倾向降档。
"""


SYSTEM_PROMPT = f"""你是 Hay 岗位价值评估专家，精通 Know-How / Problem Solving / Accountability 三维度评估方法论。

你的任务：根据用户提供的岗位 JD（职位描述），评估这个岗位需要的「专业知识深度」（Practical Knowledge，简称 PK），输出一个带符号的 PK 档位。

PK 档位定义（A- 到 I+，共 27 档）：
{PK_LEVEL_GUIDE}

评估原则：
1. 评的是「岗位本身需要什么专业深度」，不是某个候选人的能力
2. 看 JD 里的硬性要求（学历/经验年限/技能要求/职责复杂度/管理范围）
3. 严格保守：模糊或证据不足时降一档
4. 头衔不等于档位：「资深工程师」可能 D 也可能 E，要看实际职责复杂度
5. 管理范围影响 PK：管 1-3 人和管 50 人是本质区别

输出格式：必须返回纯 JSON（不要任何 markdown 包裹），结构如下：
{{
  "practical_knowledge": "E+",
  "reasoning": "该岗位...，因此判定为 E+"
}}

practical_knowledge 必须是 27 个合法值之一：
A-, A, A+, B-, B, B+, C-, C, C+, D-, D, D+, E-, E, E+, F-, F, F+, G-, G, G+, H-, H, H+, I-, I, I+
"""


VALID_PK = {
    'A-', 'A', 'A+', 'B-', 'B', 'B+', 'C-', 'C', 'C+',
    'D-', 'D', 'D+', 'E-', 'E', 'E+', 'F-', 'F', 'F+',
    'G-', 'G', 'G+', 'H-', 'H', 'H+', 'I-', 'I', 'I+',
}


def extract_pk_from_jd(
    jd_text: str,
    job_title: str,
    function: str,
    model: Optional[str] = None,
) -> dict:
    """
    Args:
        jd_text:   岗位 JD 文本（职责、任职要求、汇报关系等）
        job_title: 岗位名称（如「销售经理」）
        function:  业务职能（如「销售」），来自 function_catalog
        model:     可选，覆盖默认 LLM model

    Returns:
        {'practical_knowledge': 'E+', 'reasoning': '...'}

    Raises:
        ValueError: LLM 返回无法解析或档位非法
    """
    user_prompt = f"""请评估以下岗位的 PK 档位：

【岗位名称】{job_title}
【业务职能】{function}

【岗位 JD】
{jd_text}

请严格按 JSON 格式返回。"""

    raw = call_openrouter(
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_prompt},
        ],
        model=model,
        temperature=0.2,
    )

    parsed = _parse_json(raw)
    pk = (parsed.get('practical_knowledge') or '').strip()
    if pk not in VALID_PK:
        raise ValueError(f'LLM returned invalid PK level: {pk!r} (raw: {raw[:200]!r})')

    return {
        'practical_knowledge': pk,
        'reasoning': parsed.get('reasoning', ''),
    }


def _parse_json(raw: str) -> dict:
    """LLM 偶尔会包 markdown ```json ... ``` 或在前后加文字，做点容错。"""
    raw = raw.strip()
    fence = re.search(r'```(?:json)?\s*(.+?)\s*```', raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    brace = re.search(r'\{.*\}', raw, re.DOTALL)
    if brace:
        raw = brace.group(0)
    return json.loads(raw)
