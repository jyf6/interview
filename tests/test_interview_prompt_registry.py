import unittest

from app.prompts.interview_prompts import (
    EMOTION_BASE_PROMPT,
    EMOTION_PROMPT_BY_TYPE,
    GUIDANCE_QA_SYSTEM_PROMPT,
    ICEBREAKER_PROMPT,
    OPENING_SYSTEM_PROMPT,
    RETURNING_USER_OPENING_SYSTEM_PROMPT,
    ROUTING_JUDGEMENT_PROMPT,
    STAGE_ROUTE_PROMPT,
    STAGE_SUMMARY_PROMPT,
    STAGE_PROMPT_FILES,
)
from app.prompts.loader import load_prompt


class InterviewPromptRegistryTests(unittest.TestCase):
    def test_all_registered_interview_prompts_are_loadable(self) -> None:
        prompt_names = {
            OPENING_SYSTEM_PROMPT,
            RETURNING_USER_OPENING_SYSTEM_PROMPT,
            GUIDANCE_QA_SYSTEM_PROMPT,
            ICEBREAKER_PROMPT,
            ROUTING_JUDGEMENT_PROMPT,
            STAGE_ROUTE_PROMPT,
            STAGE_SUMMARY_PROMPT,
            EMOTION_BASE_PROMPT,
            *EMOTION_PROMPT_BY_TYPE.values(),
            *(prompt for stage_prompts in STAGE_PROMPT_FILES.values() for prompt in stage_prompts.values()),
        }

        for prompt_name in sorted(prompt_names):
            with self.subTest(prompt_name=prompt_name):
                self.assertTrue(load_prompt(prompt_name))
