from flask import Blueprint, jsonify, request, current_app
import os
import uuid

upload_bp = Blueprint('upload', __name__)

@upload_bp.route('/<session_id>', methods=['POST'])
def upload_file(session_id):
    """Upload Excel file for a session"""
    from app.api.sessions import sessions_store

    session = sessions_store.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        return jsonify({'error': 'Unsupported file format'}), 400

    # Save file
    upload_dir = current_app.config['UPLOAD_DIR']
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f'{session_id}_{file.filename}')
    file.save(file_path)

    # Update session
    session['status'] = 'uploading'
    session['upload_file_path'] = file_path

    # For MVP: return mock parsed data immediately
    mock_result = get_mock_parse_result()
    session['status'] = 'parsed'
    session['employee_count'] = mock_result['employee_count']
    session['parse_result'] = mock_result

    # Pre-populate mock employee data for analysis pipeline
    from app.api.report import get_mock_employees
    session['cleaned_employees'] = get_mock_employees()

    return jsonify(mock_result), 200


def get_mock_parse_result():
    """Mock Excel parsing result"""
    return {
        'employee_count': 126,
        'grade_count': 6,
        'department_count': 5,
        'grades': ['L3', 'L4', 'L5', 'L6', 'L7', 'L8'],
        'departments': ['研发', '销售', '市场', '人力资源', '行政'],
        'fields_detected': [
            {'name': '姓名', 'detected': True},
            {'name': '岗位', 'detected': True},
            {'name': '职级', 'detected': True},
            {'name': '月薪', 'detected': True},
            {'name': '年终奖', 'detected': True},
            {'name': '部门', 'detected': True},
            {'name': '绩效', 'detected': True},
            {'name': '入司时间', 'detected': True},
        ],
        'completeness_issues': {
            'row_missing': [
                {'row': 15, 'field': '月薪', 'issue': '月薪为空'},
                {'row': 23, 'field': '职级', 'issue': '职级为空'},
                {'row': 67, 'field': '岗位名称', 'issue': '岗位名称为空'},
            ],
            'column_missing': [
                {'field': '管理岗/专业岗', 'impact': '管理溢价分析不可用'},
                {'field': '是否关键岗位', 'impact': '关键岗位下钻不可用'},
                {'field': '管理复杂度', 'impact': '管理复杂度定价不可用'},
            ]
        },
        'cleansing_corrections': [
            {'id': 0, 'description': '第 5、12、30 行年终奖已年化处理（入司不满 1 年）', 'type': 'annualize_bonus'},
            {'id': 1, 'description': '全部员工 13 薪已从年终奖移入固定薪酬', 'type': '13th_month_reclassify'},
            {'id': 2, 'description': '第 45 行月薪 ¥85,000 已标记为异常值', 'type': 'extreme_value'},
        ],
        'grade_matching': [
            {'client_grade': 'L3', 'standard_grade': '专员级', 'confidence': 'high', 'confirmed': True},
            {'client_grade': 'L4', 'standard_grade': '高级专员级', 'confidence': 'high', 'confirmed': True},
            {'client_grade': 'L5', 'standard_grade': '经理级', 'confidence': 'high', 'confirmed': True},
            {'client_grade': 'L6', 'standard_grade': '高级经理级', 'confidence': 'high', 'confirmed': True},
            {'client_grade': 'L7', 'standard_grade': None, 'confidence': 'low', 'confirmed': False},
            {'client_grade': 'L8', 'standard_grade': '总监级', 'confidence': 'high', 'confirmed': True},
        ],
        'function_matching': [
            {'title': '软件工程师', 'matched': '技术研发-软件开发', 'confidence': 'high', 'confirmed': True},
            {'title': 'HRBP 经理', 'matched': '人力资源-HRBP', 'confidence': 'high', 'confirmed': True},
            {'title': '增长黑客', 'matched': None, 'confidence': 'low', 'confirmed': False, 'alternatives': ['数字营销', '用户增长']},
            {'title': '销售总监', 'matched': '销售-大客户销售', 'confidence': 'high', 'confirmed': True},
            {'title': '财务主管', 'matched': '财务-财务管理', 'confidence': 'high', 'confirmed': True},
        ],
        'data_completeness_score': 78,
        'unlocked_modules': ['外部竞争力分析', '内部公平性分析', '薪酬固浮比分析'],
        'locked_modules': [
            {'name': '绩效关联分析', 'reason': '缺少绩效字段'},
            {'name': '人工成本趋势分析', 'reason': '缺少公司经营数据'},
        ],
    }
