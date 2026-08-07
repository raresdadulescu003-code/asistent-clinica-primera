"""Formele cererilor HTTP. Validarea se face la graniță, o singură dată."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from clinic_agent.domain.models import ChatTurn

MAX_MESSAGE_CHARS = 2000


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    messages: list[MessageIn] = Field(min_length=1, max_length=100)

    @field_validator("messages")
    @classmethod
    def last_message_must_be_from_user(cls, messages: list[MessageIn]) -> list[MessageIn]:
        if messages[-1].role != "user":
            raise ValueError("ultimul mesaj trebuie să fie al utilizatorului")
        return messages

    def to_turns(self) -> list[ChatTurn]:
        return [ChatTurn(role=m.role, content=m.content) for m in self.messages]
