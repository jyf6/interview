from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Biography(Base):
    __tablename__ = "biographies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interviewee_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutlineVersion(Base):
    __tablename__ = "outline_versions"
    __table_args__ = (UniqueConstraint("biography_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    biography_id: Mapped[str] = mapped_column(ForeignKey("biographies.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    source_highlight: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionPoint(Base):
    __tablename__ = "collection_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    outline_version_id: Mapped[str] = mapped_column(ForeignKey("outline_versions.id", ondelete="CASCADE"))
    chapter_no: Mapped[int] = mapped_column(Integer)
    chapter_title: Mapped[str] = mapped_column(String(160))
    point_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    hook: Mapped[str] = mapped_column(Text, default="")
    target_slots: Mapped[list[str]] = mapped_column(JSONB, default=list)


class MaterialFragment(Base):
    __tablename__ = "material_fragments"
    __table_args__ = (Index("idx_material_fragments_session", "session_id", "created_at", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(120))
    thread_id: Mapped[str] = mapped_column(String(120))
    target_stage_id: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    coverage: Mapped[float] = mapped_column(Float, default=0)
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
