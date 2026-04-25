"""
JE 工具对外入口：把 JD 文本评成 Hay 8 因子 + 职级。

调用方式：
    from app.tools.je.evaluator import evaluate_job
    result = evaluate_job(jd_text='...', job_title='销售经理', function='销售')
    # → {factors, kh, ps, acc, total_score, job_grade, profile, pk_reasoning, ...}
"""
from typing import Optional

from .engine.incremental_convergence import IncrementalConvergence
from .engine.validation_rules import validation_rules
from .engine.calculator import HayCalculator
from .engine.models import HayFactors
from .extract_pk import extract_pk_from_jd
from .function_catalog import is_valid_function


class _PKLLMAdapter:
    """
    把 extract_pk_from_jd 包装成引擎期望的 llm_service 接口。

    引擎在 find_optimal_solution() 里只调用 .extract_pk_range()，
    我们注入这个 adapter 替代学生版的 LLMService。
    """
    def __init__(self, model: Optional[str] = None):
        self.model = model

    def extract_pk_range(self, eval_text: str, title: str, function: str, assessment_type: str = 'CV') -> dict:
        result = extract_pk_from_jd(jd_text=eval_text, job_title=title, function=function, model=self.model)
        # 引擎会读 education 做学历兜底；JE 场景没有"候选人学历"，传 '未知' 触发 no-op
        return {
            'practical_knowledge': result['practical_knowledge'],
            'education': '未知',
            'reasoning': result.get('reasoning', ''),
        }


# 默认单例（不指定 model 时用，跟启动时配置的 OPENROUTER_MODEL 走）
_default_engine: Optional[IncrementalConvergence] = None


def _get_engine(model: Optional[str] = None) -> IncrementalConvergence:
    """
    返回引擎实例。
    - model=None：用默认单例（OPENROUTER_MODEL）
    - model 显式指定：每次新建一个引擎，因为 _PKLLMAdapter 在 __init__ 里固化了 model；
      复用单例会让"批量评估时跨岗位负载均衡到不同模型"失效（之前的 bug）。
      新建成本可忽略：validation_rules 是模块级单例，引擎本身只是几个字段。
    """
    global _default_engine
    if model is not None:
        return IncrementalConvergence(validation_rules, llm_service=_PKLLMAdapter(model=model))
    if _default_engine is None:
        _default_engine = IncrementalConvergence(validation_rules, llm_service=_PKLLMAdapter())
    return _default_engine


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
            'convergence_stats': {...},
        }

    Raises:
        ValueError: 职能非法 / LLM 返回非法 PK
    """
    if not is_valid_function(function):
        raise ValueError(f'unsupported function: {function!r}')

    engine = _get_engine(model=model)
    raw = engine.find_optimal_solution(
        eval_text=jd_text,
        title=job_title,
        function=function,
        assessment_type='CV',
    )

    best = raw['best_solution']  # 只含 8 因子，分数没在里面
    factors_only = {k: best[k] for k in (
        'practical_knowledge', 'managerial_knowledge', 'communication',
        'thinking_challenge', 'thinking_environment',
        'freedom_to_act', 'magnitude', 'nature_of_impact',
    )}

    # 用 HayCalculator 把 8 因子算成分数 + 职级（确定性，几毫秒）
    scored = evaluate_with_factors(factors_only)
    scored['convergence_stats'] = raw.get('convergence_stats', {})
    scored['match_score'] = raw.get('match_score')
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

    return {
        'factors': factors,
        'kh_score': result.know_how.kh_score,
        'ps_score': result.problem_solving.ps_score,
        'acc_score': result.accountability.acc_score,
        'total_score': result.total_score,
        'job_grade': result.job_grade,
        'profile': None,
        'pk_reasoning': '',
        'convergence_stats': {},
        'match_score': None,
    }
