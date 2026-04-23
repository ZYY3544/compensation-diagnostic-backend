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

    # AUTH_DISABLED 模式下，require_auth 会注入虚拟的 admin 身份；
    # 这里要保证对应的 workspace + user 真实存在，否则任何带外键的写入都会挂。
    if os.getenv('AUTH_DISABLED', '').lower() == 'true':
        _seed_admin()


def _seed_admin():
    """幂等：如果不存在就建 ws_admin + usr_admin。"""
    from app.core.models import User, Workspace
    from app.core.auth import ADMIN_USER_ID, ADMIN_WORKSPACE_ID, hash_password

    db = SessionLocal()
    try:
        if not db.query(Workspace).filter_by(id=ADMIN_WORKSPACE_ID).first():
            db.add(Workspace(id=ADMIN_WORKSPACE_ID, name='Admin Workspace', company_name='铭曦'))
            db.flush()
            print(f'[db] seeded admin workspace: {ADMIN_WORKSPACE_ID}')
        if not db.query(User).filter_by(id=ADMIN_USER_ID).first():
            db.add(User(
                id=ADMIN_USER_ID,
                email='admin@mingxi.local',
                password_hash=hash_password('disabled-in-dev-mode'),
                display_name='管理员',
                workspace_id=ADMIN_WORKSPACE_ID,
            ))
            print(f'[db] seeded admin user: {ADMIN_USER_ID}')
        db.commit()
    except Exception as e:
        db.rollback()
        print(f'[db] _seed_admin failed: {e}')
    finally:
        db.close()
