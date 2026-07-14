from app.prompts.interview_prompts import STAGE_MAIN_QUESTION_IDS

MAIN_QUESTION_IDS = tuple(
    range(1, max(max(ids) for ids in STAGE_MAIN_QUESTION_IDS.values()) + 1)
)
INTERVIEW_STAGES = [
    {
        "id": "S1",
        "rounds": 4,
        "name": "童年时光",
        "coverage": "成长环境、家庭处境、日常生活、难忘事件、家人玩伴、性格影响或心底感触。",
        "boundary": "不追玩具、食物、天气等碎片细节；不过早进入成年事业、婚姻和晚年总结。",
        "followup": "出现可扩展素材时单步扩展；积极性下降时停止扩展支线并回到当前阶段主问题。",
    },
    {
        "id": "S2",
        "rounds": 4,
        "name": "青春岁月",
        "coverage": "求学、离家或初入社会的处境，学习工作主线，关键事件，同伴师长，成长和得失。",
        "boundary": "不追无关琐碎细节；不过早进入中年责任和晚年总结。",
        "followup": "出现可扩展素材时单步扩展；积极性下降时停止扩展支线并回到当前阶段主问题。",
    },
    {
        "id": "S3",
        "rounds": 4,
        "name": "人生转折",
        "coverage": "成家、择业、重大选择、责任、困境低谷、压力来源、支持分担、改变收获和遗憾。",
        "boundary": "追问要温和；遇到回避或沉重内容转向支撑、温暖和后来变化，不深挖痛苦细节。",
        "followup": "出现可扩展素材时单步扩展；积极性下降时停止扩展支线并回到当前阶段主问题。",
    },
    {
        "id": "S4",
        "rounds": 4,
        "name": "岁月阅历",
        "coverage": "当前生活环境和处境，日常节奏，代表性事件，家人老友邻里，心态变化和生活感悟。",
        "boundary": "问题更平和、收拢，不再开启过大的新事件。",
        "followup": "出现可扩展素材时单步扩展；积极性下降时停止扩展支线并回到当前阶段主问题。",
    },
    {
        "id": "S5",
        "rounds": 4,
        "name": "收尾总结",
        "coverage": "整个人生的主线，重要经历或转折，感谢或牵挂的人，人生总结、释怀、遗憾和留给家人的话。",
        "boundary": "不再开启新的阶段性故事。",
        "followup": "出现可扩展素材时围绕总结、感谢、遗憾、释怀单步扩展；积极性下降时温情收尾。",
    },
]
INTERVIEW_STAGE_OVERRIDES = {
    "S1": {
        "rounds": 5,
        "name": "童年底色",
        "coverage": "0-12岁家庭环境、父母教育、童年性格、热衷之事、童年重要人物和影响性格价值观的小事。",
        "boundary": "不追问中学大学、正式工作、创业、职业巅峰、家庭事业取舍和人生传承等后续阶段内容。",
        "followup": "围绕童年事件和人物单步扩展，重点追问内心感受、认知变化和长期性格影响。",
    },
    "S2": {
        "rounds": 6,
        "name": "青春启蒙",
        "coverage": "13-20岁中学到大学阶段的整体印象、人生期待、专业/大学选择、重要师友、自我认知变化和第一次赚钱。",
        "boundary": "不提前进入正式职业起步、重大职业转折、事业巅峰危机和家庭事业取舍。",
        "followup": "围绕青春伏笔单步扩展，重点追问三观成型、选择挣扎、精神影响和成年后选择的源头。",
    },
    "S3": {
        "rounds": 6,
        "name": "事业起步与初心",
        "coverage": "20-30岁职场前10年的毕业规划、第一份工作、收入状态、行业选择、早年困难、职场贵人和早期成功观。",
        "boundary": "不提前进入重大破局、事业巅峰低谷和家庭事业长期取舍。",
        "followup": "围绕职业起步单步扩展，重点追问生存状态、现实冲击、能力破局、初心和职业基因。",
    },
    "S4": {
        "rounds": 6,
        "name": "关键转折与破局",
        "coverage": "30-35岁职业成长期的重要职业转折、重大决定、内心挣扎、事业正轨、突破努力、贵人对手和人生意义。",
        "boundary": "不把普通第一份工作归入本阶段；不把成熟期巅峰危机或家庭亏欠作为主线展开。",
        "followup": "围绕关键一跃单步扩展，重点追问临界状态、风险评估、破局动作、至暗时刻和格局跃升。",
    },
    "S5": {
        "rounds": 6,
        "name": "巅峰与至暗",
        "coverage": "35-45岁职业成熟期的成就感、重大危机、成功荣誉后的心态、成功观变化、低谷支撑和人生道理。",
        "boundary": "不再展开职业起步和普通转折；家庭陪伴亏欠应记录后交给平衡与取舍阶段。",
        "followup": "围绕巅峰与低谷单步扩展，重点追问人性考验、自我重建和人生顿悟；敏感内容点到为止。",
    },
}
for stage in INTERVIEW_STAGES:
    override = INTERVIEW_STAGE_OVERRIDES.get(stage["id"])
    if override:
        stage.update(override)
INTERVIEW_STAGES.extend(
    [
        {
            "id": "S6",
            "rounds": 6,
            "name": "平衡与取舍",
            "coverage": "30-50岁全周期中的家庭事业冲突、家人亏欠、陪伴平衡、重要忽略瞬间、爱好牺牲、自我放松和优先级变化。",
            "boundary": "不把单纯事业危机或职业破局作为主线展开；重点始终落在家庭、责任、取舍和和解。",
            "followup": "围绕家庭事业平衡单步扩展，重点追问愧疚、取舍、家人理解、和解过程和幸福定义。",
        },
        {
            "id": "S7",
            "rounds": 5,
            "name": "当下与未来传承",
            "coverage": "45-50岁展望期的人生复盘、遗憾圆满、意义探寻、经验精神传承和最终人生答案。",
            "boundary": "这是最终升华阶段，不再开启新的大阶段故事。",
            "followup": "围绕意义和传承单步扩展，重点追问人生复盘、传承对象、后辈期待和最终答案。",
        },
    ]
)
INTERVIEW_STAGE_BY_ID = {stage["id"]: stage for stage in INTERVIEW_STAGES}
FIRST_INTERVIEW_STAGE = INTERVIEW_STAGES[0]["id"]
LAST_INTERVIEW_STAGE = INTERVIEW_STAGES[-1]["id"]
INTERVIEW_STAGE_IDS = [stage["id"] for stage in INTERVIEW_STAGES]
STAGE_STATUS_VALUES = {"not_started", "pending", "active", "completed"}
REMOVED_PROGRESS_FIELDS = {
    "remaining_rounds",
    "visited_stage_ids",
    "stage_name",
    "stage_order",
    "started_stage_name",
    "started_stage_order",
    "stage_plan",
    "stage_statuses",
}
STAGE_TASK_BY_REMAINING_ROUNDS = {
    4: (
        "本轮采访任务：环境与处境。下一问要覆盖这段时期的生活或工作环境、时代条件、家庭或个人处境，"
        "让用户先给出这段人生阶段的大致背景。"
    ),
    3: (
        "本轮采访任务：日常主线。下一问要覆盖这段时期平日主要做什么、日常节奏和主要生活状态。"
    ),
    2: (
        "本轮采访任务：关键事件。下一问要覆盖这段时期最有代表性的一件大事、转折、高光或困难。"
    ),
    1: (
        "本轮采访任务：人际与心境。下一问要覆盖这段时期身边重要的人、关系变化，"
        "以及这段时光带来的改变、收获、遗憾或整体心境。若用户已经讲清楚这些内容，就简短收束当前阶段并自然引到下一阶段。"
    ),
}
STAGE_SUPPLEMENT_TASK = (
    "本轮采访任务：当前阶段 1-8 号主问题已全部收集完成。"
    "暂不切换阶段，继续调用当前阶段主问题提示词，让模型输出编号 9 的补充询问，"
    "询问用户关于当前阶段还有没有没问到但想补充的内容。"
)
FINAL_STAGE_TASK = (
    "本轮采访任务：最终收尾。用户刚回答了人生总结或心境得失，"
    "下一句要温情感谢并结束采访，不要再提出新的问题。"
)
