from app.data.interview_cards import ENTRY_CARDS
from app.schemas.interview import DialogMessage, InterviewCard


class OpeningService:
    def build_opening_message(self) -> DialogMessage:
        content = (
            "您好，我会像一位安静的记录者，陪您把重要经历慢慢整理下来。"
            "这里没有标准答案，我们可以按您舒服的节奏来。"
        )
        return DialogMessage(content=content)

    def build_entry_cards(self) -> list[InterviewCard]:
        return [InterviewCard(**card) for card in ENTRY_CARDS]
