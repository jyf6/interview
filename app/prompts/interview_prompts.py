"""Runtime interview prompt registry.

All LLM prompts used by the interview flow live under app/prompts/interview/.
Services should import prompt names from this module instead of hard-coding paths.
"""

from typing import Final


OPENING_SYSTEM_PROMPT: Final = "interview/opening-system.txt"
RETURNING_USER_OPENING_SYSTEM_PROMPT: Final = "interview/returning-user-opening-system.txt"
GUIDANCE_QA_SYSTEM_PROMPT: Final = "interview/guidance-qa-system.txt"

ICEBREAKER_PROMPT: Final = "interview/icebreaker.txt"
ROUTING_JUDGEMENT_PROMPT: Final = "interview/routing-judgement.md"
STAGE_DETECTION_PROMPT: Final = "interview/stage-detection.md"

EMOTION_BASE_PROMPT: Final = "interview/emotion/base.md"
EMOTION_PROMPT_BY_TYPE: Final[dict[str, str]] = {
    "none": "interview/emotion/none.md",
    "sadness": "interview/emotion/sadness.md",
    "regret_self_blame": "interview/emotion/regret-self-blame.md",
    "repression_grievance": "interview/emotion/repression-grievance.md",
    "anxiety_heavy": "interview/emotion/anxiety-heavy.md",
    "loneliness": "interview/emotion/loneliness.md",
    "mixed": "interview/emotion/mixed.md",
    "unclear": "interview/emotion/unclear.md",
}

STAGE_MAIN_QUESTION_IDS: Final[dict[str, tuple[int, ...]]] = {
    "S1": tuple(range(1, 6)),
    "S2": tuple(range(1, 7)),
    "S3": tuple(range(1, 7)),
    "S4": tuple(range(1, 7)),
    "S5": tuple(range(1, 7)),
    "S6": tuple(range(1, 7)),
    "S7": tuple(range(1, 6)),
}

STAGE_PROMPT_FILES: Final[dict[str, dict[str, str]]] = {
    "S1": {
        "main_question": "interview/founder-s1-childhood-main-question.md",
        "followup": "interview/founder-s1-childhood-detail-followup.md",
    },
    "S2": {
        "main_question": "interview/founder-s2-youth-main-question.md",
        "followup": "interview/founder-s2-youth-detail-followup.md",
    },
    "S3": {
        "main_question": "interview/founder-s3-career-start-main-question.md",
        "followup": "interview/founder-s3-career-start-detail-followup.md",
    },
    "S4": {
        "main_question": "interview/founder-s4-breakthrough-main-question.md",
        "followup": "interview/founder-s4-breakthrough-detail-followup.md",
    },
    "S5": {
        "main_question": "interview/founder-s5-peak-darkness-main-question.md",
        "followup": "interview/founder-s5-peak-darkness-detail-followup.md",
    },
    "S6": {
        "main_question": "interview/founder-s6-balance-choice-main-question.md",
        "followup": "interview/founder-s6-balance-choice-detail-followup.md",
    },
    "S7": {
        "main_question": "interview/founder-s7-legacy-main-question.md",
        "followup": "interview/founder-s7-legacy-detail-followup.md",
    },
}
