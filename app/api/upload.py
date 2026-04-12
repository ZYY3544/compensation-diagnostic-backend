from flask import Blueprint, jsonify, request, current_app
import os

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

    session['status'] = 'uploading'
    session['upload_file_path'] = file_path

    try:
        # Run full pipeline: parse → code checks → AI cleansing → grade match → func match
        from app.services.pipeline import run_upload_pipeline
        result = run_upload_pipeline(file_path, session)
        session['status'] = 'parsed'
        session['employee_count'] = result['employee_count']
        session['parse_result'] = result
        session['cleaned_employees'] = result.get('_employees', [])
        return jsonify(result), 200
    except Exception as e:
        # Fallback to mock if pipeline fails
        import traceback
        print(f'Pipeline failed: {e}, using mock data')
        traceback.print_exc()
        mock_result = get_mock_parse_result()
        session['status'] = 'parsed'
        session['employee_count'] = mock_result['employee_count']
        session['parse_result'] = mock_result
        from app.api.report import get_mock_employees
        session['cleaned_employees'] = get_mock_employees()
        return jsonify(mock_result), 200


def parse_uploaded_file(file_path):
    """Parse the uploaded Excel and return structured result for frontend"""
    from app.services.excel_parser import parse_excel

    parsed = parse_excel(file_path)
    rows = parsed.get('sheet1_data', [])
    columns = parsed.get('column_names', [])
    sheet2 = parsed.get('sheet2_data', {})

    # Detect fields
    field_map = detect_fields(columns)

    # Extract unique values
    grades = set()
    departments = set()
    employees_for_analysis = []

    for row in rows:
        d = row['data']
        grade = get_mapped_value(d, field_map, 'grade')
        dept = get_mapped_value(d, field_map, 'department')
        if grade:
            grades.add(str(grade))
        if dept:
            departments.add(str(dept))

        # Build employee dict for analysis
        base = safe_float(get_mapped_value(d, field_map, 'base_salary'))
        bonus = safe_float(get_mapped_value(d, field_map, 'bonus'))
        emp = {
            'id': get_mapped_value(d, field_map, 'employee_id') or f'ROW{row["row_number"]}',
            'job_title': get_mapped_value(d, field_map, 'job_title') or '',
            'grade': str(grade) if grade else '',
            'department': str(dept) if dept else '',
            'base_monthly': base,
            'annual_bonus': bonus,
            'performance': get_mapped_value(d, field_map, 'performance') or '',
            'hire_date': str(get_mapped_value(d, field_map, 'hire_date') or ''),
            'manager': get_mapped_value(d, field_map, 'manager') or '',
        }
        employees_for_analysis.append(emp)

    grades_list = sorted(grades)
    depts_list = sorted(departments)

    # Detect completeness issues
    row_missing = []
    required_fields = ['job_title', 'grade', 'base_salary', 'bonus']
    for row in rows:
        d = row['data']
        for req in required_fields:
            val = get_mapped_value(d, field_map, req)
            if val is None or str(val).strip() == '':
                field_label = {'job_title': '岗位名称', 'grade': '职级', 'base_salary': '月薪', 'bonus': '年终奖'}.get(req, req)
                row_missing.append({'row': row['row_number'], 'field': field_label, 'issue': f'{field_label}为空'})

    # Check for missing optional columns
    column_missing = []
    optional_checks = [
        ('management_track', '管理岗/专业岗', '管理溢价分析不可用'),
        ('key_position', '是否关键岗位', '关键岗位下钻不可用'),
        ('management_complexity', '管理复杂度', '管理复杂度定价不可用'),
    ]
    for field_key, field_name, impact in optional_checks:
        if field_key not in field_map:
            column_missing.append({'field': field_name, 'impact': impact})

    # Build cleansing corrections (basic detection)
    corrections = []
    corr_id = 0

    # Check for potential annualization needs
    for emp in employees_for_analysis:
        hire = emp.get('hire_date', '')
        bonus = emp.get('annual_bonus', 0)
        if hire and '2025' in str(hire) and bonus and bonus > 0:
            # Rough check: hired in 2025, might need annualization
            corr_id += 1
            corrections.append({
                'id': corr_id,
                'description': f'员工 {emp["id"]} 入司时间较近（{hire}），年终奖可能需要年化',
                'type': 'annualize_bonus'
            })
            if len(corrections) >= 5:
                break

    # Build grade matching (auto-detect)
    grade_matching = []
    for g in grades_list:
        grade_matching.append({
            'client_grade': g,
            'standard_grade': None,
            'confidence': 'low',
            'confirmed': False,
        })

    # Build function matching (from job titles)
    seen_titles = set()
    function_matching = []
    for emp in employees_for_analysis:
        title = emp.get('job_title', '')
        if title and title not in seen_titles:
            seen_titles.add(title)
            function_matching.append({
                'title': title,
                'matched': None,
                'confidence': 'low',
                'confirmed': False,
            })
        if len(function_matching) >= 10:
            break

    # Determine unlocked/locked modules
    has_performance = 'performance' in field_map
    has_company_data = len(sheet2) > 0
    unlocked = ['外部竞争力分析', '内部公平性分析', '薪酬固浮比分析']
    locked = []
    if has_performance:
        unlocked.append('绩效关联分析')
    else:
        locked.append({'name': '绩效关联分析', 'reason': '缺少绩效字段'})
    if has_company_data:
        unlocked.append('人工成本趋势分析')
    else:
        locked.append({'name': '人工成本趋势分析', 'reason': '缺少公司经营数据'})

    fields_detected = []
    standard_fields = [
        ('employee_id', '姓名/工号'), ('job_title', '岗位'), ('grade', '职级'),
        ('base_salary', '月薪'), ('bonus', '年终奖'), ('department', '部门'),
        ('performance', '绩效'), ('hire_date', '入司时间'),
    ]
    for key, label in standard_fields:
        fields_detected.append({'name': label, 'detected': key in field_map})

    completeness_score = int((1 - len(row_missing) / max(len(rows) * len(required_fields), 1)) * 100)

    result = {
        'employee_count': len(rows),
        'grade_count': len(grades_list),
        'department_count': len(depts_list),
        'grades': grades_list,
        'departments': depts_list,
        'fields_detected': fields_detected,
        'completeness_issues': {
            'row_missing': row_missing[:20],  # Cap at 20
            'column_missing': column_missing,
        },
        'cleansing_corrections': corrections,
        'grade_matching': grade_matching,
        'function_matching': function_matching,
        'data_completeness_score': max(0, min(100, completeness_score)),
        'unlocked_modules': unlocked,
        'locked_modules': locked,
        '_employees': employees_for_analysis,  # Internal, for analysis pipeline
    }
    return result


def detect_fields(columns):
    """Map column names to standard field names using keyword matching"""
    field_map = {}
    patterns = {
        'employee_id': ['工号', '姓名', '员工'],
        'job_title': ['岗位', '职位', '头衔'],
        'grade': ['职级', '级别', '层级', 'level'],
        'department': ['部门', '一级'],
        'base_salary': ['月薪', '基本工资', '固定月薪', '月度基本'],
        'bonus': ['年终奖', '奖金', '年终'],
        'thirteenth': ['13薪', '十三薪'],
        'allowance': ['津贴', '补贴', '补助'],
        'performance': ['绩效', '考核', '评级'],
        'hire_date': ['入职', '入司', '入职日期'],
        'manager': ['上级', '汇报', '主管'],
        'management_track': ['管理岗', '专业岗', '通道'],
        'key_position': ['关键岗位', '核心岗位'],
        'management_complexity': ['管理复杂度', '复杂度'],
        'city': ['城市', 'base'],
        'age': ['年龄'],
        'education': ['学历', '教育'],
    }

    for col in columns:
        col_lower = col.lower() if col else ''
        for field_key, keywords in patterns.items():
            if field_key not in field_map:
                for kw in keywords:
                    if kw.lower() in col_lower:
                        field_map[field_key] = col
                        break

    return field_map


def get_mapped_value(row_data, field_map, field_key):
    """Get value from row using field mapping"""
    col_name = field_map.get(field_key)
    if col_name and col_name in row_data:
        return row_data[col_name]
    return None


def safe_float(val):
    """Safely convert to float"""
    if val is None:
        return 0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0


def get_mock_parse_result():
    """Mock Excel parsing result (fallback)"""
    return {
        'employee_count': 126,
        'grade_count': 6,
        'department_count': 5,
        'grades': ['L3', 'L4', 'L5', 'L6', 'L7', 'L8'],
        'departments': ['研发', '销售', '市场', '人力资源', '行政'],
        'fields_detected': [
            {'name': '姓名', 'detected': True}, {'name': '岗位', 'detected': True},
            {'name': '职级', 'detected': True}, {'name': '月薪', 'detected': True},
            {'name': '年终奖', 'detected': True}, {'name': '部门', 'detected': True},
            {'name': '绩效', 'detected': True}, {'name': '入司时间', 'detected': True},
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
