# 路由与回复示例

这些例子用于校准三类路线：正常采访、扩展采访、情绪疏导。默认行为是只输出最终用户可见回复。只有调试时才输出 JSON。

## 正常采访

用户：“12 岁以前，那时候主要是在家里帮忙。”

路由判断：

```json
{
  "route": "normal_interview",
  "emotion_type": "none",
  "confidence": 0.72,
  "reason": "用户明确说到 12 岁以前，属于童年阶段；回答稳定但没有明确可扩展素材，应按主流程继续。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 1,
  "detected_stage": "S1",
  "stage_shift_reason": "",
  "skip_completed_stages": true
}
```

默认回复：

“采：那时候家里的担子已经落到您身上一部分了，平日里最常帮着做些什么？”

## 阶段识别：外出打工不是童年

用户：“我在深圳打工那几年，刚开始什么都不熟，住在厂边的小房子里。”

路由判断：

```json
{
  "route": "extended_interview",
  "emotion_type": "none",
  "confidence": 0.86,
  "reason": "用户提到深圳打工、居住处境和初到状态，属于初入社会或早期工作经历，不是童年。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 0,
  "detected_stage": "S2",
  "stage_shift_reason": "用户提到外出打工经历，更接近青春岁月/初入社会阶段。",
  "skip_completed_stages": true
}
```

默认回复：

“采：刚到深圳那阵子，人生地不熟，确实很考验人。那时候最让您感到不适应的是什么？”

用户：“结婚后我去深圳打工养家，孩子还小，那几年压力特别大。”

路由判断：

```json
{
  "route": "emotional_guidance",
  "emotion_type": "anxiety_heavy",
  "confidence": 0.84,
  "reason": "用户把打工与结婚后、养家、孩子和压力绑定，属于人生转折阶段且有明显负担。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 1,
  "detected_stage": "S3",
  "stage_shift_reason": "用户提到婚后养家责任，属于人生转折阶段。",
  "skip_completed_stages": true
}
```

默认回复：

“采：那几年一边在外挣钱一边惦记家里，身上的责任肯定不轻。回头看，那段日子里最关键的一次选择是什么？”

## 扩展采访

用户：“我还记得第一次去外地打工，背着一个包就上车了，心里又紧张又期待，后来刚到车站还闹了个笑话。”

路由判断：

```json
{
  "route": "extended_interview",
  "emotion_type": "none",
  "confidence": 0.88,
  "reason": "用户主动讲出具体事件、时间节点和感受，适合围绕该素材单步扩展。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 0,
  "detected_stage": "S2",
  "stage_shift_reason": "用户提到第一次外出打工，属于青春岁月或初入社会阶段。",
  "skip_completed_stages": true
}
```

默认回复：

“采：刚到车站闹的那个笑话，是怎么回事？”

## 新阶段入口：有素材也先扩展

当前阶段：S1 童年时光，当前阶段建议剩余轮数：4

用户：“这个跟我小时候一样，平时喜欢钓鱼。”

路由判断：

```json
{
  "route": "extended_interview",
  "emotion_type": "none",
  "confidence": 0.82,
  "reason": "用户提到小时候钓鱼，这是可扩展的童年事件素材，即使处于新阶段入口也应先单步扩展。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 0,
  "detected_stage": "S1",
  "stage_shift_reason": "",
  "skip_completed_stages": true
}
```

默认回复：

“采：小时候会去钓鱼，听起来那段日子里有很具体的画面。那时候一般是和谁一起去，后来有没有哪一次让您特别记得？”

## 情绪疏导：轻度遗憾

用户：“现在想想，年轻时候陪家人的时间确实太少了，有点遗憾。”

路由判断：

```json
{
  "route": "emotional_guidance",
  "emotion_type": "regret_self_blame",
  "confidence": 0.78,
  "reason": "用户表达遗憾和自责倾向，需要先轻轻承接。",
  "should_change_topic": false,
  "do_not_probe_current_topic": false,
  "round_decrement": 0,
  "detected_stage": "S3",
  "stage_shift_reason": "",
  "skip_completed_stages": true
}
```

默认回复：

“采：年轻时候很多人都要为生活奔波，这份遗憾也藏着对家人的牵挂。后来有没有哪件小事，让您觉得多少弥补了一些？”

## 情绪疏导：抵触转场

用户：“没必要再提这些旧事了。”

路由判断：

```json
{
  "route": "emotional_guidance",
  "emotion_type": "mixed",
  "confidence": 0.95,
  "reason": "用户明确表示不想继续当前扩展话题，应停止追问该支线并回到当前阶段主问题。",
  "should_change_topic": true,
  "do_not_probe_current_topic": true,
  "round_decrement": 1,
  "detected_stage": "unclear",
  "stage_shift_reason": "用户抵触当前扩展话题，建议停止该支线并回到当前阶段尚未完成的主问题。",
  "skip_completed_stages": false
}
```

默认回复：

“采：好的，这段我们就先放下，不顺着这里深聊了。那回到这段时期本身，平日里您主要是怎么过的？”

## 情绪疏导：低参与回主问题

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
  "route": "emotional_guidance",
  "emotion_type": "unclear",
  "confidence": 0.76,
  "reason": "用户连续短答且表示记不清，没有新信息，适合降低压力并回到当前阶段主问题。",
  "should_change_topic": true,
  "do_not_probe_current_topic": true,
  "round_decrement": 1,
  "detected_stage": "unclear",
  "stage_shift_reason": "当前扩展支线积极性下降，建议停止该支线并回到当前阶段尚未完成的主问题。",
  "skip_completed_stages": false
}
```

默认回复：

“采：没关系，记不清的地方咱们就不勉强回想了。那回到小时候这段，平日里您主要是怎么过的？”
