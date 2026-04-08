from concurrent.futures import ThreadPoolExecutor
from app.services.preprocessor import run_code_checks
from app.services.excel_parser import parse_excel
from app.agents.cleansing_agent import CleansingAgent

executor = ThreadPoolExecutor(max_workers=4)


def run_cleansing_pipeline(session_id, file_path):
    """
    完整的清洗流程：
    1. 解析 Excel
    2. 代码层跑确定性规则
    3. AI 层判断不确定问题
    4. 代码层执行修正
    """
    # Step 1: Parse Excel
    parsed = parse_excel(file_path)

    # Step 2: Code checks
    code_results = run_code_checks(parsed)

    # Step 3: AI judgments (only for uncertain issues)
    agent = CleansingAgent()
    ai_results = agent.run(code_results)

    # Step 4: Apply corrections based on AI judgments
    corrections = apply_corrections(parsed, code_results, ai_results)

    return {
        'parsed': parsed,
        'code_checks': code_results,
        'ai_judgments': ai_results,
        'corrections': corrections,
    }


def apply_corrections(parsed, code_results, ai_results):
    """根据代码检测和AI判断，执行数据修正"""
    corrections_applied = []

    # Apply annualization if AI confirmed
    if ai_results and 'judgments' in ai_results:
        for j in ai_results['judgments']:
            if j.get('action') and not j.get('needs_user_confirm'):
                corrections_applied.append({
                    'rule': j['rule'],
                    'rows': j['rows'],
                    'action': j['action'],
                    'auto_applied': True,
                })
            elif j.get('needs_user_confirm'):
                corrections_applied.append({
                    'rule': j['rule'],
                    'rows': j['rows'],
                    'action': j['action'],
                    'auto_applied': False,
                    'user_question': j.get('user_question'),
                })

    return corrections_applied


def run_analysis_pipeline(session_id):
    """Run all analysis modules"""
    # TODO: Implement actual analysis
    pass
