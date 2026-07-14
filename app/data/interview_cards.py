CARD_ID_ALIASES = {
    "need_more_guidance": "need_guidance",
    "dont_know_process": "unknown_process",
    "dont_know_start_point": "scattered",
    "worry_not_good_at_talking": "restrained",
    "want_example_first": "unknown_process",
}


def normalize_card_id(card_id: str) -> str:
    return CARD_ID_ALIASES.get(card_id, card_id)
