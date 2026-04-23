"""
HAY 引擎的最小化配置：只暴露 5 个 validation CSV 路径 + 职能常模路径。

替代了 student-value-backend/config.py（那边带了一堆学生场景的环境变量、
Supabase、邀请码、用量限制……都跟 JE 评估无关）。

CSV 文件直接放在本 package 的 validation_csv/ 目录下，不依赖外部环境变量。
"""
from pathlib import Path

# package 根目录（engine/）
_ENGINE_DIR = Path(__file__).resolve().parent
_CSV_DIR = _ENGINE_DIR / 'validation_csv'


class _Config:
    @property
    def KH_VALIDATION_CSV_PATH(self) -> str:
        return str(_CSV_DIR / 'knowhow报错底表.csv')

    @property
    def PS_VALIDATION_CSV_PATH(self) -> str:
        return str(_CSV_DIR / 'PS报错底表.csv')

    @property
    def ACC_VALIDATION_CSV_PATH(self) -> str:
        return str(_CSV_DIR / 'ACC报错底表.csv')

    @property
    def PS_KH_VALIDATION_CSV_PATH(self) -> str:
        return str(_CSV_DIR / 'KH和PS报错底表.csv')

    @property
    def PROFILE_NORM_CSV_PATH(self) -> str:
        return str(_CSV_DIR / '职能对应岗位特性表.csv')

    # 学生版还有 SALARY_CSV_PATH，JE 工具不用薪酬表（薪酬留给"薪酬设计"工具）。
    # 但有些代码可能还引用，留个空值，触发时再具体处理。
    @property
    def SALARY_CSV_PATH(self) -> str:
        return str(_CSV_DIR / '薪酬数据底表.csv')


config = _Config()
