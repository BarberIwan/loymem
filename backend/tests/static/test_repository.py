"""Static guards on the whole repository: no provider names in the core, no
banned copy, no raw design values, no tool attribution."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "spec",
}
TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".css",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".txt",
    ".html",
    ".mako",
}
LOCKFILES = {"pnpm-lock.yaml", "package-lock.json"}

PROVIDERS = [
    "salonized",
    "treatwell",
    "fresha",
    "booksy",
    "timely",
    "setmore",
    "planity",
    "phorest",
    "shore",
    "acuity",
    "calendly",
    "simplybook",
    "mindbody",
]

BANNED_COPY = [
    "ontgrendel",
    "naadloos",
    "moeiteloos",
    "hoger niveau",
    "snel veranderende",
    "unlock",
    "seamless",
    "effortless",
    "next level",
    "elevate",
    "supercharge",
    "game-changer",
    "game changer",
    "revolution",
    "ai-powered",
    "magic",
]
EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️]")
DASHES = re.compile("[—–]")

AI_MARKERS = re.compile(
    r"co-authored-by|generated with|\bclaude\b|anthropic|chatgpt|openai|\bcopilot\b|"
    r"\bgpt-\d|\bllm\b|\bai-generated\b",
    re.IGNORECASE,
)


def files(*roots: str, suffixes: set[str] = TEXT_SUFFIXES) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        for p in (ROOT / root).rglob("*"):
            if (
                p.is_file()
                and p.suffix in suffixes
                and p.name not in LOCKFILES
                and not SKIP_DIRS & set(p.relative_to(ROOT).parts)
            ):
                out.append(p)
    return out


def test_core_has_no_provider_names() -> None:
    offenders = []
    for p in files("backend/app", "frontend/src", "frontend/messages"):
        if "integrations" in p.relative_to(ROOT).parts:
            continue
        text = p.read_text(encoding="utf-8").lower()
        offenders += [
            f"{p.relative_to(ROOT)}: {name}"
            for name in PROVIDERS
            if re.search(rf"\b{name}\b", text)
        ]
    assert offenders == []


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def test_copy_has_no_banned_phrases() -> None:
    problems = []
    for locale in ("nl", "en"):
        path = ROOT / "frontend" / "messages" / f"{locale}.json"
        for s in _strings(json.loads(path.read_text(encoding="utf-8"))):
            low = s.lower()
            problems += [f"{locale}: '{w}' in '{s}'" for w in BANNED_COPY if w in low]
            if "!" in s:
                problems.append(f"{locale}: uitroepteken in '{s}'")
            if EMOJI.search(s):
                problems.append(f"{locale}: emoji in '{s}'")
            if DASHES.search(s):
                problems.append(f"{locale}: gedachtestreepje in '{s}'")
    assert problems == []


def test_messages_have_the_same_keys() -> None:
    def keys(node: object, prefix: str = "") -> set[str]:
        if isinstance(node, dict):
            return {k for key, v in node.items() for k in keys(v, f"{prefix}{key}.")}
        return {prefix.rstrip(".")}

    nl, en = (
        json.loads((ROOT / "frontend/messages" / f"{x}.json").read_text()) for x in ("nl", "en")
    )
    assert keys(nl) == keys(en)


RAW_VALUE = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|(?<![\w-])\d*\.?\d+(px|rem|em|ms|s)\b"
)


def test_no_raw_colour_or_spacing_outside_tokens() -> None:
    offenders = []
    for p in files("frontend/src", suffixes={".css", ".tsx", ".ts"}):
        if p.name == "tokens.css":
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = re.sub(r"//.*|/\*.*?\*/", "", line)
            if code.lstrip().startswith("@media"):
                continue  # custom properties do not work in media queries
            if p.suffix != ".css" and "style=" not in code:
                continue
            for m in RAW_VALUE.finditer(code):
                if m.group(0) in {"0px", "0s"}:
                    continue
                offenders.append(f"{p.relative_to(ROOT)}:{n}: {m.group(0)}")
    assert offenders == []


def test_repo_has_no_ai_attribution() -> None:
    offenders = []
    for p in files(".", suffixes=TEXT_SUFFIXES):
        if p.name == "test_repository.py":
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if AI_MARKERS.search(line):
                offenders.append(f"{p.relative_to(ROOT)}:{n}")
    log = subprocess.run(
        ["git", "log", "--format=%an%n%ae%n%B"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    if AI_MARKERS.search(log):
        offenders.append("git log")
    assert offenders == []
