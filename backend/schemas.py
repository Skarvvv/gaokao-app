"""Pydantic Schemas
===================
Request/response validation models for auth endpoints.
Separate from ORM models to keep API contracts clean.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ============================================
# Auth requests
# ============================================

class RegisterRequest(BaseModel):
    phone: str = Field(..., min_length=11, max_length=11, description="手机号 (11位)")
    password: str = Field(..., min_length=6, max_length=50, description="密码 (至少6位)")
    nickname: Optional[str] = Field(None, max_length=50, description="昵称 (选填)")


class LoginRequest(BaseModel):
    phone: str = Field(..., description="手机号")
    password: str = Field(..., description="密码")


# ============================================
# Profile request/response
# ============================================

class ProfileRequest(BaseModel):
    score: Optional[int] = None
    province: Optional[str] = None
    subjects: Optional[List[str]] = None
    schoolLevels: Optional[List[str]] = None
    majors: Optional[List[str]] = None
    strategy: Optional[str] = None
    region: Optional[str] = None


class ProfileResponse(BaseModel):
    score: Optional[int] = None
    province: Optional[str] = None
    subjects: Optional[List[str]] = None
    schoolLevels: Optional[List[str]] = None
    majors: Optional[List[str]] = None
    strategy: Optional[str] = None
    region: Optional[str] = None
