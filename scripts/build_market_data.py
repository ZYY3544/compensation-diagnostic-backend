"""
一次性脚本：把 static/市场薪酬数据.xlsx 转成 static/market_data.json

运行时机：xlsx 被更新后跑一次。运行后产生的 JSON 会被 commit 进仓库，
Render 部署时直接读 JSON，不再依赖 openpyxl 加载市场数据这条慢路径。

用法：
    python3 scripts/build_market_data.py
"""
import json
import os
import sys

# 让脚本可以从仓库根目录跑（不依赖 PYTHONPATH）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl


def _safe_int(val) -> int:
    if val is None:
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def main():
    static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
    xlsx_path = os.path.join(static_dir, '市场薪酬数据.xlsx')
    json_path = os.path.join(static_dir, 'market_data.json')

    if not os.path.exists(xlsx_path):
        print(f'ERROR: xlsx not found: {xlsx_path}')
        sys.exit(1)

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else '' for h in next(rows_iter)]

    # JSON 不能用 tuple 当 key，存成 list of records，运行时再 reindex
    records = []
    for row_values in rows_iter:
        row = {h: v for h, v in zip(headers, row_values) if h}
        job_func = str(row.get('Job Function', '')).strip()
        hay = row.get('Hay职级')
        if not job_func or hay is None:
            continue
        records.append({
            'job_family': str(row.get('Job Family', '')).strip(),
            'job_function': job_func,
            'hay_grade': int(hay),
            'level': str(row.get('层级', '')).strip(),
            'base_p25': _safe_int(row.get('base_p25')),
            'base_p50': _safe_int(row.get('base_p50')),
            'base_p75': _safe_int(row.get('base_p75')),
            'bonus_p25': _safe_int(row.get('bonus_p25')),
            'bonus_p50': _safe_int(row.get('bonus_p50')),
            'bonus_p75': _safe_int(row.get('bonus_p75')),
            'ttc_p25': _safe_int(row.get('ttc_p25')),
            'ttc_p50': _safe_int(row.get('ttc_p50')),
            'ttc_p75': _safe_int(row.get('ttc_p75')),
        })

    wb.close()

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f'wrote {len(records)} rows → {json_path}')


if __name__ == '__main__':
    main()
