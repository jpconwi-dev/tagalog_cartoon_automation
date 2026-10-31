from app.core.config import Settings
from app.schemas.content import (CharacterPlacement, Scene, ScenePlan, ScenePlanItem, ScriptDoc,
                                 TopicRequest, VideoMetadata)
from app.services.providers.base import HealthResult

_ORD = ["Una", "Pangalawa", "Pangatlo", "Pang-apat", "Panlima", "Pang-anim", "Pampito", "Pangwalo"]
_BACKGROUNDS = ["meadow", "village", "classroom", "night_sky", "river", "workshop"]
_CAMERAS = ["zoom_in", "pan_right", "static", "zoom_out", "pan_left"]


def _secs(text: str) -> float:
    return max(4.0, round(len(text.split()) / 2.5, 1))


class TemplateProvider:
    """Last-resort, offline, no-AI provider. Makes no factual claims beyond supplied key points."""
    name = "template"

    def __init__(self, settings: Settings, client=None):
        self.settings = settings

    async def generate_script(self, req: TopicRequest) -> ScriptDoc:
        t = req.title
        pts = [p.strip() for p in req.key_points if p.strip()][:8]
        scenes: list[tuple[str, str, list[str]]] = [
            (f"Alam mo ba kung ano talaga ang totoo tungkol sa {t}? Tara, alamin natin!",
             "Juan scratches his head with a big question mark above him", ["juan"]),
        ]
        if pts:
            for i, p in enumerate(pts):
                scenes.append((f"{_ORD[i]}, {p}", f"Mara explains point {i + 1} using a simple drawing", ["mara", "juan"]))
        else:
            scenes += [
                (f"Magsimula tayo sa isang tanong: ano nga ba ang {t}?", "Juan thinking with a thought bubble", ["juan"]),
                ("Madalas, may kinalaman ito sa mga bagay na nakikita natin sa araw-araw na buhay.",
                 "Mara pointing at everyday objects on a table", ["mara"]),
                ("Laging magtanong at magsaliksik sa mapagkakatiwalaang sanggunian para makasiguro.",
                 "Juan reading a big book with a magnifying glass", ["juan"]),
            ]
        scenes.append((f"Kaya ayan, natutunan natin ang ilang mahahalagang bagay tungkol sa {t}.",
                       "Juan and Mara waving at the viewer", ["juan", "mara"]))
        built = [Scene(narration=n, visual=v, characters=c, est_seconds=min(120.0, _secs(n)),
                       on_screen_text=t[:60] if i == 0 else None, transition="fade" if i % 3 == 2 else "cut")
                 for i, (n, v, c) in enumerate(scenes)]
        return ScriptDoc(
            title=t[:100], topic=t, category=req.category,
            hook=scenes[0][0],
            introduction=f"Sa video na ito, pag-uusapan natin ang {t} sa simple at nakakatuwang paraan.",
            scenes=built,
            conclusion="Sana may bago kang natutunan ngayong araw.",
            call_to_action="Kung nagustuhan mo ito, mag-like, mag-subscribe, at ibahagi sa kaibigan mo!",
            references=[], is_template=True, provider=self.name)

    async def generate_scene_plan(self, script: ScriptDoc) -> ScenePlan:
        items = []
        for i, s in enumerate(script.scenes):
            chars = s.characters or ["juan"]
            placed = [CharacterPlacement(character_id=c if c in ("juan", "mara") else "juan",
                                         position=["left", "right", "center"][j % 3],
                                         expression="happy" if i % 2 == 0 else "surprised")
                      for j, c in enumerate(chars[:2])]
            items.append(ScenePlanItem(scene_index=s.index, background=_BACKGROUNDS[i % len(_BACKGROUNDS)],
                                       characters=placed, camera=_CAMERAS[i % len(_CAMERAS)],
                                       speech_bubble=s.on_screen_text))
        return ScenePlan(scenes=items)

    async def generate_metadata(self, script: ScriptDoc) -> VideoMetadata:
        refs = ("\n\nMga sanggunian:\n" + "\n".join(script.references)) if script.references else ""
        words = [w.strip(".,?!").lower() for w in script.topic.split() if len(w) > 3]
        return VideoMetadata(
            title=script.title[:100],
            description=f"{script.hook}\n\n{script.introduction}{refs}",
            tags=list(dict.fromkeys(words + [script.category, "tagalog", "edukasyon", "cartoon"]))[:15],
            hashtags=["#Tagalog", "#Edukasyon"])

    async def health_check(self, deep: bool = False) -> HealthResult:
        return HealthResult(True, "always available")
