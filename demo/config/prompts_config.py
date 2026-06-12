"""Prompt templates loaded from demo/prompts."""

from config.prompt_loader import load_prompt


OPENING_SYSTEM_PROMPT = load_prompt("opening_system.txt")
OPENING_USER_PROMPT_TEMPLATE = load_prompt("opening_user.txt")

GUIDANCE_SYSTEM_PROMPT = load_prompt("guidance_system.txt")
GUIDANCE_USER_PROMPT_TEMPLATE = load_prompt("guidance_user.txt")
