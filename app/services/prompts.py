import json
from app.schemas.content import ScriptDoc, TopicRequest

SCRIPT_SYSTEM = """You are a scriptwriter for short educational cartoon explainer videos in natural, conversational Filipino (Tagalog) with light humor.
Rules:
- Write all narration in Tagalog. Technical terms may stay in English.
- Do not invent facts, dates, numbers, quotes, or events. If you are not sure something is true, leave it out.
- Clearly separate established facts from speculation (for example "pinaniniwalaan ng mga eksperto", "posible na").
- Do not copy existing scripts, characters, or distinctive jokes.
- Every scene's narration must be different and move the story forward.
- Use only these recurring characters: "juan" (curious boy) and "mara" (witty older sister).
Return ONLY one JSON object. No markdown, no commentary. It must match this shape exactly:
{
  "title": "string, max 100 chars, Tagalog, not misleading",
  "topic": "string",
  "category": "string",
  "target_audience": "string",
  "hook": "opening hook sentence",
  "introduction": "short introduction",
  "scenes": [
    {"narration": "Tagalog narration", "on_screen_text": "short label or null",
     "visual": "what is drawn in this scene (English)", "characters": ["juan"],
     "sound_effects": ["pop"], "transition": "cut|fade|slide", "est_seconds": 12}
  ],
  "conclusion": "string",
  "call_to_action": "string",
  "references": ["trustworthy source names or URLs, empty list if none"],
  "est_duration_seconds": 240
}"""


def script_prompt(req: TopicRequest) -> str:
    n = max(6, min(20, req.target_seconds // 20))
    pts = "\n".join(f"- {p}" for p in req.key_points) or "- (none supplied; use only well-established facts)"
    return (f"Topic: {req.title}\nCategory: {req.category}\nTarget length: about {req.target_seconds} seconds "
            f"(about {n} scenes).\nKey points to cover:\n{pts}\nReturn the JSON object now.")


SCENE_PLAN_SYSTEM = """You plan the visuals of a cartoon video from its scenes. Return ONLY one JSON object, no markdown:
{"scenes": [{"scene_index": 1, "background": "short background name", "characters":
 [{"character_id": "juan", "pose": "stand", "expression": "happy", "position": "left"}],
 "props": ["book"], "camera": "static|zoom_in|zoom_out|pan_left|pan_right", "speech_bubble": "short text or null"}]}
Rules: exactly one entry per input scene, in order; character_id must be "juan" or "mara"; position is left, center or right."""


def scene_plan_prompt(script: ScriptDoc) -> str:
    items = [{"scene_index": s.index, "visual": s.visual, "characters": s.characters} for s in script.scenes]
    return "Scenes:\n" + json.dumps(items, ensure_ascii=False)


METADATA_SYSTEM = """You write YouTube metadata in Filipino (Tagalog). Do not mislead or invent facts. Return ONLY one JSON object:
{"title": "max 100 chars", "description": "2-4 short paragraphs, max 4000 chars", "tags": ["up to 15 tags"],
 "hashtags": ["up to 3, without spaces"], "category_id": "27"}"""


def metadata_prompt(script: ScriptDoc) -> str:
    return json.dumps({"title": script.title, "topic": script.topic, "hook": script.hook,
                       "introduction": script.introduction, "references": script.references},
                      ensure_ascii=False)
