"""
银发传记 Demo - 集成测试脚本
===========================
两种路径全覆盖：
  路径 A: 开场白 → 直接开始采访 → 对话
  路径 B: 开场白 → 不知道怎么聊 → 选引导卡片 → 开始采访 → 对话

用法（先启动后端：python main.py）：
  venv/Scripts/python.exe test_integration.py
"""

import json
import sys
import httpx

BASE_URL = "http://127.0.0.1:8000"
USER_ID = "test_user_001"


def log(step: str, msg, indent: int = 0):
    prefix = "  " * indent
    print(f"\n{prefix}━━━ {step} ━━━")
    if isinstance(msg, dict):
        print(f"{prefix}{json.dumps(msg, ensure_ascii=False, indent=2)}")
    else:
        print(f"{prefix}{msg}")


def test_health(client: httpx.Client):
    log("STEP 0", "检查后端服务...")
    r = client.get(f"{BASE_URL}/api/health")
    r.raise_for_status()
    log("STEP 0", f"✅ 服务正常: {r.json()}")


def test_path_a_direct(client: httpx.Client):
    """路径 A: 开场白 → 直接开始采访 → 对话"""
    print("\n" + "=" * 55)
    print("  路径 A: 开场白 → 直接开始采访 → 对话")
    print("=" * 55)

    # 1. 开始会话
    log("A1 开始会话", "获取开场白 + 主卡片...")
    r = client.post(f"{BASE_URL}/api/session/start", json={"user_id": USER_ID + "_a", "entry_source": "cli_test"})
    r.raise_for_status()
    data = r.json()
    sid = data["session_id"]
    log("A1 结果", f"state={data['state']} 卡片={[c['label'] for c in data.get('cards', [])]}")
    if data.get("message"):
        m = data["message"]
        log("开场白", m.get("main_message", ""), indent=1)

    # 2. 点击「直接开始采访」→ 应该直接进入 INTERVIEWING
    log("A2 点击「直接开始采访」", "应一步进入采访...")
    r = client.post(f"{BASE_URL}/api/session/{sid}/card", json={"card_id": "start_interview"})
    r.raise_for_status()
    data = r.json()
    assert data["state"] == "INTERVIEWING", f"期望 INTERVIEWING，实际 {data['state']}"
    log("A2 结果", f"✅ state={data['state']}")

    # 3. 发送消息
    log("A3 对话", "用户发送消息...")
    r = client.post(f"{BASE_URL}/api/session/{sid}/chat", json={"message": "我小时候住在上海，院子里有棵梧桐树。"})
    r.raise_for_status()
    data = r.json()
    log("A3 回复", data.get("assistant_text", ""), indent=1)

    print("\n  ✅ 路径 A 通过")


def test_path_b_guidance(client: httpx.Client):
    """路径 B: 开场白 → 不知道怎么聊 → 选引导卡片 → 开始采访 → 对话"""
    print("\n" + "=" * 55)
    print("  路径 B: 开场白 → 不知道怎么聊 → 引导卡片 → 采访")
    print("=" * 55)

    # 1. 开始会话
    log("B1 开始会话", "获取开场白...")
    r = client.post(f"{BASE_URL}/api/session/start", json={"user_id": USER_ID + "_b", "entry_source": "cli_test"})
    r.raise_for_status()
    data = r.json()
    sid = data["session_id"]
    cards = data.get("cards", [])
    log("B1 卡片", [c["label"] for c in cards])

    # 验证有两张主卡片
    card_ids = [c["card_id"] for c in cards]
    assert "start_interview" in card_ids, "缺少「直接开始采访」卡片"
    assert "need_guidance" in card_ids, "缺少「不知道怎么聊」卡片"

    # 2. 点击「我还没想好怎么说」
    log("B2 点击「不知道怎么聊」", "应展示 6 张引导卡片...")
    r = client.post(f"{BASE_URL}/api/session/{sid}/card", json={"card_id": "need_guidance"})
    r.raise_for_status()
    data = r.json()
    guidance_cards = data.get("cards", [])
    log("B2 引导卡片", [c["label"] for c in guidance_cards])
    assert data["state"] == "GUIDANCE_CARD", f"期望 GUIDANCE_CARD，实际 {data['state']}"
    assert len(guidance_cards) == 6, f"期望 6 张引导卡片，实际 {len(guidance_cards)}"

    # 3. 选择一张引导卡片
    card_id = guidance_cards[0]["card_id"]
    card_label = guidance_cards[0]["label"]
    log(f"B3 选择卡片: {card_label}", "...")
    r = client.post(f"{BASE_URL}/api/session/{sid}/card", json={"card_id": card_id})
    r.raise_for_status()
    data = r.json()
    log("B3 引导回复", data.get("assistant_text", ""), indent=1)
    follow_cards = data.get("cards", [])
    log("B3 后续卡片", [c["label"] for c in follow_cards])
    assert any(c["card_id"] == "start_interview" for c in follow_cards), "应包含「开始采访」卡片"

    # 4. 点击「开始采访」→ 进入 INTERVIEWING
    log("B4 点击「开始采访」", "应直接进入采访...")
    r = client.post(f"{BASE_URL}/api/session/{sid}/card", json={"card_id": "start_interview"})
    r.raise_for_status()
    data = r.json()
    assert data["state"] == "INTERVIEWING", f"期望 INTERVIEWING，实际 {data['state']}"
    log("B4 结果", f"✅ state={data['state']}")

    # 5. 对话
    log("B5 对话", "用户发送消息...")
    r = client.post(f"{BASE_URL}/api/session/{sid}/chat", json={"message": "我小时候住在北京胡同里，院子里有棵枣树。"})
    r.raise_for_status()
    data = r.json()
    log("B5 回复", data.get("assistant_text", ""), indent=1)

    print("\n  ✅ 路径 B 通过")


def test_flow():
    client = httpx.Client(timeout=60, proxy=None, trust_env=False)

    test_health(client)
    test_path_a_direct(client)
    test_path_b_guidance(client)

    print("\n" + "=" * 55)
    print("  ✅✅ 全部集成测试通过！")
    print("=" * 55)

    client.close()


if __name__ == "__main__":
    test_flow()