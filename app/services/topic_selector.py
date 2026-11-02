import json
import re
import unicodedata
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import Settings
from app.models.tables import TopicHistory
from app.schemas.content import TopicRequest

BANK_PATH = Path(__file__).resolve().parent.parent / "templates" / "topics.json"


class NoTopicAvailable(Exception):
    pass


class DuplicateTopic(Exception):
    pass


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", t).split())


def similarity(a: str, b: str) -> float:
    ta, tb = set(normalize(a).split()), set(normalize(b).split())
    if not ta or not tb:
        return 0.0
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) >= 3 and small <= big:  # one title contained in the other
        return 1.0
    return len(ta & tb) / len(ta | tb)


def find_duplicate(title: str, used_titles: list[str], threshold: float) -> str | None:
    for u in used_titles:
        if similarity(title, u) >= threshold:
            return u
    return None


def load_bank(path: Path = BANK_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def used_titles(session: Session) -> list[str]:
    return [t.title for t in session.exec(select(TopicHistory).order_by(TopicHistory.id)).all()]


def select_topic(session: Session, settings: Settings, bank: list[dict] | None = None) -> TopicRequest:
    """Rotate categories (least recently used first) and skip anything already covered."""
    bank = bank if bank is not None else load_bank()
    history = list(session.exec(select(TopicHistory).order_by(TopicHistory.id)).all())
    used = [h.title for h in history]
    last_idx = {}
    for i, h in enumerate(history):
        last_idx[h.category] = i
    categories = list(dict.fromkeys(b["category"] for b in bank))
    for cat in sorted(categories, key=lambda c: (last_idx.get(c, -1), categories.index(c))):
        for b in (x for x in bank if x["category"] == cat):
            if not find_duplicate(b["title"], used, settings.topic_similarity_threshold):
                return TopicRequest(title=b["title"], subject=b.get("subject"), category=cat,
                                    key_points=b.get("key_points", []),
                                    target_seconds=min(240, settings.max_video_duration_seconds))
    raise NoTopicAvailable("every topic in app/templates/topics.json has been used; add more topics")


def ensure_not_duplicate(session: Session, settings: Settings, title: str) -> None:
    match = find_duplicate(title, used_titles(session), settings.topic_similarity_threshold)
    if match:
        raise DuplicateTopic(f"too similar to an earlier video: {match}")


def record_topics(session: Session, category: str, *titles: str) -> None:
    seen: set[str] = set()
    for t in titles:
        if t and normalize(t) not in seen:
            seen.add(normalize(t))
            session.add(TopicHistory(title=t, category=category))
