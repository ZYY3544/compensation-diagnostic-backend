"""
诊断报告 PDF 导出。
用 reportlab 生成简洁的中文 PDF。
"""
import os
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 注册中文字体（使用系统字体）
_font_registered = False
def _ensure_font():
    global _font_registered
    if _font_registered:
        return
    # 尝试常见中文字体路径
    font_paths = [
        '/System/Library/Fonts/STHeiti Light.ttc',  # macOS
        '/System/Library/Fonts/PingFang.ttc',       # macOS
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',  # Linux
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',  # Linux
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont('Chinese', fp))
                _font_registered = True
                return
            except:
                continue
    # Fallback：不注册，用默认字体（中文可能显示不全）
    _font_registered = True


def generate_report_pdf(report: dict, advice: dict = None) -> bytes:
    """生成诊断报告 PDF，返回 bytes"""
    _ensure_font()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    font_name = 'Chinese' if _font_registered else 'Helvetica'

    title_style = ParagraphStyle('Title_CN', parent=styles['Title'], fontName=font_name, fontSize=18)
    h2_style = ParagraphStyle('H2_CN', parent=styles['Heading2'], fontName=font_name, fontSize=14)
    body_style = ParagraphStyle('Body_CN', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=16)
    small_style = ParagraphStyle('Small_CN', parent=styles['Normal'], fontName=font_name, fontSize=9, textColor=colors.grey)

    elements = []

    # 标题
    elements.append(Paragraph('铭曦 · 薪酬诊断报告', title_style))
    elements.append(Spacer(1, 10*mm))

    # 健康分
    score = report.get('health_score', 0)
    elements.append(Paragraph(f'综合健康度：{score} 分', h2_style))
    elements.append(Spacer(1, 5*mm))

    # 核心发现
    findings = report.get('key_findings', [])
    if findings:
        elements.append(Paragraph('核心发现', h2_style))
        for f in findings:
            priority = f.get('priority', '')
            text = f.get('text', '')
            elements.append(Paragraph(f'[{priority}] {text}', body_style))
        elements.append(Spacer(1, 8*mm))

    # 各模块摘要
    modules = report.get('modules', {})
    module_names = {
        'external_competitiveness': '外部竞争力',
        'internal_equity': '内部公平性',
        'fix_variable_ratio': '薪酬结构',
        'pay_performance': '绩效关联',
        'labor_cost': '人工成本',
    }

    for key, name in module_names.items():
        mod = modules.get(key, {})
        if not mod:
            continue

        elements.append(Paragraph(name, h2_style))

        if key == 'external_competitiveness':
            cr = mod.get('overall_cr', '—')
            below = mod.get('total_below_p25', 0)
            elements.append(Paragraph(f'整体 CR: {cr}，低于 P25 人数: {below}', body_style))

        elif key == 'internal_equity':
            high = mod.get('high_dispersion_count', 0)
            elements.append(Paragraph(f'离散度偏高的层级数: {high}', body_style))

        elif key == 'pay_performance':
            gap = mod.get('a_vs_b_gap_pct', '—')
            ratio = mod.get('a_vs_c_ratio', '—')
            elements.append(Paragraph(f'A/B 薪酬差距: {gap}%，A/C 薪酬倍数: {ratio}', body_style))

        elif key == 'fix_variable_ratio':
            fix = mod.get('overall_fix_pct', '—')
            elements.append(Paragraph(f'整体固浮比: {fix}:{100 - (fix or 0)}', body_style))

        elif key == 'labor_cost':
            kpi = mod.get('kpi', {})
            cost = kpi.get('total_cost_wan', '—')
            hc = kpi.get('headcount', '—')
            elements.append(Paragraph(f'年度总人工成本: {cost}万，在职人数: {hc}', body_style))

        elements.append(Spacer(1, 6*mm))

    # 诊断建议
    if advice and advice.get('advice'):
        elements.append(Paragraph('诊断建议', h2_style))
        for a in advice['advice']:
            priority = a.get('priority', '')
            title = a.get('title', '')
            detail = a.get('detail', '')
            elements.append(Paragraph(f'[{priority}] {title}', body_style))
            elements.append(Paragraph(detail, small_style))
            elements.append(Spacer(1, 3*mm))

        if advice.get('closing'):
            elements.append(Spacer(1, 3*mm))
            elements.append(Paragraph(advice['closing'], body_style))

    # 页脚
    elements.append(Spacer(1, 15*mm))
    elements.append(Paragraph('— 铭曦薪酬诊断系统 · Sparky AI 生成 —', small_style))

    doc.build(elements)
    return buffer.getvalue()
