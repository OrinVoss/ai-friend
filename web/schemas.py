"""Pydantic schemas for REST API request/response validation."""

from pydantic import BaseModel, Field


# #309: session_id 会被拼进文件路径，只允许安全字符（防路径穿越）
SESSION_ID_PATTERN = r"^[0-9A-Za-z_\-一-鿿]{1,64}$"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message to the AI")
    session_id: str = Field(default="default", pattern=SESSION_ID_PATTERN,
                            description="Session identifier")


class ChatResponse(BaseModel):
    response: str
    emotion: str
    turn: int
    session_id: str


class StatusResponse(BaseModel):
    turn: int
    emotion: str
    relationship: dict
    relationship_history: list


class HistoryTurn(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    turns: list[HistoryTurn]
    session_id: str
