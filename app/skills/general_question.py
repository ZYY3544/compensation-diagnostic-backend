"""
Skill: 薪酬知识问答

轻模式（兜底）。纯 AI 回答，不需要数据，不需要分析引擎，不出右侧工作台。
其他 skill 都匹配不上时走这里。
"""

SKILL = {
    "key": "general_question",
    "display_name": "薪酬知识问答",
    "mode": "light",
    "chip_label": None,  # 不在首屏展示

    "triggers": [
        r"什么是",
        r"是什么意思",
        r"怎么理解",
        r"解释一下",
        r"什么叫",
        # 注意：这个 skill 同时也是兜底，当其他 skill 都匹配不上时走这里
    ],

    "preconditions": [],  # 无前置条件

    "input_params": {
        "question": {
            "type": "string",
            "required": True,
            "resolve": "用户的原始消息",
        },
    },

    "engine": "none",  # 不需要分析引擎

    "narrative_prompt": "prompts/general_qa.txt",

    "render_components": [],  # 无右侧工作台，Sparky 在对话里直接回答
}
