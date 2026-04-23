"""
上传流水线分叉：
  Path A（模板上传）：表头 / 关键词能覆盖所有必填字段 → 直接跑完整 pipeline，前端进数据确认
  Path B（自由上传）：覆盖不全 → 返回 mapping_needed:true + AI 字段识别建议
                       前端展示字段映射确认面板，用户确认后调 /confirm-mapping 跑 pipeline

静态模板：static/薪酬诊断数据收集模板.xlsx
"""
from flask import Blueprint, jsonify, request, current_app, send_file
import os
from app.core.auth import require_auth
from app.api._session_helpers import owned_session_or_403

upload_bp = Blueprint('upload', __name__)


@upload_bp.route('/template', methods=['GET'])
@require_auth
def download_template():
    """下载标准模板 xlsx"""
    # static 目录挂在 app 根目录平级
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    template_path = os.path.join(repo_root, 'static', '薪酬诊断数据收集模板.xlsx')
    if not os.path.exists(template_path):
        return jsonify({'error': 'Template not found'}), 404
    return send_file(
        template_path,
        as_attachment=True,
        download_name='薪酬诊断数据收集模板.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@upload_bp.route('/<session_id>', methods=['POST'])
@require_auth
def upload_file(session_id):
    """
    上传 Excel。
    先解析表头，判断是否和模板列名对得上：
      - 对得上 → 直接跑完整 pipeline，返回 ParseResult（前端进数据确认）
      - 对不上 → 返回 mapping_needed:true + AI 字段映射建议（前端进字段映射确认页）
    """
    session, err = owned_session_or_403(session_id)
    if err:
        return err

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        return jsonify({'error': 'Unsupported file format'}), 400

    # 存文件
    upload_dir = current_app.config['UPLOAD_DIR']
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f'{session_id}_{file.filename}')
    file.save(file_path)

    session['status'] = 'uploading'
    session['upload_file_path'] = file_path

    # 快速看一眼表头：够不够用
    from app.services.pipeline import (
        has_all_required_from_template, parse_headers_and_samples, run_upload_pipeline,
    )
    try:
        parsed_preview = parse_headers_and_samples(file_path)
    except Exception as e:
        return jsonify({'error': f'Excel 解析失败：{e}'}), 400

    columns = parsed_preview['columns']
    samples = parsed_preview['sample_rows']
    template_ok, keyword_field_map = has_all_required_from_template(columns)
    print(f'[Upload] {session_id} columns={columns} template_ok={template_ok}')

    # -------------------- Path A：模板上传 --------------------
    if template_ok:
        try:
            result = run_upload_pipeline(file_path, session)
            session['status'] = 'parsed'
            session['employee_count'] = result['employee_count']
            session['parse_result'] = result
            session['cleaned_employees'] = result.get('_employees', [])
            return jsonify({**result, 'mapping_needed': False}), 200
        except Exception as e:
            import traceback
            print(f'[Upload] Pipeline failed: {e}')
            traceback.print_exc()
            return jsonify({'error': f'解析失败：{e}'}), 500

    # -------------------- Path B：自由上传，触发 AI 字段映射 --------------------
    from app.services.ai_field_matcher import suggest_field_mapping
    from app.services.standard_fields import STANDARD_FIELDS
    suggestion = suggest_field_mapping(columns, samples)

    # 缓存到 session：用户确认映射后还要用
    session['_upload_columns'] = columns
    session['_upload_samples'] = samples
    session['_upload_keyword_field_map'] = keyword_field_map  # 备用

    return jsonify({
        'mapping_needed': True,
        'columns': columns,
        'sample_rows': [r['data'] if isinstance(r, dict) and 'data' in r else r for r in samples[:5]],
        'suggestion': suggestion,              # AI 映射建议
        'standard_fields': STANDARD_FIELDS,    # 给前端下拉框用
    }), 200


@upload_bp.route('/<session_id>/confirm-mapping', methods=['POST'])
@require_auth
def confirm_mapping(session_id):
    """
    Path B 的第二步：用户在字段映射面板确认后调这个。
    请求体：{ 'mappings': [{'user_column': '姓名', 'system_field': 'employee_id'}, ...] }
    把 standard_key → user_column 的映射转成 pipeline 熟悉的 old-key → user_column 格式，
    然后跑完整 pipeline 返回 ParseResult。
    """
    from app.services.standard_fields import PIPELINE_KEY_ALIAS
    from app.services.pipeline import run_upload_pipeline

    session, err = owned_session_or_403(session_id)
    if err:
        return err

    file_path = session.get('upload_file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': '上传文件已过期，请重新上传'}), 400

    data = request.json or {}
    mappings = data.get('mappings') or []

    # 转成 pipeline 使用的 field_map: {pipeline_key: user_column_name}
    field_map_override: dict = {}
    for m in mappings:
        std_key = m.get('system_field')
        user_col = m.get('user_column')
        if not std_key or not user_col:
            continue
        pipeline_key = PIPELINE_KEY_ALIAS.get(std_key)
        if not pipeline_key:
            continue
        field_map_override[pipeline_key] = user_col

    print(f'[Upload] {session_id} confirm-mapping field_map={field_map_override}')

    try:
        result = run_upload_pipeline(file_path, session, field_map_override=field_map_override)
        session['status'] = 'parsed'
        session['employee_count'] = result['employee_count']
        session['parse_result'] = result
        session['cleaned_employees'] = result.get('_employees', [])
        # 清掉临时缓存
        session.pop('_upload_columns', None)
        session.pop('_upload_samples', None)
        session.pop('_upload_keyword_field_map', None)
        return jsonify({**result, 'mapping_needed': False}), 200
    except Exception as e:
        import traceback
        print(f'[Upload] Pipeline after mapping failed: {e}')
        traceback.print_exc()
        return jsonify({'error': f'映射确认后解析失败：{e}'}), 500
