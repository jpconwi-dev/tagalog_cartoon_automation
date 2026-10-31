from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class TopicRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    category: str = Field(default="general", max_length=80)
    key_points: list[str] = Field(default_factory=list, max_length=12)
    target_seconds: int = Field(default=240, ge=30, le=1800)


class Scene(BaseModel):
    index: int = Field(default=0, ge=0)
    narration: str = Field(min_length=10, max_length=1200)
    on_screen_text: str | None = Field(default=None, max_length=120)
    visual: str = Field(min_length=5, max_length=600)
    characters: list[str] = Field(default_factory=list)
    sound_effects: list[str] = Field(default_factory=list)
    transition: str = "cut"
    est_seconds: float = Field(default=10.0, gt=0, le=120)


class ScriptDoc(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    topic: str = Field(min_length=3)
    category: str = "general"
    target_audience: str = "Pangkalahatang manonood"
    hook: str = Field(min_length=10)
    introduction: str = Field(min_length=10)
    scenes: list[Scene] = Field(min_length=3, max_length=40)
    conclusion: str = Field(min_length=10)
    call_to_action: str = Field(min_length=5)
    references: list[str] = Field(default_factory=list)
    est_duration_seconds: float = Field(default=0.0, ge=0)
    language: str = "fil"
    is_template: bool = False
    provider: str | None = None

    @field_validator("scenes")
    @classmethod
    def _renumber(cls, scenes: list[Scene]) -> list[Scene]:
        for i, s in enumerate(scenes, 1):
            s.index = i
        return scenes

    @model_validator(mode="after")
    def _check(self):
        narr = [s.narration.strip().lower() for s in self.scenes]
        if len(set(narr)) != len(narr):
            raise ValueError("duplicate scene narration")
        if not self.est_duration_seconds:
            self.est_duration_seconds = round(sum(s.est_seconds for s in self.scenes), 1)
        return self


Camera = Literal["static", "zoom_in", "zoom_out", "pan_left", "pan_right"]


class CharacterPlacement(BaseModel):
    character_id: str
    pose: str = "stand"
    expression: str = "neutral"
    position: Literal["left", "center", "right"] = "center"


class ScenePlanItem(BaseModel):
    scene_index: int = Field(ge=1)
    background: str = Field(min_length=2)
    characters: list[CharacterPlacement] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    camera: Camera = "static"
    speech_bubble: str | None = None


class ScenePlan(BaseModel):
    scenes: list[ScenePlanItem] = Field(min_length=1)


class VideoMetadata(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    description: str = Field(min_length=10, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    hashtags: list[str] = Field(default_factory=list, max_length=3)
    category_id: str = "27"  # YouTube "Education"

    @field_validator("tags")
    @classmethod
    def _trim_tags(cls, tags: list[str]) -> list[str]:
        out, total = [], 0
        for t in (x.strip() for x in tags):
            if not t:
                continue
            if total + len(t) > 450:  # YouTube allows ~500 chars total; keep margin
                break
            out.append(t)
            total += len(t)
        return out

    @field_validator("hashtags")
    @classmethod
    def _norm_hashtags(cls, tags: list[str]) -> list[str]:
        return ["#" + t.strip().lstrip("#").replace(" ", "") for t in tags if t.strip().lstrip("#")]
