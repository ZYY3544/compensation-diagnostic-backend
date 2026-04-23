"""
薪酬诊断工具的标识目录。

物理代码当前仍在 app/engine/、app/skills/、app/services/、app/agents/、app/api/ 下，
未做整体迁移以避免破坏稳定功能。后续如有重构需要可分模块逐步迁入。

工具 key: 'diagnosis'
入口路由: /api/sessions, /api/upload, /api/chat, /api/report, /api/skill 等
"""

TOOL_KEY = 'diagnosis'
DISPLAY_NAME = '薪酬诊断'
