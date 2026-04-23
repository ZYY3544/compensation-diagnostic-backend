"""
SQLAlchemy 引擎 + Session 配置。

DATABASE_URL 环境变量决定连哪个库：
  - 没设 → 本地 SQLite 文件 (data.db)，方便开发不依赖 Postgres
  - postgresql://...  → Render 上的 Postgres

每个 web 请求拿一个 db_session，请求结束 commit + close。
出错时 rollback。
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session


def _build_engine():
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        # 本地开发兜底：SQLite 文件
        url = 'sqlite:///data.db'
        print(f'[db] DATABASE_URL not set, using SQLite: {url}')
    else:
        # Render / Heroku 给的 postgres:// 老前缀，SQLAlchemy 2.x 要 postgresql://
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        print(f'[db] connecting to {url.split("@")[-1] if "@" in url else url}')

    # SQLite 单文件需要 check_same_thread=False 才能跨线程使用
    connect_args = {'check_same_thread': False} if url.startswith('sqlite') else {}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = _build_engine()
SessionLocal = scoped_session(sessionmaker(bind=engine, autocommit=False, autoflush=False))
Base = declarative_base()


def get_db():
    """Flask 视图里用：with get_db() as db: ..."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """启动时 create_all。生产环境后续可换 Alembic。"""
    # 导入所有 model 让 Base.metadata 知道它们
    from app.core import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print('[db] tables initialized')
