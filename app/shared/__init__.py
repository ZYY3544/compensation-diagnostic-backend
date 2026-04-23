"""
跨工具共享层。

预期未来放置（按需迁入）：
- shared/agents/      LLM 客户端、Sparky 基类、意图识别
- shared/data/        Workspace 级数据资产（员工、岗位、测评、访谈）
- shared/skills/      skill registry + schema
- shared/market_data  市场薪酬数据（全局共用）
- shared/pdf_exporter PDF 导出基础设施

迁入原则：
- 一次只迁一块，迁完更新所有 caller，本地跑通再 commit
- 不要为了"看起来整齐"提前迁入；让真实的"第二个工具的需求"驱动迁移
"""
