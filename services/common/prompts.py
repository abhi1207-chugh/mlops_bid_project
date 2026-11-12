"""Versioned prompt loader.

A per-agent override allows a controlled prompt experiment: for example, change
only COMPLIANCE_PROMPT_VERSION while keeping classifier and verifier fixed.
"""
from __future__ import annotations

import os
import re

from common.config import get_settings


def load_prompt(name: str, version: str | None = None, **variables: str) -> tuple[str, str]:
    if version is None:
        override = f"{name.upper()}_PROMPT_VERSION"
        version = os.getenv(override) or get_settings().prompt_version
    if not re.fullmatch(r"v[0-9]+", version):
        raise ValueError(f"invalid prompt version {version!r} for {name}")
    path = os.path.join(get_settings().prompts_dir, name, f"{version}.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    missing = re.findall(r"\{\{(\w+)\}\}", text)
    if missing:
        raise ValueError(f"prompt {name}/{version}: unfilled variables {sorted(set(missing))}")
    return text, f"{name}/{version}"
