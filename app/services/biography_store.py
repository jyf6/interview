from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Biography, CollectionPoint, MaterialFragment, OutlineVersion
from app.db.session import create_database_engine, create_session_factory, initialize_database


class BiographyStore:
    """SQLAlchemy ORM boundary for biography outlines and archived material."""

    def __init__(self, database_url: str, session_factory: sessionmaker[Session] | None = None) -> None:
        self.database_url = database_url
        self.engine = create_database_engine(database_url)
        initialize_database(self.engine)
        self.session_factory = session_factory or create_session_factory(self.engine)

    def _session(self) -> Session:
        return self.session_factory()

    def close(self) -> None:
        self.engine.dispose()

    def create_biography(self, interviewee_id: str | None = None) -> dict[str, Any]:
        biography = Biography(id=str(uuid4()), interviewee_id=interviewee_id)
        with self._session() as session, session.begin():
            session.add(biography)
        return {"id": biography.id, "interviewee_id": biography.interviewee_id}

    def biography_exists(self, biography_id: str) -> bool:
        with self._session() as session:
            return session.get(Biography, biography_id) is not None

    def save_outline(self, biography_id: str, source_highlight: str, chapters: list[dict[str, Any]]) -> dict[str, Any]:
        outline_id = str(uuid4())
        with self._session() as session, session.begin():
            if session.get(Biography, biography_id) is None:
                raise KeyError("biography_not_found")
            version = session.scalar(
                select(func.coalesce(func.max(OutlineVersion.version), 0) + 1)
                .where(OutlineVersion.biography_id == biography_id)
            )
            session.add(OutlineVersion(
                id=outline_id,
                biography_id=biography_id,
                version=int(version or 1),
                status="draft",
                source_highlight=source_highlight,
            ))
            session.flush()
            self._insert_points(session, outline_id, chapters)
        return self.get_outline(outline_id)

    def get_outline(self, outline_id: str) -> dict[str, Any]:
        with self._session() as session:
            outline = session.get(OutlineVersion, outline_id)
            if outline is None:
                raise KeyError("outline_not_found")
            points = session.scalars(
                select(CollectionPoint)
                .where(CollectionPoint.outline_version_id == outline_id)
                .order_by(CollectionPoint.chapter_no, CollectionPoint.point_no)
            ).all()
            result = {
                "id": outline.id,
                "biography_id": outline.biography_id,
                "version": outline.version,
                "status": outline.status,
                "source_highlight": outline.source_highlight,
            }
        chapters: dict[int, dict[str, Any]] = {}
        for point in points:
            chapter = chapters.setdefault(point.chapter_no, {"title": point.chapter_title, "points": []})
            chapter["points"].append({
                "id": point.id,
                "title": point.title,
                "hook": point.hook,
                "target_slots": point.target_slots or [],
            })
        return {**result, "chapters": list(chapters.values())}

    def get_published_outline(self, outline_id: str) -> dict[str, Any]:
        outline = self.get_outline(outline_id)
        if outline["status"] != "published":
            raise ValueError("outline_not_published")
        return outline

    def next_point(self, outline_id: str, point_id: str) -> dict[str, Any] | None:
        outline = self.get_published_outline(outline_id)
        points = [point for chapter in outline["chapters"] for point in chapter["points"]]
        for index, point in enumerate(points):
            if point["id"] == point_id:
                return points[index + 1] if index + 1 < len(points) else None
        return points[0] if points else None

    def archive_material(
        self,
        session_id: str,
        thread_id: str,
        target_stage_id: str,
        content: str,
        evaluation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        evaluation = evaluation or {}
        material = MaterialFragment(
            id=str(uuid4()),
            session_id=session_id,
            thread_id=thread_id,
            target_stage_id=target_stage_id,
            content=content.strip()[:10_000],
            coverage=float(evaluation.get("coverage", 0)),
            facts_json=evaluation,
        )
        with self._session() as session, session.begin():
            session.add(material)
        return {
            "id": material.id,
            "session_id": material.session_id,
            "thread_id": material.thread_id,
            "target_stage_id": material.target_stage_id,
            "content": material.content,
            "coverage": material.coverage,
            "facts_json": material.facts_json,
        }

    def list_materials(self, session_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = session.scalars(
                select(MaterialFragment)
                .where(MaterialFragment.session_id == session_id)
                .order_by(MaterialFragment.created_at, MaterialFragment.id)
            ).all()
            return [{
                "id": row.id,
                "session_id": row.session_id,
                "thread_id": row.thread_id,
                "target_stage_id": row.target_stage_id,
                "content": row.content,
                "coverage": row.coverage,
                "facts_json": row.facts_json,
                "created_at": row.created_at,
            } for row in rows]

    def replace_draft(self, outline_id: str, chapters: list[dict[str, Any]]) -> dict[str, Any]:
        with self._session() as session, session.begin():
            outline = session.get(OutlineVersion, outline_id)
            if outline is None:
                raise KeyError("outline_not_found")
            if outline.status != "draft":
                raise ValueError("outline_not_editable")
            session.execute(delete(CollectionPoint).where(CollectionPoint.outline_version_id == outline_id))
            self._insert_points(session, outline_id, chapters)
        return self.get_outline(outline_id)

    def publish_outline(self, outline_id: str) -> dict[str, Any]:
        with self._session() as session, session.begin():
            outline = session.get(OutlineVersion, outline_id)
            if outline is None:
                raise KeyError("outline_not_found")
            point_count = session.scalar(
                select(func.count(CollectionPoint.id)).where(CollectionPoint.outline_version_id == outline_id)
            )
            if not point_count:
                raise ValueError("outline_empty")
            outline.status = "published"
        return self.get_outline(outline_id)

    @staticmethod
    def _insert_points(session: Session, outline_id: str, chapters: list[dict[str, Any]]) -> None:
        for chapter_no, chapter in enumerate(chapters, start=1):
            for point_no, point in enumerate(chapter.get("points", []), start=1):
                session.add(CollectionPoint(
                    id=str(uuid4()),
                    outline_version_id=outline_id,
                    chapter_no=chapter_no,
                    chapter_title=str(chapter.get("title") or f"第{chapter_no}章"),
                    point_no=point_no,
                    title=str(point.get("title") or f"采集点{point_no}"),
                    hook=str(point.get("hook") or ""),
                    target_slots=point.get("target_slots") or [],
                ))
