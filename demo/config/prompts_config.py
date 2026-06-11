"""Prompt templates loaded from demo/prompts."""

from config.prompt_loader import load_prompt


OPENING_SYSTEM_PROMPT = load_prompt("opening_system.txt")
OPENING_USER_PROMPT_TEMPLATE = load_prompt("opening_user.txt")

GUIDANCE_SYSTEM_PROMPT = load_prompt("guidance_system.txt")
GUIDANCE_USER_PROMPT_TEMPLATE = load_prompt("guidance_user.txt")

INTERVIEW_SYSTEM_PROMPT = load_prompt("interview_system.txt")
INTERVIEW_USER_PROMPT_TEMPLATE = load_prompt("interview_user.txt")

EMOTION_SINGLE_SYSTEM_PROMPT = load_prompt("emotion_single_system.txt")
EMOTION_SINGLE_USER_PROMPT_TEMPLATE = load_prompt("emotion_single_user.txt")
