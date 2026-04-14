"""
能力注册表：Sparky 的技能树。
每个 skill 声明：触发条件、前置检查、引擎入口、叙事 prompt。
新增能力 = 加一条注册 + 实现 engine 函数。
"""
from typing import Callable, Optional

SKILLS: dict[str, dict] = {
    # =======================================
    # 重模式
    # =======================================
    'full_diagnosis': {
        'key': 'full_diagnosis',
        'display_name': '完整薪酬诊断',
        'mode': 'heavy',
        'triggers': [
            '完整', '全面', '诊断', '体检', '系统地', '整体',
            '做一次诊断', '薪酬诊断', '全方位',
        ],
        'preconditions': ['has_data_snapshot'],
        'chip_label': '做一次完整的薪酬诊断',
        'chip_icon': '📊',
        'estimated_duration': '10-15 分钟',
        'engine': None,  # heavy 模式走既有 Stage 1-5 流程
        'narrative_prompt': 'diagnosis_summary.txt',
    },

    # =======================================
    # 轻模式
    # =======================================
    'external_benchmark': {
        'key': 'external_benchmark',
        'display_name': '外部市场对标',
        'mode': 'light',
        'triggers': [
            '市场', '对标', 'P50', 'P25', 'P75', 'p50', 'p25', 'p75',
            '竞争力', '行业水平', '市场水平', '跟市场',
            '市场薪酬', '同行', '外部对比', '差距',
        ],
        'preconditions': ['has_data_snapshot'],
        'chip_label': '查一下市场薪酬水平',
        'chip_icon': '🔍',
        'estimated_duration': '30 秒',
        'engine': 'app.skills.external_benchmark.run',
        'narrative_prompt': 'skill_benchmark.txt',
        'render_components': ['BarH', 'MetricGrid', 'Table'],
    },

    'salary_simulation': {
        'key': 'salary_simulation',
        'display_name': '调薪预算模拟',
        'mode': 'light',
        'triggers': [
            '调薪', '调到', '加薪', '预算', '涨薪', '薪酬调整',
            '多少钱', '加多少', '到 P', '分配',
        ],
        'preconditions': ['has_data_snapshot'],
        'chip_label': '调薪预算怎么分配',
        'chip_icon': '📈',
        'estimated_duration': '1 分钟',
        'engine': 'app.skills.salary_simulation.run',
        'narrative_prompt': 'skill_simulation.txt',
        'render_components': ['MetricGrid', 'ComparisonTable'],
    },

    'offer_check': {
        'key': 'offer_check',
        'display_name': '候选人定薪建议',
        'mode': 'light',
        'triggers': [
            '候选人', '定薪', '发多少', '发 offer', '招聘定薪',
            '期望薪资', '定价', '新人定薪',
        ],
        'preconditions': [],
        'chip_label': '候选人定薪建议',
        'chip_icon': '💰',
        'estimated_duration': '10 秒',
        'engine': 'app.skills.offer_check.run',
        'narrative_prompt': 'skill_offer.txt',
        'render_components': ['MetricGrid'],
    },

    'grade_lookup': {
        'key': 'grade_lookup',
        'display_name': '市场薪酬查询',
        'mode': 'light',
        'triggers': [
            '查询', '查一下', '看一下', 'Hay', 'hay', '职级薪酬',
            '行情', '水平大概', '大概多少',
        ],
        'preconditions': [],
        'chip_label': '查某个职级的市场行情',
        'chip_icon': '🔎',
        'estimated_duration': '10 秒',
        'engine': 'app.skills.grade_lookup.run',
        'narrative_prompt': 'skill_lookup.txt',
        'render_components': ['MetricGrid'],
    },
}


def get_skill(key: str) -> Optional[dict]:
    return SKILLS.get(key)


def list_skills(mode: Optional[str] = None) -> list[dict]:
    items = list(SKILLS.values())
    if mode:
        items = [s for s in items if s['mode'] == mode]
    return items


def get_engine_fn(skill_key: str) -> Optional[Callable]:
    """动态加载 engine 函数"""
    skill = get_skill(skill_key)
    if not skill or not skill.get('engine'):
        return None
    module_path, fn_name = skill['engine'].rsplit('.', 1)
    import importlib
    try:
        module = importlib.import_module(module_path)
        return getattr(module, fn_name, None)
    except (ImportError, AttributeError) as e:
        print(f'[SkillRegistry] Failed to load {skill["engine"]}: {e}')
        return None


def check_preconditions(skill_key: str, context: dict) -> tuple[bool, Optional[str]]:
    """检查前置条件。返回 (是否通过, 未通过原因)"""
    skill = get_skill(skill_key)
    if not skill:
        return False, '未知能力'
    for pre in skill.get('preconditions', []):
        if pre == 'has_data_snapshot':
            if not context.get('snapshot_id') and not context.get('has_data'):
                return False, '需要先上传一份薪酬数据'
        # 其他前置条件按需扩展
    return True, None
