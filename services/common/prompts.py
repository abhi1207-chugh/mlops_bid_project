"""Versioned prompt loader. Prompts live in prompts/<name>/vN.md; the version used is recorded with every response."""
from __future__ import annotations

import os
import re

from common.config import get_settings


def load_prompt(name: str, version: str | None = None, **variables: str) -> tuple[str, str]:
    if version is None:
        version = get_settings().prompt_version
    path = os.path.join(get_settings().prompts_dir, name, f"{version}.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    missing = re.findall(r"\{\{(\w+)\}\}", text)
    if missing:
        raise ValueError(f"prompt {name}/{version}: unfilled variables {sorted(set(missing))}")
    return text, f"{name}/{version}"
