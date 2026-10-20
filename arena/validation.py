"""Fail closed on malformed model output rather than inventing winners."""

import json
import math

from .bracket import WEIGHTS
from .config import ArenaError


def parse_json(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    elif text.startswith("```\n") and text.endswith("```"):
        text = text[4:-3].strip()
    try:
        value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except ValueError:
        raise ArenaError("Return one valid JSON object, without commentary or non-finite numbers.") from None
    if not isinstance(value, dict):
        raise ArenaError("Response must be a JSON object.")
    return value


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ArenaError(f"{name} must be a nonempty string.")


def validate_result(kind, value):
    if kind in ("competitor", "assistant"):
        nonempty(value.get("solution"), "solution")
    elif kind == "attacker":
        attacks = value.get("attacks")
        if not isinstance(attacks, list) or len(attacks) > 7:
            raise ArenaError("attacks must be a list of at most seven attacks.")
        for attack in attacks:
            if not isinstance(attack, dict) or attack.get("severity") not in ("FATAL", "MAJOR", "MINOR"):
                raise ArenaError("Each attack needs severity FATAL, MAJOR, or MINOR.")
            nonempty(attack.get("claim"), "attack claim")
            nonempty(attack.get("evidence"), "attack evidence")
    elif kind == "defender":
        nonempty(value.get("defense"), "defense")
        nonempty(value.get("solution"), "solution")
    elif kind in ("judge", "final"):
        scores = value.get("scores")
        if not isinstance(scores, dict) or set(scores) != {"X", "Y"}:
            raise ArenaError("Judge scores must contain exactly X and Y.")
        for label in ("X", "Y"):
            score = scores[label]
            if not isinstance(score, dict):
                raise ArenaError("Each score must be an object.")
            for key, _ in WEIGHTS:
                v = score.get(key)
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 10:
                    raise ArenaError(f"{label}.{key} must be a finite number from 0 to 10.")
            if type(score.get("fatal")) is not bool:
                raise ArenaError("fatal must be true or false.")
            if score["fatal"]:
                nonempty(score.get("fatal_evidence"), "fatal_evidence")
        if value.get("winner") not in ("X", "Y"):
            raise ArenaError("Judge winner must be X or Y.")
        nonempty(value.get("reason"), "reason")
    else:
        raise ArenaError("Unknown job kind.")
    return value


def envelope(value):
    if value.get("action") == "tool":
        nonempty(value.get("name"), "tool name")
        if not isinstance(value.get("arguments"), dict):
            raise ArenaError("Tool arguments must be an object.")
    elif value.get("action") == "answer":
        if not isinstance(value.get("result"), dict):
            raise ArenaError("Answer needs a result object.")
    else:
        raise ArenaError("action must be tool or answer.")
    return value
