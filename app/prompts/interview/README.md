# Interview Prompts

This directory is the single runtime home for interview-related LLM prompts.

Code should reference prompt files through `app/prompts/interview_prompts.py`, not by hard-coding paths in services.

## Opening And Guidance

- `opening-system.txt`: first-time opening message generation.
- `returning-user-opening-system.txt`: returning-user welcome message generation.
- `guidance-qa-system.txt`: guidance-card Q&A generation before the formal interview.
- `icebreaker.txt`: fixed first formal-interview icebreaker after the user starts the interview.

## Formal Interview Flow

- `routing-judgement.md`: route each user turn to normal interview, extended interview, or emotional-support fusion.
- `stage-detection.md`: detect which S1-S5 stage the user's content belongs to.
- `s*-*-main-question.md`: stage-specific planned main-question prompts.
- `s*-*-detail-followup.md`: stage-specific detail follow-up prompts for high-engagement extension.

## Emotional Support

- `emotion/base.md`: shared emotional-support fusion rules.
- `emotion/*.md`: emotion-type-specific guidance snippets appended only when route judgement marks emotional support as needed.
