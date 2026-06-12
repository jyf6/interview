# 路由与回复示例

这些例子用于校准路线判断和最终回复。默认行为是只输出最终用户可见回复。只有调试时才输出 JSON。

## 正常采访

用户：“我想补充一下之前离职那件事，当时其实还有一个同事帮了我不少。”

路由判断：

```json
{
  "route": "normal_interview",
  "emotion_type": "none",
  "confidence": 0.9,
  "reason": "用户在补充具体事件和人物，没有出现负面负担或回避。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 1
}
```

默认回复：

“采：可以，我会把这个同事的帮助也放进这段经历里。那他当时具体是怎么帮到您的？”

## 轻度情绪疏导

用户：“现在想想，年轻时候陪家人的时间确实太少了，有点遗憾。”

路由判断：

```json
{
  "route": "mild_emotional_guidance",
  "emotion_type": "regret_self_blame",
  "confidence": 0.78,
  "reason": "用户表达轻度遗憾，但没有拒绝继续讲述，也没有陷入强烈自责。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 1
}
```

默认回复：

“采：年轻时候很多人都要为生活奔波，这份遗憾也藏着对家人的牵挂。后来有没有哪件小事，让您觉得多少弥补了一些？”

## 明显情绪疏导

用户：“越想越心酸，现在身边再也没有那样疼我的人了。”

路由判断：

```json
{
  "route": "strong_emotional_guidance",
  "emotion_type": "sadness",
  "confidence": 0.88,
  "reason": "用户表达明显伤感，负面情绪重于事实叙述。",
  "should_change_topic": true,
  "do_not_probe_current_topic": true,
  "round_decrement": 1
}
```

默认回复：

“采：我能理解这份感触，过往的美好总会让人动容。咱们先不聊这些让人心酸的内容了，说说那时候让您觉得轻松快乐的小事吧？”

## 抵触跳转

用户：“没必要再提这些旧事了。”

路由判断：

```json
{
  "route": "resistance_turn",
  "emotion_type": "mixed",
  "confidence": 0.95,
  "reason": "用户明确表示不想继续当前话题，应停止追问并换话题。",
  "should_change_topic": true,
  "do_not_probe_current_topic": true,
  "round_decrement": 1
}
```

默认回复：

“采：好的，我尊重您的想法，这段我们就不聊了。接下来换个轻松些的话题，说说现在生活里让您觉得舒心的小事吧？”

## 隐性低落

历史对话：

```text
采：童年的生活环境，现在还能清晰记起来吗？
受：还行。
采：那小时候有没有印象深刻的玩伴呢？
```

用户：“记不清了。”

路由判断：

```json
{
  "route": "implicit_low_engagement",
  "emotion_type": "unclear",
  "confidence": 0.76,
  "reason": "用户连续短答且表示记不清，没有新信息，适合降低压力并换轻松角度。",
  "should_change_topic": true,
  "do_not_probe_current_topic": false,
  "round_decrement": 1
}
```

默认回复：

“采：没关系，记不清的地方咱们就不勉强回想了。换个轻松点的角度说说，现在的日子里，什么事最让您觉得踏实？”

## 低轮数兴致高涨

当前阶段建议剩余轮数：2

用户：“那次第一次去外地打工，我到现在都记得，背着一个包就上车了，心里又紧张又期待，后来刚到车站还闹了个笑话。”

路由判断：

```json
{
  "route": "normal_interview",
  "emotion_type": "none",
  "confidence": 0.88,
  "reason": "用户在低轮数时主动补充具体事件和细节，表现出明显讲述欲，没有抵触或情绪下沉。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 0
}
```

默认回复：

“采：这个画面一下子就鲜活起来了，也能看出那次出门在您心里分量不轻。刚到车站闹的那个笑话，是怎么回事？”
