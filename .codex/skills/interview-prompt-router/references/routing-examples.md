# Routing Examples

Use these examples to calibrate route decisions and final replies. Default behavior is to return only the final user-facing reply. Use the JSON form only for debug output.

## Normal Interview

User: "我想补充一下之前离职那件事。"

Debug decision:

```json
{
  "route": "normal_interview",
  "confidence": 0.9,
  "signals": ["supplement_existing_event", "stable_narration"],
  "selected_prompt": "references/normal-interview-prompt.md",
  "assistant_reply": "可以，我会把它补充到离职这件事里。你想补充的是当时发生的经过，还是你后来做决定的原因？"
}
```

Default reply:

"可以，我会把它补充到离职这件事里。你想补充的是当时发生的经过，还是你后来做决定的原因？"

## Emotional Support

User: "我还是觉得这一切都是我的错，我不太想说了。"

Debug decision:

```json
{
  "route": "emotional_support",
  "confidence": 0.95,
  "signals": ["self_blame", "unwilling_to_continue"],
  "selected_prompt": "references/emotional-support-prompt.md",
  "assistant_reply": "听起来这部分对你来说很沉重，我们不用急着继续往下说。你可以选择先停一下，也可以只留一句很简短的记录：这是一段让你很自责、也不太想展开的经历。"
}
```

Default reply:

"听起来这部分对你来说很沉重，我们不用急着继续往下说。你可以选择先停一下，也可以只留一句很简短的记录：这是一段让你很自责、也不太想展开的经历。"

## Ambiguous But Continuing

User: "那段挺难的，不过我可以继续说。"

Debug decision:

```json
{
  "route": "normal_interview",
  "confidence": 0.68,
  "signals": ["emotion_present", "explicit_continue"],
  "selected_prompt": "references/normal-interview-prompt.md",
  "assistant_reply": "好，我们慢一点来。你愿意继续的话，可以先说说那件事大概发生在什么时候吗？"
}
```

Default reply:

"好，我们慢一点来。你愿意继续的话，可以先说说那件事大概发生在什么时候吗？"

## Prefer Support

User: "一想到这里我就有点发抖。"

Debug decision:

```json
{
  "route": "emotional_support",
  "confidence": 0.88,
  "signals": ["somatic_distress"],
  "selected_prompt": "references/emotional-support-prompt.md",
  "assistant_reply": "我们先停在这里，不需要继续回忆细节。你可以先把注意力放回现在，慢慢呼吸一下；如果你愿意，我们可以暂停这一段，或者只记录一个很短的标题。"
}
```

Default reply:

"我们先停在这里，不需要继续回忆细节。你可以先把注意力放回现在，慢慢呼吸一下；如果你愿意，我们可以暂停这一段，或者只记录一个很短的标题。"
