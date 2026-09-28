import json
import requests

from config import API_KEY, MODEL


URL = "https://api.groq.com/openai/v1/chat/completions"


SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "title": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "number"}
                },
                "required": [
                    "candidate_id",
                    "start",
                    "end",
                    "title",
                    "reason",
                    "score"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["clips"],
    "additionalProperties": False
}


def validate(candidates):
    prompt = """
You are an expert short-form podcast editor.

Evaluate the candidates and return ONLY genuinely strong
standalone moments.

For each selected candidate:

- Understand the surrounding context.
- Determine the natural START.
- Determine the natural END.
- Include setup when necessary.
- Include explanation, reveal, result, or payoff.
- Never cut through a sentence or thought.
- Do not add irrelevant material.
- Final duration MUST be 25-70 seconds.
- Prefer 30-60 seconds.
- START and END MUST remain inside AVAILABLE_CONTEXT.
- Do not invent timestamps.
- PREFILTER_FINAL_MARKER is the deterministic baseline produced by PREFILTER.
- SAFE_START_BOUNDARIES and SAFE_END_BOUNDARIES are hard timestamp constraints.
- START MUST correspond to a SAFE_START_BOUNDARIES value.
- END MUST correspond to a SAFE_END_BOUNDARIES value.
- PREFILTER_FINAL_MARKER is a comparison baseline, not a command to copy blindly.
- Reject weak or context-dependent moments.

Do not force a fixed number of clips.
Quality is more important than quantity.

Return JSON only.

Each clip must contain:
candidate_id
start
end
title
reason
score

score = 0-100.

CANDIDATES:
"""

    for c in candidates:
        text = " ".join(c["text"].split())

        if len(text.split()) > 160:
            text = " ".join(text.split()[:160]) + "..."

        prompt += (
            f"\n\nCANDIDATE {c['id']}\n"
            f"ANCHOR: {c['anchor_start']:.1f}-{c['anchor_end']:.1f}\n"
            f"AVAILABLE_CONTEXT: "
            f"{c['context_start']:.1f}-{c['context_end']:.1f}\n"
            f"PREFILTER_FINAL_MARKER: {c.get('prefilter_marker')}\n"
            f"SAFE_START_BOUNDARIES: {c.get('safe_start_boundaries', [])}\n"
            f"SAFE_END_BOUNDARIES: {c.get('safe_end_boundaries', [])}\n"
            f"TEXT: {text}"
        )

    try:
        response = requests.post(
            URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_completion_tokens": 900,
                "reasoning_effort": "low",
                "reasoning_format": "hidden",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "clip_validation",
                        "strict": True,
                        "schema": SCHEMA
                    }
                }
            },
            timeout=120
        )

        if response.status_code != 200:
            print("[VALIDATOR ERROR]", response.text[:500])
            return []

        content = (
            response.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )

        data = json.loads(content)
        candidate_map = {c["id"]: c for c in candidates}
        final = []

        for clip in data.get("clips", []):
            try:
                c = candidate_map[int(clip["candidate_id"])]

                raw_start = float(clip["start"])
                raw_end = float(clip["end"])

                if not (
                    c["context_start"] <= raw_start <= c["context_end"]
                    and c["context_start"] <= raw_end <= c["context_end"]
                ):
                    print(
                        f"[BOUNDARY REJECT] candidate={c['id']} "
                        f"outside_context={raw_start:.3f}-{raw_end:.3f}"
                    )
                    continue

                def canonical_safe_boundary(value, boundaries):
                    for boundary in boundaries:
                        if abs(value - float(boundary)) <= 0.05:
                            return round(float(boundary), 3)
                    return None

                start = canonical_safe_boundary(
                    raw_start,
                    c.get("safe_start_boundaries", [])
                )
                end = canonical_safe_boundary(
                    raw_end,
                    c.get("safe_end_boundaries", [])
                )

                if start is None or end is None:
                    print(
                        f"[BOUNDARY REJECT] candidate={c['id']} "
                        f"unsafe={raw_start:.3f}-{raw_end:.3f}"
                    )
                    continue

                duration = end - start

                if not 25 <= duration <= 70:
                    continue

                marker = c.get("prefilter_marker")
                boundary_match = False

                if marker:
                    boundary_match = (
                        abs(start - float(marker["start"])) <= 0.001
                        and abs(end - float(marker["end"])) <= 0.001
                    )

                print(
                    f"[BOUNDARY COMPARE] candidate={c['id']} "
                    f"PREFILTER={marker} "
                    f"GEMINI={start:.3f}-{end:.3f} "
                    f"match={boundary_match}"
                )

                final.append({
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "duration": round(duration, 1),
                    "prefilter_start": (
                        round(float(marker["start"]), 1)
                        if marker else None
                    ),
                    "prefilter_end": (
                        round(float(marker["end"]), 1)
                        if marker else None
                    ),
                    "boundary_match": boundary_match,
                    "title": str(clip["title"]).strip(),
                    "reason": str(clip["reason"]).strip(),
                    "score": max(
                        0,
                        min(100, float(clip["score"]))
                    )
                })

            except (KeyError, TypeError, ValueError):
                continue

        return final

    except Exception as exc:
        print("[VALIDATOR ERROR]", exc)
        return []
