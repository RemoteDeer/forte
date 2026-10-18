import json
from functools import lru_cache
from pathlib import Path

from .schemas import Rule


@lru_cache
def catalog() -> dict[str, Rule]:
    data = json.loads(Path(__file__).with_name("rules.json").read_text(encoding="utf-8"))
    return {item["id"]: Rule.model_validate(item) for item in data}
