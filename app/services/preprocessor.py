def generate_data_summary(parsed_data):
    """Generate statistical summary for LLM input"""
    rows = parsed_data.get('sheet1_data', [])
    columns = parsed_data.get('column_names', [])

    summary = {
        'total_rows': len(rows),
        'columns': [],
    }

    for col in columns:
        col_values = [r['data'].get(col) for r in rows if r['data'].get(col) is not None]
        col_summary = {
            'name': col,
            'non_null_count': len(col_values),
            'null_count': len(rows) - len(col_values),
            'unique_count': len(set(str(v) for v in col_values)),
        }

        # Numeric stats
        numeric_values = []
        for v in col_values:
            try:
                numeric_values.append(float(v))
            except (ValueError, TypeError):
                pass

        if numeric_values:
            col_summary['min'] = min(numeric_values)
            col_summary['max'] = max(numeric_values)
            col_summary['mean'] = sum(numeric_values) / len(numeric_values)

        summary['columns'].append(col_summary)

    return summary
