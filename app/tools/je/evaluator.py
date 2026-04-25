"""
JE 工具对外入口：把 JD 文本评成 Hay 8 因子 + 职级。

调用方式：
    from app.tools.je.evaluator import evaluate_job
    result = evaluate_job(jd_text='...', job_title='销售经理', function='销售')
    # → {factors, kh, ps, acc, total_score, job_grade, profile, pk_reasoning,
    #    candidates: [...], convergence_stats: {...}}
"""
from typing import Optional

from .engine.incremental_convergence import IncrementalConvergence
from .engine.validation_rules import validation_rules
from .engine.calculator import HayCalculator
from .engine.models import HayFactors
from .extract_pk import extract_pk_from_jd
from .function_catalog import is_valid_function


_FACTOR_KEYS = (
    'practical_knowledge', 'managerial_knowledge', 'communication',
    'thinking_challenge', 'thinking_environment',
    'freedom_to_act', 'magnitude', 'nature_of_impact',
)


class _PKLLMAdapter:
    """
    把 extract_pk_from_jd 包装成引擎期望的 llm_service 接口。

    引擎只用 .extract_pk_range() 拿 PK 档位，但 LLM 同时返回了 reasoning（"为什么是 D 档"
    的解释文本）。引擎自己不消费 reasoning，所以我们把它缓存到 adapter 实例，外层
    evaluate_job 用完后从 .last_reasoning 取出来给前端展示。

    每次 evaluate_job 调用都新建 adapter（不复用），避免多线程并发时 last_reasoning
    被串。
    """
    def __init__(self, model: Optional[str] = None):
        self.model = model
        self.last_reasoning = ''

    def extract_pk_range(self, eval_text: str, title: str, function: str, assessment_type: str = 'CV') -> dict:
        result = extract_pk_from_jd(jd_text=eval_text, job_title=title, function=function, model=self.model)
        self.last_reasoning = result.get('reasoning', '')
        # 引擎会读 education 做学历兜底；JE 场景没有"候选人学历"，传 '未知' 触发 no-op
        return {
            'practical_knowledge': result['practical_knowledge'],
            'education': '未知',
            'reasoning': self.last_reasoning,
        }


def evaluate_job(jd_text: str, job_title: str, function: str, model: Optional[str] = None) -> dict:
    """
    主评估入口。

    Args:
        jd_text:   岗位 JD 文本
        job_title: 岗位名称
        function:  业务职能（必须在 function_catalog.all_functions() 内）
        model:     可选 LLM model 覆盖

    Returns:
        {
            'factors':       {pk, mk, comm, tc, te, freedom, magnitude, nature},
            'kh_score':      330,
            'ps_score':      87,
            'acc_score':     43,
            'total_score':   460,
            'job_grade':     14,
            'profile':       'P3',
            'pk_reasoning':  '该岗位...',
            'candidates':    [{factors, total_score, job_grade, profile, match_score, dominant}, ...],
            'convergence_stats': {...},
        }

    Raises:
        ValueError: 职能非法 / LLM 返回非法 PK
    """
    if not is_valid_function(function):
        raise ValueError(f'unsupported function: {function!r}')

    # 不复用引擎单例：adapter 带状态（last_reasoning）；每次跑个新引擎更安全。
    # validation_rules 是模块级单例，构造引擎本身只是几个字段赋值，开销可忽略。
    adapter = _PKLLMAdapter(model=model)
    engine = IncrementalConvergence(validation_rules, llm_service=adapter)
    raw = engine.find_optimal_solution(
        eval_text=jd_text,
        title=job_title,
        function=function,
        assessment_type='CV',
    )

    best = raw['best_solution']
    factors_only = {k: best[k] for k in _FACTOR_KEYS}

    # 用 HayCalculator 把 8 因子算成分数 + 职级（确定性，几毫秒）
    scored = evaluate_with_factors(factors_only)
    scored['pk_reasoning'] = adapter.last_reasoning
    scored['profile'] = scored.get('profile') or _profile_for_solution(best, raw)
    scored['convergence_stats'] = raw.get('convergence_stats', {})
    scored['match_score'] = raw.get('match_score')
    scored['candidates'] = _build_candidates(raw.get('all_valid_solutions') or [])
    return scored


def evaluate_with_factors(factors: dict) -> dict:
    """
    跳过 LLM，直接用给定的 8 因子算总分 + 职级。
    用于"HR 反向手改某个因子重算"的场景（Q1-C 决策）。

    Args:
        factors: {practical_knowledge, managerial_knowledge, communication,
                  thinking_challenge, thinking_environment,
                  freedom_to_act, magnitude, nature_of_impact}

    Returns:
        与 evaluate_job 相同的结构，但 pk_reasoning 为空，convergence_stats 为空
    """
    hay_factors = HayFactors(**factors)
    calc = HayCalculator()
    result = calc.calculate(hay_factors)

    profile = None
    if result.summary and result.summary.job_profile:
        profile = result.summary.job_profile.profile_type

    return {
        'factors': factors,
        'kh_score': result.know_how.kh_score,
        'ps_score': result.problem_solving.ps_score,
        'acc_score': result.accountability.acc_score,
        'total_score': result.total_score,
        'job_grade': result.job_grade,
        'profile': profile,
        'pk_reasoning': '',
        'candidates': [],
        'convergence_stats': {},
        'match_score': None,
    }


# ---------------------------------------------------------------------------
# 多解候选挑选
# ---------------------------------------------------------------------------

def _build_candidates(valid_solutions: list, max_n: int = 3) -> list[dict]:
    """
    从引擎返回的全部合法方案里挑出 top-N 多样性候选给前端展示。

    输入 valid_solutions: [(factors_dict, match_score, profile, job_grade), ...]，
    已按 match_score 降序。

    多样性策略：
    - 优先按 (profile, job_grade) 去重（相同 profile + 相同职级只留一个 — 都是同等"最优"，
      没必要让 HR 在 8 因子完全相同的两套方案里选）
    - 其次按 job_grade 多样性挑选（如果有 G11/G12/G13 三种结果，每种各取一个）
    - 始终保留榜首（最高匹配度）作为第 1 位
    """
    if not valid_solutions:
        return []

    seen_keys: set[tuple] = set()
    diverse: list[tuple] = []   # 留下来的 (factors, score, profile, grade)
    for sol in valid_solutions:
        if len(diverse) >= max_n:
            break
        factors_dict, match_score, profile, job_grade = sol
        key = (profile, job_grade)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        diverse.append(sol)

    # 还不到 max_n？再补几个不去重的（同 profile/grade 但 8 因子不同的方案）
    if len(diverse) < max_n:
        for sol in valid_solutions:
            if len(diverse) >= max_n:
                break
            if sol not in diverse:
                diverse.append(sol)

    out: list[dict] = []
    for factors_dict, match_score, profile, job_grade in diverse:
        factors = {k: factors_dict[k] for k in _FACTOR_KEYS}
        scored = evaluate_with_factors(factors)
        kh = scored['kh_score'] or 0
        ps = scored['ps_score'] or 0
        acc = scored['acc_score'] or 0
        out.append({
            'factors': factors,
            'kh_score': kh,
            'ps_score': ps,
            'acc_score': acc,
            'total_score': scored['total_score'],
            'job_grade': job_grade,
            'profile': profile,
            'match_score': round(match_score, 1) if match_score is not None else None,
            'dominant': _dominant_dimension(kh, ps, acc),
            'orientation': _orientation_label(profile),
        })
    return out


def _dominant_dimension(kh: int, ps: int, acc: int) -> str:
    """返回 KH/PS/ACC 三者中最大的一个。total=0 时返回 'unknown'。"""
    if (kh + ps + acc) == 0:
        return 'unknown'
    biggest = max(kh, ps, acc)
    if biggest == kh:
        return 'KH'
    if biggest == ps:
        return 'PS'
    return 'ACC'


def _orientation_label(profile: Optional[str]) -> str:
    """根据 profile 标记岗位倾向：P 型偏专业，A 型偏管理，L 平衡。"""
    if not profile:
        return ''
    if profile.startswith('P'):
        return '偏专业 / 操作型'
    if profile.startswith('A'):
        return '偏管理 / 战略型'
    if profile == 'L':
        return '平衡型'
    return profile


def _profile_for_solution(best_solution: dict, raw: dict) -> Optional[str]:
    """从 all_valid_solutions 里找出 best_solution 对应的 profile 标签。"""
    for sol in raw.get('all_valid_solutions') or []:
        factors_dict, _match, profile, _grade = sol
        if all(factors_dict.get(k) == best_solution.get(k) for k in _FACTOR_KEYS):
            return profile
    return None
