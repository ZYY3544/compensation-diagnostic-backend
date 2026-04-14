-- 铭曦数据持久化 schema（Supabase / Postgres）
-- 执行方式：在 Supabase SQL Editor 里粘贴执行

-- ====== users ======
create table if not exists users (
  user_id text primary key,
  org_name text,
  role text,
  created_at timestamptz default now()
);

-- ====== data_snapshots ======
-- 一次上传的数据快照，包含原始解析 + 清洗结果 + 映射关系 + 全量分析结果
create table if not exists data_snapshots (
  snapshot_id text primary key,
  user_id text references users(user_id) on delete cascade,
  uploaded_at timestamptz default now(),
  raw_excel_path text,
  parse_result jsonb,
  cleaned_employees jsonb,        -- 清洗后员工数据
  employees_original jsonb,       -- 原始员工数据（清洗前快照）
  grade_mapping jsonb,            -- 公司职级 → 标准 Level
  func_mapping jsonb,             -- 部门/族 → 标准职能
  full_analysis_json jsonb,       -- 全量分析结果（按维度聚合）
  analyzed_at timestamptz,        -- 分析时间戳；数据变更需清空
  interview_notes jsonb,          -- 访谈纪要
  -- 中间状态（供 wizard 过程使用）
  code_results jsonb,
  field_map jsonb,
  column_names jsonb,
  grades_list jsonb,
  mutations jsonb,
  cleansed_excel_path text,
  status text default 'draft'     -- draft | parsed | analyzed
);

create index if not exists idx_snapshot_user on data_snapshots(user_id, uploaded_at desc);

-- ====== conversations ======
create table if not exists conversations (
  conv_id text primary key,
  user_id text references users(user_id) on delete cascade,
  snapshot_id text references data_snapshots(snapshot_id) on delete set null,
  started_at timestamptz default now(),
  title text,
  type text,  -- diagnosis | quick | follow_up
  messages jsonb default '[]'::jsonb,
  status text default 'active'
);

create index if not exists idx_conv_user on conversations(user_id, started_at desc);

-- ====== skill_invocations ======
create table if not exists skill_invocations (
  invocation_id text primary key,
  conv_id text references conversations(conv_id) on delete cascade,
  snapshot_id text references data_snapshots(snapshot_id) on delete set null,
  skill_key text,
  invoked_at timestamptz default now(),
  input_params jsonb,
  result_json jsonb,
  narrative_text text,
  render_artifacts jsonb,
  status text default 'success'
);

create index if not exists idx_inv_conv on skill_invocations(conv_id, invoked_at);

-- ====== 旧 session 兼容层（迁移期间用）======
-- 现有 in-memory sessions_store 的 dict 原样存 JSON，后续逐步拆到其他表
create table if not exists sessions_legacy (
  session_id text primary key,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  data jsonb                       -- 整个 session dict 原样存
);
