"""ORM Models
=============
User         — account table (phone + password_hash + nickname)
UserProfile  — one-to-one profile (score, province, subjects, preferences)

JSON fields (subjects, school_levels, majors) are stored as TEXT
and serialized/deserialized via json.loads / json.dumps.
This works identically on SQLite and MySQL.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    profile = relationship(
        "UserProfile",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "phone": self.phone,
            "nickname": self.nickname or "",
        }


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    score = Column(Integer, nullable=True)
    province = Column(String(50), nullable=True)
    subjects = Column(Text, nullable=True)        # JSON array
    school_levels = Column(Text, nullable=True)    # JSON array
    majors = Column(Text, nullable=True)           # JSON array
    strategy = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User", back_populates="profile")

    def to_dict(self):
        return {
            "score": self.score,
            "province": self.province or "",
            "subjects": json.loads(self.subjects) if self.subjects else [],
            "schoolLevels": json.loads(self.school_levels) if self.school_levels else [],
            "majors": json.loads(self.majors) if self.majors else [],
            "strategy": self.strategy or "",
            "region": self.region or "",
        }
