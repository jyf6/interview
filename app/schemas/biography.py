from pydantic import BaseModel, Field


class BiographyCreateRequest(BaseModel):
    interviewee_id: str | None = None


class BiographyResponse(BaseModel):
    id: str
    interviewee_id: str | None = None


class IcebreakerRequest(BaseModel):
    content: str = Field(min_length=10, max_length=20_000)


class HighlightSessionRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=120)


class HighlightMessageRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=10_000)


class HighlightTurnResponse(BaseModel):
    session_id: str
    assistant_message: str
    messages: list[dict]
    ready: bool
    outline: dict | None = None
    evaluation: dict = Field(default_factory=dict)


class OutlineResponse(BaseModel):
    id: str
    biography_id: str
    version: int
    status: str
    source_highlight: str
    chapters: list[dict]


class OutlineEditRequest(BaseModel):
    chapters: list[dict] = Field(min_length=1)
