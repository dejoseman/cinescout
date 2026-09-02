#!/usr/bin/env python
"""Assert that no prohibited AI provider is present in the dependency tree.

The hackathon rules permit Google Cloud AI and named partner capabilities only.
This script fails if a disallowed provider SDK appears in the requirements, the
frontend manifest, or the installed environment.

    python scripts/check_dependencies.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Package name fragments that would indicate a prohibited provider.
PROHIBITED = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "cohere": "Cohere",
    "mistralai": "Mistral",
    "replicate": "Replicate",
    "boto3": "AWS SDK (Bedrock risk)",
    "botocore": "AWS SDK (Bedrock risk)",
    "azure-ai": "Microsoft Azure AI",
    "azure-openai": "Microsoft Azure OpenAI",
    "huggingface-hub": "Hugging Face inference",
    "langchain": "third-party agent framework",
    "llama-index": "third-party agent framework",
    "crewai": "third-party agent framework",
    "autogen": "third-party agent framework",
}

#: Allowed even though they contain a flagged substring.
ALLOWLIST = {"google-adk", "google-genai", "google-cloud-aiplatform"}


def check_file(path: Path, extract) -> list[str]:
    if not path.exists():
        return []
    problems = []
    for name in extract(path.read_text(encoding="utf-8")):
        lowered = name.lower().strip()
        if lowered in ALLOWLIST:
            continue
        for fragment, label in PROHIBITED.items():
            if fragment in lowered:
                problems.append(f"{path.relative_to(ROOT)}: '{name}' -> {label}")
    return problems


def from_requirements(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-r")):
            continue
        names.append(re.split(r"[<>=!\[;]", line)[0])
    return names


def from_package_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [
        *data.get("dependencies", {}).keys(),
        *data.get("devDependencies", {}).keys(),
    ]


def main() -> int:
    problems: list[str] = []
    problems += check_file(ROOT / "backend/requirements.txt", from_requirements)
    problems += check_file(ROOT / "backend/requirements-dev.txt", from_requirements)
    problems += check_file(ROOT / "frontend/package.json", from_package_json)

    # Also inspect what is actually installed, which is what really runs.
    try:
        from importlib.metadata import distributions

        installed = {d.metadata["Name"] or "" for d in distributions()}
        for name in installed:
            lowered = name.lower()
            if lowered in ALLOWLIST:
                continue
            for fragment, label in PROHIBITED.items():
                if fragment in lowered:
                    problems.append(f"installed environment: '{name}' -> {label}")
    except Exception:  # noqa: BLE001 - metadata scanning is best effort
        print("note: could not scan the installed environment")

    if problems:
        print("PROHIBITED AI PROVIDERS DETECTED:\n")
        for problem in sorted(set(problems)):
            print(f"  - {problem}")
        return 1

    print("PASS  No prohibited AI provider found.")
    print("      Orchestration: Google ADK. Reasoning: Google Gemini.")
    print("      External retrieval: Parallel Search API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
