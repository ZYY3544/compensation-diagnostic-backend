"""
职能匹配服务：
1. 代码判断数据源优先级（职位族/类 > 部门 > 岗位名称）
2. AI #1：来源分类 → 标准职位族映射
3. AI #2：来源职位类 → 标准职位类映射 + 岗位异常标记
"""
import json

# ======================================================================
# 铭曦标准职位族/职位类体系
# ======================================================================
STANDARD_FAMILIES = {
    '技术研发': ['软件开发', '算法与AI', '测试', '运维与基础架构', '技术管理'],
    '产品': ['产品管理', '产品运营'],
    '设计': ['UI与UX设计', '视觉设计', '工业设计'],
    '销售': ['直销', '渠道销售', '大客户销售', '销售管理'],
    '市场': ['品牌', '数字营销', '市场研究', '公关'],
    '运营': ['用户运营', '内容运营', '商务运营', '数据运营'],
    '供应链': ['采购', '物流', '仓储', '质量管理'],
    '客户服务': ['客服', '技术支持'],
    '人力资源': ['招聘', 'HRBP', '薪酬绩效', '培训发展', '组织发展'],
    '财务': ['会计', '财务分析', '税务', '审计'],
    '法务': ['合规', '知识产权', '商务法务'],
    '行政': ['行政管理', '采购管理', '企业文化'],
    '高管': ['高管管理'],
    '其他': ['未分类'],
}

FAMILY_LIST = list(STANDARD_FAMILIES.keys())

# 全部标准职位类（扁平列表）
ALL_SUBFUNCTIONS = []
for fam, subs in STANDARD_FAMILIES.items():
    for s in subs:
        ALL_SUBFUNCTIONS.append(s)

FAMILY_DEFINITIONS = {
    '技术研发': '负责产品技术实现、架构设计、代码开发、测试和运维',
    '产品': '负责产品规划、需求定义、用户体验和产品生命周期管理',
    '设计': '负责视觉、交互、工业设计等创意工作',
    '销售': '负责客户开拓、商务谈判、销售目标达成',
    '市场': '负责品牌建设、市场推广、用户获取和公关传播',
    '运营': '负责用户运营、内容运营、数据分析和业务流程优化',
    '供应链': '负责采购、物流、仓储和质量管理',
    '客户服务': '负责客户问题解决、技术支持和服务质量',
    '人力资源': '负责招聘、薪酬、绩效、培训和组织发展',
    '财务': '负责财务核算、分析、税务和审计',
    '法务': '负责法律合规、知识产权和商务合同',
    '行政': '负责办公行政、后勤保障和企业文化',
    '高管': '公司级管理决策层',
    '其他': '暂未归入标准分类的岗位',
}

SUBFUNCTION_DEFINITIONS = {
    '软件开发': '前端、后端、移动端、全栈等软件工程',
    '算法与AI': '机器学习、深度学习、数据科学、NLP等',
    '测试': '功能测试、自动化测试、性能测试',
    '运维与基础架构': 'DevOps、SRE、云平台、网络与安全',
    '技术管理': '技术团队管理、架构决策',
    '产品管理': '产品规划、需求分析、产品路线图',
    '产品运营': '产品上线后的运营、数据分析、迭代',
    'UI与UX设计': '用户界面和用户体验设计',
    '视觉设计': '平面设计、品牌视觉',
    '工业设计': '实体产品外观和结构设计',
    '直销': '面向终端客户的直接销售',
    '渠道销售': '通过代理商、经销商等渠道销售',
    '大客户销售': '面向大型企业客户的销售',
    '销售管理': '销售团队管理、销售策略制定',
    '品牌': '品牌策略、品牌传播',
    '数字营销': 'SEO/SEM、社交媒体、效果广告',
    '市场研究': '市场调研、竞品分析、用户洞察',
    '公关': '媒体关系、危机公关、企业传播',
    '用户运营': '用户增长、留存、活跃度管理',
    '内容运营': '内容策划、编辑、发布',
    '商务运营': '商务合作、BD、战略合作',
    '数据运营': '数据分析、BI、运营策略',
    '采购': '供应商管理、采购执行',
    '物流': '物流规划、配送管理',
    '仓储': '库存管理、仓库运营',
    '质量管理': '品控、质量体系',
    '客服': '客户咨询、投诉处理',
    '技术支持': '技术问题诊断和解决',
    '招聘': '人才获取、招聘流程管理',
    'HRBP': '业务伙伴、组织诊断、人才管理',
    '薪酬绩效': '薪酬体系、绩效考核',
    '培训发展': '培训体系、人才发展',
    '组织发展': 'OD、组织设计、变革管理',
    '会计': '账务处理、报表编制',
    '财务分析': '财务分析、预算管理',
    '税务': '税务筹划、纳税申报',
    '审计': '内审、外审、风控',
    '合规': '法律合规、监管应对',
    '知识产权': '专利、商标、版权',
    '商务法务': '合同审查、商务纠纷',
    '行政管理': '办公管理、后勤保障',
    '采购管理': '行政采购、供应商管理',
    '企业文化': '文化建设、员工活动',
    '高管管理': '公司级决策与战略管理',
    '未分类': '暂未归类的岗位',
}


def build_func_match_data(employees: list, field_map: dict) -> dict:
    """
    代码层：判断数据源优先级 + 统计。
    返回 { data_source, source_groups, employees_by_source }
    """
    # 判断数据源：职位族 > 一级部门 > 岗位名称
    has_job_family = any(emp.get('job_family') for emp in employees)
    has_department = any(emp.get('department') for emp in employees)

    if has_job_family:
        data_source = 'job_family'
        source_field = 'job_family'
    elif has_department:
        data_source = 'department'
        source_field = 'department'
    else:
        data_source = 'job_title'
        source_field = 'job_title'

    # 按来源分组
    groups: dict[str, list] = {}
    for emp in employees:
        key = str(emp.get(source_field, '') or '').strip()
        if not key:
            key = '未分类'
        groups.setdefault(key, []).append(emp)

    source_stats = [
        {'source_name': k, 'count': len(v)}
        for k, v in sorted(groups.items(), key=lambda x: -x[1].__len__())
    ]

    # 二级分组（职位类来源）
    sub_source_field = 'job_class' if has_job_family else ('department_2' if has_department else 'job_title')

    sub_groups: dict[str, dict[str, list]] = {}
    for source_name, emps in groups.items():
        sub_groups[source_name] = {}
        for emp in emps:
            sub_key = str(emp.get(sub_source_field, '') or emp.get('job_title', '')).strip()
            if not sub_key:
                sub_key = '未分类'
            sub_groups[source_name].setdefault(sub_key, []).append(emp)

    return {
        'data_source': data_source,
        'source_stats': source_stats,
        'groups': groups,
        'sub_groups': sub_groups,
    }


def ai_match_families(source_names: list) -> dict:
    """AI #1：来源分类 → 标准职位族映射"""
    from app.agents.base_agent import BaseAgent
    agent = BaseAgent(temperature=0.2)

    prompt = f"""请将以下来源分类映射到铭曦标准职位族。

来源分类列表：{json.dumps(source_names, ensure_ascii=False)}

标准职位族（选一个）：
{json.dumps(FAMILY_LIST, ensure_ascii=False)}

各职位族含义：
{chr(10).join(f'- {k}: {v}' for k, v in FAMILY_DEFINITIONS.items())}

输出严格 JSON：{{"HR中心": "人力资源", "技术部": "技术研发", ...}}
值必须是标准职位族之一。只输出 JSON。"""

    messages = [
        {"role": "system", "content": "你是薪酬诊断系统的职能匹配模块。根据来源分类名称推断对应的标准职位族。"},
        {"role": "user", "content": prompt},
    ]
    response = agent.call_llm(messages)

    if '```json' in response:
        response = response.split('```json')[1].split('```')[0]
    elif '```' in response:
        response = response.split('```')[1].split('```')[0]

    try:
        mapping = json.loads(response.strip())
        for k, v in list(mapping.items()):
            if v not in FAMILY_LIST:
                mapping[k] = '其他'
        return mapping
    except json.JSONDecodeError:
        return {}


def ai_match_subfunctions(family_name: str, sub_source_names: list, job_titles: list) -> dict:
    """
    AI #2：在一个职位族内，来源职位类 → 标准职位类映射 + 岗位异常标记。
    返回 { 'sub_mapping': {来源: 标准}, 'mismatches': [{id, title, reason}] }
    """
    from app.agents.base_agent import BaseAgent
    agent = BaseAgent(temperature=0.2)

    available_subs = STANDARD_FAMILIES.get(family_name, ['未分类'])

    prompt = f"""在"{family_name}"职位族内，请完成两件事：

1. 将以下来源职位类映射到标准职位类
来源职位类：{json.dumps(sub_source_names, ensure_ascii=False)}
标准职位类选项：{json.dumps(available_subs, ensure_ascii=False)}

2. 检查以下岗位名称是否与所属职位族"{family_name}"匹配
岗位列表（只传了可能有问题的）：{json.dumps(job_titles[:20], ensure_ascii=False)}
如果某个岗位名称明显不属于"{family_name}"（如技术部下的"行政助理"），标记出来。

输出严格 JSON：
{{
  "sub_mapping": {{"HRBP组": "HRBP", "培训组": "培训发展"}},
  "mismatches": [{{"title": "行政助理", "suggested_family": "行政", "reason": "岗位职责与{family_name}不符"}}]
}}
只输出 JSON。"""

    messages = [
        {"role": "system", "content": "你是薪酬诊断系统的职能匹配模块。"},
        {"role": "user", "content": prompt},
    ]
    response = agent.call_llm(messages)

    if '```json' in response:
        response = response.split('```json')[1].split('```')[0]
    elif '```' in response:
        response = response.split('```')[1].split('```')[0]

    try:
        result = json.loads(response.strip())
        # 校验 sub_mapping 值
        sub_mapping = result.get('sub_mapping', {})
        for k, v in list(sub_mapping.items()):
            if v not in available_subs:
                sub_mapping[k] = available_subs[0] if available_subs else '未分类'
        result['sub_mapping'] = sub_mapping
        return result
    except json.JSONDecodeError:
        return {'sub_mapping': {}, 'mismatches': []}
