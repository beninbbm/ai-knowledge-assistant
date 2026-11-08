"""Find the [n] citations in a model's answer and check them against the real sources.

Small models are imperfect at citing: they may write [Source 2], [1, 3], or cite a
number that doesn't exist. We normalise what we can ([1][3]) and drop citations to
sources the model never received, so every citation shown is backed by a real passage.
"""

import re

# [1]  [1, 3]  [1][3]  [Source 2]  [sources 1 and 4]
_CITATION = re.compile(
    r"\s?\[(?:sources?\s*)?(\d+(?:\s*(?:,|;|and|&)\s*(?:sources?\s*)?\d+)*)\]", re.IGNORECASE
)

_RUN = re.compile(r"(?:\[\d+\])+")


def extract_citations(answer: str, source_count: int) -> tuple[str, list[int]]:
    """Return (cleaned answer, cited source numbers in order of first appearance)."""
    cited: list[int] = []

    def replace(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", match.group(1))]
        valid = [n for n in numbers if 1 <= n <= source_count]
        for n in valid:
            if n not in cited:
                cited.append(n)
        if not valid:
            return ""  # citation to a source that doesn't exist: remove it
        lead = " " if match.group(0)[0].isspace() else ""
        return lead + "".join(f"[{n}]" for n in dict.fromkeys(valid))

    cleaned = _CITATION.sub(replace, answer)
    # Collapse repeats within a run of adjacent citations: "[1][3][1]" -> "[1][3]".
    cleaned = _RUN.sub(
        lambda m: "".join(dict.fromkeys(re.findall(r"\[\d+\]", m.group(0)))), cleaned
    )
    return cleaned.strip(), cited
