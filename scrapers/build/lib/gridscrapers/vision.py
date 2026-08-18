"""Generic vision parser for SCADA-screenshot SLDCs.

Reusable infra: (image bytes, strict JSON schema, sane bounds) in → validated
dict out, or None + a quarantine reason. Built for the states whose only live
feed is a dashboard image (Maharashtra now; UP, Bihar, … later) — the plugin
just supplies the image URL, schema, and bounds.

Uses the Claude API (anthropic SDK) with structured outputs so the model
returns schema-conforming JSON, never prose. The prompt + schema + model are
hashed into `prompt_fingerprint`; the plugin's PARSER_VERSION must be bumped
whenever any of them change, so archived raw images re-parse reproducibly.

Auth: the SDK resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / CLI profile
from the environment. No key configured (e.g. this dev box) → parse_image
returns (None, "no API credentials"); the raw image is still archived.
"""

import base64
import hashlib
import json
from dataclasses import dataclass, field

MODEL = "claude-opus-4-8"
MAX_TOKENS = 2000


@dataclass(frozen=True)
class VisionSpec:
    """What one SCADA dashboard exposes and how to validate it."""

    name: str
    prompt: str
    schema: dict  # JSON Schema (object) for the model's structured output
    bounds: dict[str, tuple[float, float]]  # dotted path -> (min, max)
    # reconciliation: the dotted paths whose values must sum to `total_path`
    # within `tolerance` (fraction). Empty parts skip the check.
    reconcile_parts: tuple[str, ...] = ()
    total_path: str = ""
    tolerance: float = 0.10
    model: str = MODEL

    def fingerprint(self) -> str:
        blob = json.dumps([self.model, self.prompt, self.schema], sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _dig(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def validate(data: dict, spec: VisionSpec) -> list[str]:
    """Bounds + reconciliation. Returns violations (empty = clean)."""
    errs: list[str] = []
    for path, (lo, hi) in spec.bounds.items():
        v = _dig(data, path)
        if v is None:
            errs.append(f"missing {path}")
        elif not isinstance(v, (int, float)):
            errs.append(f"{path} not numeric: {v!r}")
        elif not (lo <= v <= hi):
            errs.append(f"{path}={v} out of [{lo}, {hi}]")
    if spec.reconcile_parts and spec.total_path and not errs:
        total = _dig(data, spec.total_path)
        part_sum = sum(_dig(data, p) or 0 for p in spec.reconcile_parts)
        if total and abs(part_sum - total) > spec.tolerance * abs(total):
            errs.append(
                f"reconcile: parts {part_sum:.1f} vs {spec.total_path} {total:.1f} "
                f"(> {spec.tolerance:.0%})"
            )
    return errs


def parse_image(
    image_bytes: bytes, media_type: str, spec: VisionSpec
) -> tuple[dict | None, str | None]:
    """Returns (validated_data, None) or (None, quarantine_reason).

    Never returns hallucinated numbers: a model output that fails bounds or
    reconciliation comes back as (None, reason) for quarantine.
    """
    try:
        import anthropic
    except ImportError:
        return None, "anthropic SDK not installed"

    try:
        client = anthropic.Anthropic()  # resolves credentials from env
    except Exception as e:
        return None, f"no API credentials: {e}"

    b64 = base64.standard_b64encode(image_bytes).decode()
    try:
        resp = client.messages.create(
            model=spec.model,
            max_tokens=MAX_TOKENS,
            output_config={"format": {"type": "json_schema", "schema": spec.schema}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": spec.prompt},
                ],
            }],
        )
    except Exception as e:
        return None, f"API error: {type(e).__name__}: {e}"

    if resp.stop_reason == "refusal":
        return None, "model refused"
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        return None, "empty model response"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"non-JSON output: {e}"

    errors = validate(data, spec)
    if errors:
        return None, "; ".join(errors)
    return data, None
