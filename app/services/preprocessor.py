"""
代码层预处理：对解析后的 Excel 数据跑所有确定性规则检测。
只做检测、标记，不做修正。修正由 pipeline 层根据 AI 判断结果执行。
"""
import statistics
from datetime import datetime, date


# ---------------------------------------------------------------------------
# 字段名映射（精确匹配，后续 AI 做模糊映射）
# ---------------------------------------------------------------------------
FIELD_ALIASES = {
    'position': ['岗位名称', '岗位', '职位', '职位名称', 'position', 'job_title'],
    'grade': ['职级', '层级', '级别', 'level', 'grade', '职等'],
    'monthly_salary': ['月度基本工资', '月薪', '基本工资', '月度工资', 'base_salary', 'monthly_salary'],
    'bonus': ['年终奖', '年终奖金', '奖金', 'bonus', 'annual_bonus'],
    'join_date': ['入司时间', '入职时间', '入职日期', '入司日期', 'join_date', 'hire_date'],
    'department': ['部门', '一级部门', '所属部门', 'department'],
    'supervisor': ['直属上级', '上级', '汇报对象', 'supervisor', 'manager', '上级工号'],
    'allowance': ['津贴', '月度津贴', '各种现金津贴', '补贴', 'allowance'],
    'age': ['年龄', 'age'],
    'performance': ['绩效', '绩效结果', '年度绩效结果', '绩效等级', 'performance'],
    'employee_id': ['工号', '员工工号', '姓名', '员工姓名', 'employee_id', 'name'],
}


def _resolve_field(column_names: list, standard_key: str) -> str | None:
    """在实际列名中查找标准字段对应的列名，精确匹配"""
    aliases = FIELD_ALIASES.get(standard_key, [])
    for alias in aliases:
        if alias in column_names:
            return alias
    return None


def _safe_float(value) -> float | None:
    """安全转换为 float，处理 None、字符串、逗号等"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace(',', '').replace('，', '').strip()
        if cleaned == '' or cleaned == '-':
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _safe_int(value) -> int | None:
    """安全转换为 int"""
    f = _safe_float(value)
    if f is None:
        return None
    return int(f)


def _parse_date(value) -> date | None:
    """尝试将各种格式的日期值解析为 date 对象"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y年%m月%d日', '%Y.%m.%d',
                '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _extract_grade_level(grade_value) -> int | None:
    """
    从职级值中提取数字等级。
    支持：Level 5, L5, P6, M3, 5级, 5 等格式。
    返回纯数字（如 5）。
    """
    if grade_value is None:
        return None
    s = str(grade_value).strip().upper()
    import re
    # 匹配 Level 5, L5, P6, M3, T9 等
    m = re.search(r'(?:LEVEL\s*|L|P|M|T)(\d+)', s)
    if m:
        return int(m.group(1))
    # 纯数字
    m = re.search(r'(\d+)', s)
    if m:
        return int(m.group(1))
    return None


def _group_by_grade(rows: list, grade_col: str, value_col: str) -> dict:
    """按职级分组，返回 {grade_value: [(row_number, numeric_value), ...]}"""
    groups = {}
    for row in rows:
        grade = row['data'].get(grade_col)
        val = _safe_float(row['data'].get(value_col))
        if grade is not None and val is not None and val > 0:
            grade_key = str(grade).strip()
            if grade_key not in groups:
                groups[grade_key] = []
            groups[grade_key].append((row['row_number'], val))
    return groups


def _group_by_grade_and_dept(rows: list, grade_col: str, dept_col: str, value_col: str) -> dict:
    """按职级+部门分组，返回 {(grade, dept): [(row_number, value), ...]}"""
    groups = {}
    for row in rows:
        grade = row['data'].get(grade_col)
        dept = row['data'].get(dept_col)
        val = _safe_float(row['data'].get(value_col))
        if grade is not None and dept is not None and val is not None and val > 0:
            key = (str(grade).strip(), str(dept).strip())
            if key not in groups:
                groups[key] = []
            groups[key].append((row['row_number'], val))
    return groups


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def run_code_checks(parsed_data: dict) -> dict:
    """
    对解析后的 Excel 数据跑所有确定性规则检测。

    输入: parsed_data = {
        'sheet1_data': [{'row_number': int, 'data': {...}}],
        'sheet2_data': {...},
        'column_names': [...]
    }

    输出: 包含各规则检测结果的 dict
    """
    rows = parsed_data.get('sheet1_data', [])
    columns = parsed_data.get('column_names', [])

    # 解析字段映射
    col = {}
    for key in FIELD_ALIASES:
        col[key] = _resolve_field(columns, key)

    result = {
        'critical_missing': [],       # 规则4
        'future_dates': [],           # 规则7
        'old_dates': [],              # 规则7
        'salary_outliers': [],        # 规则2
        'bonus_outliers': [],         # 规则3
        'needs_annualize': [],        # 规则1
        'possible_13th_overlap': [],  # 规则8
        'salary_inversions': [],      # 规则6
        'dispersion_alerts': [],      # 规则9
        'allowance_alerts': [],       # 规则10
        'age_grade_alerts': [],       # 规则12
        'high_bonus_suspects': [],    # 规则14
        'allowance_variance': [],     # 规则15
        'performance_values': [],     # 规则5（收集给AI）
        'unique_departments': [],     # 规则11（收集给AI）
        'data_summary': {},
        'sample_rows': [],
        'field_mapping': col,         # 字段映射结果，方便下游使用
    }

    if not rows:
        return result

    # -----------------------------------------------------------------------
    # 生成摘要和样本
    # -----------------------------------------------------------------------
    result['sample_rows'] = [r['data'] for r in rows[:5]]
    result['data_summary'] = _build_summary(rows, columns)

    # -----------------------------------------------------------------------
    # 收集绩效值和部门名称（供 AI 层使用）
    # -----------------------------------------------------------------------
    if col['performance']:
        perf_vals = set()
        for r in rows:
            v = r['data'].get(col['performance'])
            if v is not None:
                perf_vals.add(str(v).strip())
        result['performance_values'] = sorted(perf_vals)

    if col['department']:
        dept_vals = []
        for r in rows:
            v = r['data'].get(col['department'])
            if v is not None:
                dept_vals.append(str(v).strip())
        result['unique_departments'] = sorted(set(dept_vals))

    # -----------------------------------------------------------------------
    # 规则4：必填字段空值
    # -----------------------------------------------------------------------
    required_fields = ['position', 'grade', 'monthly_salary', 'bonus']
    for r in rows:
        for field_key in required_fields:
            actual_col = col.get(field_key)
            if actual_col is None:
                continue  # 整列不存在，不逐行标记
            val = r['data'].get(actual_col)
            if val is None or str(val).strip() == '':
                result['critical_missing'].append({
                    'row_number': r['row_number'],
                    'field': actual_col,
                    'value': None,
                    'issue': f'必填字段 [{actual_col}] 为空',
                })

    # -----------------------------------------------------------------------
    # 规则7：入司时间合理性
    # -----------------------------------------------------------------------
    if col['join_date']:
        today = date.today()
        cutoff_old = date(1980, 1, 1)
        for r in rows:
            raw = r['data'].get(col['join_date'])
            d = _parse_date(raw)
            if d is None:
                continue
            if d > today:
                result['future_dates'].append({
                    'row_number': r['row_number'],
                    'field': col['join_date'],
                    'value': str(d),
                    'issue': f'入司时间 {d} 晚于当前日期，疑似录入错误',
                })
            elif d < cutoff_old:
                result['old_dates'].append({
                    'row_number': r['row_number'],
                    'field': col['join_date'],
                    'value': str(d),
                    'issue': f'入司时间 {d} 早于1980年，疑似异常',
                })

    # -----------------------------------------------------------------------
    # 规则2：月薪异常值（按职级分组，偏离中位值 > 3倍）
    # -----------------------------------------------------------------------
    if col['grade'] and col['monthly_salary']:
        salary_groups = _group_by_grade(rows, col['grade'], col['monthly_salary'])
        for grade_key, members in salary_groups.items():
            if len(members) < 3:
                continue
            values = [v for _, v in members]
            med = statistics.median(values)
            if med <= 0:
                continue
            for row_num, val in members:
                ratio = val / med
                if ratio > 3 or ratio < 1 / 3:
                    result['salary_outliers'].append({
                        'row_number': row_num,
                        'field': col['monthly_salary'],
                        'value': val,
                        'issue': f'月薪 {val} 偏离同职级({grade_key})中位值 {med:.0f} 超过3倍 (比值={ratio:.2f})',
                        'grade': grade_key,
                        'median': med,
                        'ratio': round(ratio, 2),
                    })

    # -----------------------------------------------------------------------
    # 规则3：年终奖异常值（按职级分组，偏离中位值 > 3倍）
    # -----------------------------------------------------------------------
    if col['grade'] and col['bonus']:
        bonus_groups = _group_by_grade(rows, col['grade'], col['bonus'])
        for grade_key, members in bonus_groups.items():
            if len(members) < 3:
                continue
            values = [v for _, v in members]
            med = statistics.median(values)
            if med <= 0:
                continue
            for row_num, val in members:
                ratio = val / med
                if ratio > 3 or ratio < 1 / 3:
                    result['bonus_outliers'].append({
                        'row_number': row_num,
                        'field': col['bonus'],
                        'value': val,
                        'issue': f'年终奖 {val} 偏离同职级({grade_key})中位值 {med:.0f} 超过3倍 (比值={ratio:.2f})',
                        'grade': grade_key,
                        'median': med,
                        'ratio': round(ratio, 2),
                    })

    # -----------------------------------------------------------------------
    # 规则1：疑似需要年化（入司不满一年 + 年终奖低于同级中位值）
    # -----------------------------------------------------------------------
    if col['join_date'] and col['bonus'] and col['grade']:
        today = date.today()
        data_year = today.year  # 假定数据年度为当前年
        year_start = date(data_year, 1, 1)
        bonus_groups = _group_by_grade(rows, col['grade'], col['bonus'])
        grade_medians = {}
        for gk, members in bonus_groups.items():
            values = [v for _, v in members]
            if values:
                grade_medians[gk] = statistics.median(values)

        for r in rows:
            join = _parse_date(r['data'].get(col['join_date']))
            bonus_val = _safe_float(r['data'].get(col['bonus']))
            grade_val = r['data'].get(col['grade'])
            if join is None or bonus_val is None or grade_val is None:
                continue
            grade_key = str(grade_val).strip()
            # 入司时间在数据年度内 → 不满一年
            if join >= year_start and join <= today:
                med = grade_medians.get(grade_key)
                if med and med > 0 and bonus_val < med * 0.7:
                    months_worked = max(1, (today - join).days // 30)
                    result['needs_annualize'].append({
                        'row_number': r['row_number'],
                        'field': col['bonus'],
                        'value': bonus_val,
                        'issue': f'入司不满一年({join}，在职约{months_worked}个月)，年终奖 {bonus_val} 低于同级中位值 {med:.0f} 的70%，疑似需要年化',
                        'join_date': str(join),
                        'months_worked': months_worked,
                        'grade': grade_key,
                        'grade_median': med,
                    })

    # -----------------------------------------------------------------------
    # 规则6：上下级薪酬倒挂
    # -----------------------------------------------------------------------
    if col['supervisor'] and col['monthly_salary'] and col['employee_id']:
        # 构建员工ID → 月薪映射
        id_salary = {}
        id_row = {}
        for r in rows:
            eid = r['data'].get(col['employee_id'])
            sal = _safe_float(r['data'].get(col['monthly_salary']))
            if eid is not None and sal is not None:
                eid_key = str(eid).strip()
                id_salary[eid_key] = sal
                id_row[eid_key] = r['row_number']

        for r in rows:
            sup = r['data'].get(col['supervisor'])
            sub_sal = _safe_float(r['data'].get(col['monthly_salary']))
            sub_id = r['data'].get(col['employee_id'])
            if sup is None or sub_sal is None:
                continue
            sup_key = str(sup).strip()
            sup_sal = id_salary.get(sup_key)
            if sup_sal is not None and sub_sal > sup_sal:
                result['salary_inversions'].append({
                    'row_number': r['row_number'],
                    'field': col['monthly_salary'],
                    'value': sub_sal,
                    'issue': f'下级(行{r["row_number"]})月薪 {sub_sal} > 上级({sup_key}, 行{id_row.get(sup_key, "?")})月薪 {sup_sal}，存在薪酬倒挂',
                    'subordinate_id': str(sub_id) if sub_id else None,
                    'supervisor_id': sup_key,
                    'supervisor_salary': sup_sal,
                })

    # -----------------------------------------------------------------------
    # 规则8：13薪与年终奖交叉校验
    # -----------------------------------------------------------------------
    if col['monthly_salary'] and col['bonus']:
        for r in rows:
            salary = _safe_float(r['data'].get(col['monthly_salary']))
            bonus = _safe_float(r['data'].get(col['bonus']))
            if salary is None or bonus is None or salary <= 0:
                continue
            # 检查年终奖是否约等于 13薪 + N倍月薪
            remainder = bonus - salary  # 减去一个月（13薪部分）
            if remainder > 0 and salary > 0:
                n = remainder / salary
                # 如果 n 非常接近整数（误差 < 10%），且原始 bonus/salary 也接近整数+1
                total_ratio = bonus / salary
                int_ratio = round(total_ratio)
                if int_ratio >= 2 and abs(total_ratio - int_ratio) < 0.1:
                    result['possible_13th_overlap'].append({
                        'row_number': r['row_number'],
                        'field': col['bonus'],
                        'value': bonus,
                        'issue': f'年终奖 {bonus} ≈ {int_ratio} 倍月薪 {salary}（比值={total_ratio:.2f}），疑似包含13薪',
                        'monthly_salary': salary,
                        'ratio': round(total_ratio, 2),
                    })

    # -----------------------------------------------------------------------
    # 规则9：同级同部门离散异常（最高/最低 > 2.5）
    # -----------------------------------------------------------------------
    if col['grade'] and col['department'] and col['monthly_salary']:
        gd_groups = _group_by_grade_and_dept(
            rows, col['grade'], col['department'], col['monthly_salary']
        )
        for (grade_key, dept_key), members in gd_groups.items():
            if len(members) < 2:
                continue
            values = [v for _, v in members]
            min_val = min(values)
            max_val = max(values)
            if min_val <= 0:
                continue
            ratio = max_val / min_val
            if ratio > 2.5:
                for row_num, val in members:
                    if val == max_val or val == min_val:
                        result['dispersion_alerts'].append({
                            'row_number': row_num,
                            'field': col['monthly_salary'],
                            'value': val,
                            'issue': f'同职级({grade_key})同部门({dept_key})内最高薪 {max_val:.0f} / 最低薪 {min_val:.0f} = {ratio:.2f}，离散度超过2.5',
                            'grade': grade_key,
                            'department': dept_key,
                            'max_salary': max_val,
                            'min_salary': min_val,
                            'dispersion_ratio': round(ratio, 2),
                        })

    # -----------------------------------------------------------------------
    # 规则10：津贴超30%月薪
    # -----------------------------------------------------------------------
    if col['allowance'] and col['monthly_salary']:
        for r in rows:
            allowance = _safe_float(r['data'].get(col['allowance']))
            salary = _safe_float(r['data'].get(col['monthly_salary']))
            if allowance is None or salary is None or salary <= 0:
                continue
            if allowance > salary * 0.3:
                result['allowance_alerts'].append({
                    'row_number': r['row_number'],
                    'field': col['allowance'],
                    'value': allowance,
                    'issue': f'津贴 {allowance} 超过月薪 {salary} 的30%（占比 {allowance / salary * 100:.1f}%），异常偏高',
                    'monthly_salary': salary,
                    'ratio': round(allowance / salary, 2),
                })

    # -----------------------------------------------------------------------
    # 规则12：年龄职级不匹配
    # -----------------------------------------------------------------------
    if col['age'] and col['grade']:
        for r in rows:
            age = _safe_int(r['data'].get(col['age']))
            grade_raw = r['data'].get(col['grade'])
            if age is None or grade_raw is None:
                continue
            level = _extract_grade_level(grade_raw)
            if level is None:
                continue
            if age < 22 and level >= 5:
                result['age_grade_alerts'].append({
                    'row_number': r['row_number'],
                    'field': col['age'],
                    'value': age,
                    'issue': f'年龄 {age} 岁（< 22）但职级 {grade_raw}（Level {level} ≥ 5），年龄职级不匹配',
                    'grade': str(grade_raw),
                    'grade_level': level,
                })
            elif age > 55 and level <= 3:
                result['age_grade_alerts'].append({
                    'row_number': r['row_number'],
                    'field': col['age'],
                    'value': age,
                    'issue': f'年龄 {age} 岁（> 55）但职级 {grade_raw}（Level {level} ≤ 3），年龄职级不匹配',
                    'grade': str(grade_raw),
                    'grade_level': level,
                })

    # -----------------------------------------------------------------------
    # 规则14：疑似含长期激励（年终奖 > 同级中位值 5倍 + 高职级）
    # -----------------------------------------------------------------------
    if col['grade'] and col['bonus']:
        bonus_groups = _group_by_grade(rows, col['grade'], col['bonus'])
        grade_medians_bonus = {}
        for gk, members in bonus_groups.items():
            values = [v for _, v in members]
            if values:
                grade_medians_bonus[gk] = statistics.median(values)

        for r in rows:
            bonus_val = _safe_float(r['data'].get(col['bonus']))
            grade_raw = r['data'].get(col['grade'])
            if bonus_val is None or grade_raw is None:
                continue
            grade_key = str(grade_raw).strip()
            level = _extract_grade_level(grade_raw)
            med = grade_medians_bonus.get(grade_key)
            if med and med > 0 and level is not None:
                ratio = bonus_val / med
                if ratio > 5 and level >= 5:
                    result['high_bonus_suspects'].append({
                        'row_number': r['row_number'],
                        'field': col['bonus'],
                        'value': bonus_val,
                        'issue': f'年终奖 {bonus_val} 是同级({grade_key})中位值 {med:.0f} 的 {ratio:.1f} 倍，且职级较高(Level {level})，疑似包含长期激励',
                        'grade': grade_key,
                        'grade_level': level,
                        'median': med,
                        'ratio': round(ratio, 2),
                    })

    # -----------------------------------------------------------------------
    # 规则15：津贴波动大，疑似实报实销（同级别变异系数 > 0.5）
    # -----------------------------------------------------------------------
    if col['grade'] and col['allowance']:
        allowance_groups = _group_by_grade(rows, col['grade'], col['allowance'])
        for grade_key, members in allowance_groups.items():
            if len(members) < 3:
                continue
            values = [v for _, v in members]
            mean_val = statistics.mean(values)
            if mean_val <= 0:
                continue
            try:
                stdev_val = statistics.stdev(values)
            except statistics.StatisticsError:
                continue
            cv = stdev_val / mean_val
            if cv > 0.5:
                for row_num, val in members:
                    result['allowance_variance'].append({
                        'row_number': row_num,
                        'field': col['allowance'],
                        'value': val,
                        'issue': f'同职级({grade_key})津贴变异系数 {cv:.2f} > 0.5（均值={mean_val:.0f}，标准差={stdev_val:.0f}），疑似混入实报实销',
                        'grade': grade_key,
                        'cv': round(cv, 2),
                        'group_mean': round(mean_val, 2),
                        'group_stdev': round(stdev_val, 2),
                    })

    return result


# ---------------------------------------------------------------------------
# 辅助：生成数据统计摘要
# ---------------------------------------------------------------------------
def _build_summary(rows: list, columns: list) -> dict:
    """生成统计摘要（给 AI 用）"""
    summary = {
        'total_rows': len(rows),
        'columns': [],
    }

    for col_name in columns:
        col_values = [r['data'].get(col_name) for r in rows if r['data'].get(col_name) is not None]
        col_summary = {
            'name': col_name,
            'non_null_count': len(col_values),
            'null_count': len(rows) - len(col_values),
            'unique_count': len(set(str(v) for v in col_values)),
        }

        numeric_values = []
        for v in col_values:
            f = _safe_float(v)
            if f is not None:
                numeric_values.append(f)

        if numeric_values:
            col_summary['min'] = min(numeric_values)
            col_summary['max'] = max(numeric_values)
            col_summary['mean'] = round(sum(numeric_values) / len(numeric_values), 2)
            if len(numeric_values) >= 2:
                col_summary['median'] = statistics.median(numeric_values)

        summary['columns'].append(col_summary)

    return summary
