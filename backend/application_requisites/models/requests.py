# pydantic request models

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from .enums import ScanMode


class ScanRequest(BaseModel):
    email: Optional[EmailStr] = Field(default=None)
    full_name: Optional[str] = Field(default=None)
    username: Optional[str] = Field(default=None)
    usernames: Optional[List[str]] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    scan_mode: ScanMode = Field(default=ScanMode.HYBRID)
    hcaptcha_token: Optional[str] = Field(default=None)

    def has_any_identifier(self) -> bool:
        return any([self.email, self.full_name, self.phone, self.username, self.usernames])


class NormalizedQuery(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    usernames: List[str] = Field(default_factory=list)

    def merge(self, other: "NormalizedQuery") -> "NormalizedQuery":
        merged_users = list({*self.usernames, *other.usernames})
        return NormalizedQuery(
            email=self.email or other.email,
            full_name=self.full_name or other.full_name,
            phone=self.phone or other.phone,
            usernames=merged_users,
        )

    def is_empty(self) -> bool:
        return not any([self.email, self.full_name, self.phone, self.usernames])
