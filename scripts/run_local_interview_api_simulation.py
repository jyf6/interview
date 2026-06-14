import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.interview_agent_service import (
    InterviewAgentService,
    InterviewOpeningResult,
    InterviewRouteResult,
    InterviewStageDetectionResult,
)


STAGE_NAMES = {
    "S1": "童年底色",
    "S2": "青春启蒙",
    "S3": "事业起步与初心",
    "S4": "关键转折与破局",
    "S5": "巅峰与至暗",
    "S6": "平衡与取舍",
    "S7": "当下与未来传承",
    "unclear": "未识别",
}

QUESTIONS = {
    "S1": {
        1: "您小时候成长在怎样的家庭环境中，父母日常的教育方式是什么样的？",
        2: "回想童年，您当时是怎样的性格，是懂事内敛还是活泼爱闯的类型？",
        3: "小时候您最热衷做什么事，有没有哪件事能让您全身心投入？",
        4: "除了家人之外，老师、邻里或是小伙伴里，有没有人对您影响很深？",
        5: "童年里有没有一件印象深刻的小事，如今回头看，悄悄改变了您的想法或性格？",
    },
    "S2": {
        1: "回望少年到青年的这段时光，整体给您留下了怎样的印象？",
        2: "中学到大学阶段，您对未来人生有着怎样的想象和期待？",
        3: "当年为什么会选择就读这个专业或这所大学，背后有哪些考量？",
        4: "这段时光里，有没有哪位老师、同学或是朋友，对您的影响特别大？",
        5: "青春期有没有哪一段经历，让您第一次对世界、对自己有了新的认识？",
        6: "您还记得第一次靠自己的能力赚钱是什么时候吗，当时有着怎样的感受？",
    },
    "S3": {
        1: "刚毕业踏入社会的时候，您对自己的人生有着怎样的规划？",
        2: "您的第一份工作是什么样的，当时的工作状态和收入情况如何？",
        3: "当初为什么会选择进入现在这个行业，是偶然还是早有准备？",
        4: "刚打拼的那些年，遇到过哪些让您印象深刻的困难和挑战？",
        5: "这段时期有没有哪位领导、同事或是伙伴，对您的成长帮助很大？",
        6: "那时候您对“成功”的定义是什么，和现在相比有哪些不同？",
    },
    "S4": {
        1: "您人生中最重要的一次职业转折是什么时候，当时面临着怎样的选择？",
        2: "做出这个重大决定的时候，您内心经历了哪些挣扎和考量？",
        3: "有没有一个清晰的时刻，让您觉得“事业终于要走上正轨了”？",
        4: "为了实现这次突破，您付出了哪些常人难以想象的努力？",
        5: "这段时期有没有哪位贵人或是对手，对您的事业发展起到了关键作用？",
        6: "现在回头看，这次转折对您的整个人生意味着什么？",
    },
    "S5": {
        1: "事业发展到现在，您觉得最有成就感、最让您骄傲的时刻是什么时候？",
        2: "有没有哪一次危机或是失败，让您差点放弃自己坚持多年的事业？",
        3: "面对巨大的成功和荣誉时，您有没有过迷茫、膨胀或是焦虑的时刻？",
        4: "经历过巅峰和低谷之后，您对“成功”的理解发生了哪些本质的变化？",
        5: "这段最艰难的日子里，是什么力量支撑着您一步步走了过来？",
        6: "从这些经历中，您总结出的最深刻的人生道理是什么？",
    },
    "S6": {
        1: "这么多年全身心投入事业，您觉得对家人有哪些难以弥补的亏欠？",
        2: "您是如何在高强度的工作中，尽量平衡陪伴家人的时间的？",
        3: "有没有哪一个瞬间，让您突然觉得“为了事业忽略了太多重要的东西”？",
        4: "为了扛起家庭和事业的双重责任，您放弃了哪些自己的爱好和追求？",
        5: "在忙碌到几乎没有自我的日子里，您是如何找到属于自己的放松方式的？",
        6: "随着年龄的增长，您对“家庭”和“事业”的优先级排序有没有发生变化？",
    },
    "S7": {
        1: "如果把人生分成几个阶段，您会怎么评价自己走过的这半生？",
        2: "走到今天，您觉得自己人生中最大的遗憾和最大的圆满分别是什么？",
        3: "当事业已经取得一定成就之后，您开始思考的人生意义是什么？",
        4: "您已经或者正在做哪些事，想要把自己的经验和精神传承下去？",
        5: "走到人生这个阶段，您觉得人这一辈子最重要的到底是什么？",
    },
}

ANSWERS = {
    "S1": {
        1: "我小时候成长在一个普通但很重规矩的家庭，父母不太讲大道理，但会用行动要求我守信、勤快。",
        2: "童年的我比较懂事内敛，遇到事情习惯先观察，很少主动表达委屈。",
        3: "我小时候最喜欢拆装小东西，能一个人蹲半天研究为什么它能动。",
        4: "除了家人，小学班主任对我影响很深，他总鼓励我把想法说出来。",
        5: "有一次我把邻居家的工具修好了，那件小事让我第一次觉得自己能靠能力帮到别人。",
        9: "童年底色大概就是父母给我的踏实和老师给我的自信。",
    },
    "S2": {
        1: "少年到青年这段时光给我的印象是迷茫但有劲，很多东西都想试一试。",
        2: "中学到大学时，我希望以后能做点真正有价值的事业，不只是找一份安稳工作。",
        3: "当年选专业主要是觉得它更接近实际问题，也能让我尽早接触社会。",
        4: "大学里有一位老师对我影响很大，他让我明白视野比成绩更重要。",
        5: "大二有一次社会实践，让我第一次看到真实商业世界和书本完全不同。",
        6: "第一次靠自己赚钱是在大学做项目兼职，拿到钱时特别兴奋，也第一次感到独立。",
        9: "青春阶段最大的收获，是我开始知道自己想成为怎样的人。",
    },
    "S3": {
        1: "刚毕业时我其实规划很粗糙，只想着先活下来，再找机会做出点成绩。",
        2: "第一份工作很辛苦，收入不高，每天都在学怎么和客户、同事打交道。",
        3: "进入这个行业一半是偶然，一半是因为我发现它能解决真实需求。",
        4: "刚打拼那几年最大的困难是资源少、经验少，还要不断证明自己。",
        5: "有一位老领导帮我很多，他愿意让我承担难项目，也会指出我的问题。",
        6: "那时我觉得成功就是赚到钱、被认可，现在更看重长期价值和责任。",
        9: "事业起步阶段最重要的是让我学会了扛事。",
    },
    "S4": {
        1: "最重要的职业转折是在三十岁左右，我决定离开舒适岗位，自己带团队做新方向。",
        2: "做决定时很挣扎，怕失败、怕拖累家人，也怕错过唯一的窗口期。",
        3: "第一个大客户愿意长期合作的时候，我第一次觉得事业真的要走上正轨了。",
        4: "为了突破，我连续很久都在一线跑客户、改方案，很多晚上只睡几个小时。",
        5: "那段时间有个竞争对手逼着我升级能力，也有一位贵人帮我打开资源。",
        6: "现在看，那次转折让我从执行者变成了真正承担结果的人。",
        9: "破局阶段最重要的是让我敢于对选择负责。",
    },
    "S5": {
        1: "最骄傲的时刻是公司业务做到行业前列，团队也终于被外界认可。",
        2: "也有一次现金流危机，差点让我放弃坚持多年的事业。",
        3: "面对荣誉时我确实膨胀过，也焦虑过，怕自己守不住。",
        4: "经历高峰和低谷后，我觉得成功不只是赢，而是能不能长期稳住价值。",
        5: "最难的时候，是团队和家人的信任支撑着我一步步走出来。",
        6: "最深的人生道理是不能只看眼前输赢，人要有底线，也要有耐心。",
        9: "巅峰和低谷让我知道人不能被掌声定义。",
    },
    "S6": {
        1: "这些年对家人最大的亏欠，是很多重要时刻我都不在场。",
        2: "后来我会提前留出固定时间陪家人，哪怕很忙也尽量不取消。",
        3: "孩子有一次说习惯了我不在家，那一刻我很受触动。",
        4: "为了家庭和事业，我放弃了很多自己的兴趣，也很少真正放松。",
        5: "后来我开始通过散步、读书和短暂独处找回一点自己的节奏。",
        6: "年龄越大，我越觉得家庭是底盘，事业应该服务于更好的生活。",
        9: "平衡与取舍让我学会不要把亲近的人放到最后。",
    },
    "S7": {
        1: "如果分阶段看，前半生是积累和冲刺，后半段更像是理解和沉淀。",
        2: "最大的遗憾是陪伴家人太少，最大的圆满是没有放弃自己的初心。",
        3: "事业有成后，我开始思考怎样让经验帮助更多年轻人少走弯路。",
        4: "我正在培养团队里的年轻人，也想把自己的经历整理成可传承的方法。",
        5: "走到现在，我觉得人这一辈子最重要的是守住良心，也把价值留给别人。",
        9: "最后想留给后辈一句话：走得快很重要，但知道为什么出发更重要。",
    },
}

EXTENDED_DONE: set[str] = set()
EXTENSION_ANSWERS = {
    "S1": "现在回头看，那种家庭氛围确实让我后来做事比较谨慎，也很在意承诺，很多选择都会先想清楚后果。",
    "S2": "那段经历让我开始意识到，人不能只看眼前的成绩，还要知道自己真正想走到哪里。",
    "S3": "刚工作那几年给我的影响很大，它让我知道很多事情不能等条件都成熟了才开始，必须边做边学。",
    "S4": "那次转折之后，我做决定会更看长期价值，也更能接受短期的不确定和压力。",
    "S5": "经历过高峰和低谷以后，我不太会被一时的掌声影响了，也更愿意把底线和长期信任放在前面。",
    "S6": "家庭这部分对我的影响很深，它提醒我不能只顾着往前冲，也要回头看看身边的人是否被我落下了。",
    "S7": "走到现在，我更希望自己的经历能给年轻人一些参考，让他们少走一点弯路，也更早明白什么最重要。",
}
EXTENSION_ANSWER_TEXTS = set(EXTENSION_ANSWERS.values())


async def fake_icebreaker(self, **kwargs):
    return InterviewOpeningResult(reply="我们可以从您的童年底色慢慢聊起。", response_source="none")


async def fake_detect(self, *, user_message: str):
    return InterviewStageDetectionResult(stage_code="unclear", stage_name="未识别", judgment_reason="接口模拟固定不抢阶段")


def stage_from_description(stage_description: str) -> str:
    match = re.search(r"S[1-7]", stage_description)
    return match.group(0) if match else "S1"


async def fake_route(self, *, user_message, recent_messages, stage_description, remaining_rounds):
    stage_id = stage_from_description(stage_description)
    if (
        stage_id not in EXTENDED_DONE
        and "我们开始" not in user_message
        and user_message not in EXTENSION_ANSWER_TEXTS
        and "阶段最大的收获" not in user_message
    ):
        EXTENDED_DONE.add(stage_id)
        return InterviewRouteResult(
            route="extended_interview",
            emotion_type="none",
            needs_emotional_support=False,
            confidence=1,
            reason="本地接口模拟：每个阶段触发一次扩展追问",
            round_decrement=0,
        )
    return InterviewRouteResult(
        route="normal_interview",
        emotion_type="none",
        needs_emotional_support=False,
        confidence=1,
        reason="本地接口模拟：继续主线",
        round_decrement=1,
    )


async def fake_reply(
    self,
    *,
    route,
    user_message,
    recent_messages,
    stage_description,
    remaining_rounds,
    completed_main_question_ids=None,
    session_id=None,
    interview_progress=None,
):
    stage_id = str((interview_progress or {}).get("stage_id") or stage_from_description(stage_description))
    if route.route == "extended_interview":
        return (
            "您刚刚说的这段经历很有代表性。现在回头看，它对您后来做选择的方式产生了什么影响？",
            "llm",
            None,
        )
    completed = set(completed_main_question_ids or [])
    next_id = next((qid for qid in QUESTIONS[stage_id] if qid not in completed), None)
    if next_id is None:
        return (
            json.dumps(
                {"question_id": "9", "question": f"关于{STAGE_NAMES[stage_id]}这个阶段，还有什么我没问到、但您特别想补充的吗？"},
                ensure_ascii=False,
            ),
            "llm",
            9,
        )
    return json.dumps({"question_id": str(next_id), "question": QUESTIONS[stage_id][next_id]}, ensure_ascii=False), "llm", next_id


InterviewAgentService.generate_icebreaker = fake_icebreaker
InterviewAgentService.detect_user_stage = fake_detect
InterviewAgentService.judge_turn_route = fake_route
InterviewAgentService.generate_reply_for_route = fake_reply


def extract_question(content: str) -> str:
    try:
        return json.loads(content).get("question") or content
    except Exception:
        return content


records = []
with TestClient(app) as client:
    start_resp = client.post("/api/v1/interview/dialog/start", json={})
    start_resp.raise_for_status()
    session_id = start_resp.json()["session_id"]
    action_resp = client.post("/api/v1/interview/dialog/actions", json={"session_id": session_id, "card_id": "start_interview"})
    action_resp.raise_for_status()

    user_input = "我们开始吧。"
    for turn in range(1, 90):
        request_body = {"session_id": session_id, "content": user_input}
        response = client.post("/api/v1/interview/dialog/text", json=request_body)
        response.raise_for_status()
        response_body = response.json()
        progress = response_body["state_interview"]
        stage_id = str(progress.get("stage_id") or "S1")
        active_id = progress.get("active_main_question_id")
        output = extract_question((response_body.get("message") or {}).get("content", ""))
        if active_id is None and not progress.get("completed"):
            next_input = EXTENSION_ANSWERS.get(stage_id, "这段经历对我后来的选择确实有很深的影响。")
        else:
            next_input = ANSWERS.get(stage_id, {}).get(active_id or 9, "我这部分补充完整了。")
        records.append(
            {
                "turn": turn,
                "request": request_body,
                "response_status": response.status_code,
                "output": output,
                "next_user_input": next_input,
                "state": {
                    "stage_id": stage_id,
                    "stage_name": STAGE_NAMES.get(stage_id, stage_id),
                    "active_main_question_id": active_id,
                    "completed_main_question_ids": progress.get("completed_main_question_ids"),
                    "awaiting_stage_completion": progress.get("awaiting_stage_completion"),
                    "completed": progress.get("completed"),
                },
            }
        )
        if progress.get("completed"):
            break
        user_input = next_input

json_path = Path("logs/local_interview_api_responses.json")
md_path = Path("logs/local_interview_api_responses.md")
json_path.write_text(json.dumps({"session_id": session_id, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")

lines = [
    "# 本地采访接口模拟记录",
    "",
    f"- session_id: `{session_id}`",
    f"- total_turns: {len(records)}",
    "- 接口：`POST /api/v1/interview/dialog/text`",
    "- 说明：每条“输出”均来自接口 response 的 `message.content` 字段解析结果。",
    "",
]
for item in records:
    state = item["state"]
    lines.append(f"## Turn {item['turn']} | {state['stage_id']} {state['stage_name']} | status {item['response_status']}")
    lines.append(f"输入：{item['request']['content']}")
    lines.append(f"输出：{item['output']}")
    lines.append(
        "状态："
        + json.dumps(
            {
                "active_main_question_id": state["active_main_question_id"],
                "completed_main_question_ids": state["completed_main_question_ids"],
                "awaiting_stage_completion": state["awaiting_stage_completion"],
                "completed": state["completed"],
            },
            ensure_ascii=False,
        )
    )
    lines.append("")
md_path.write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"session_id": session_id, "turns": len(records), "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))
