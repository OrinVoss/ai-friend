"""Pydantic schemas for REST API request/response validation."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message to the AI")
    session_id: str = Field(default="default", description="Session identifier")


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
