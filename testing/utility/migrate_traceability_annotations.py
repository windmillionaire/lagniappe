"""Rewrite legacy traceability behavior tags into matrix/pair clauses."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOTS = (
    "build",
    "config",
    "installer",
    "lagniappe",
    "runner",
    "run.py",
    "src",
    "testing",
)
SOURCE_SUFFIXES = {".js", ".mjs", ".py"}
TAG_LINE_RE = re.compile(
    r"^(?P<prefix>\s*(?:(?:#|//|\*)\s*)?)"
    r"@(?P<tag>[A-Za-z][A-Za-z0-9_-]*)"
    r"(?:\s+(?P<value>.*?))?"
    r"(?P<suffix>\s*)$"
)
BEHAVIOR_TAGS = {"feature", "features", "dimension", "dimensions", "pair", "pairs"}
TRACEABILITY_TAGS = BEHAVIOR_TAGS | {
    "covered-by",
    "manual",
    "matrix",
    "reason",
    "scaffold",
    "scaffolding",
    "source",
    "sources",
    "style",
    "styles",
    "template",
    "templates",
    "test",
    "testable",
    "tests",
    "todo",
    "todos",
}


def split_values(value: str) -> list[str]:
    return [part for part in re.split(r"[\s,]+", value.strip()) if part]


def parsed_tag(line: str) -> tuple[str, str, str] | None:
    match = TAG_LINE_RE.match(line.rstrip("\n"))
    if not match:
        return None
    tag = match.group("tag").lower().replace("_", "-")
    if tag not in TRACEABILITY_TAGS:
        return None
    return (
        tag,
        (match.group("value") or "").strip(),
        match.group("prefix"),
    )


def exact_cells(tagged_lines: list[tuple[str, str, str]]) -> set[tuple[str, str]]:
    features: list[str] = []
    dimensions: list[str] = []
    pairs: set[tuple[str, str]] = set()
    for tag, value, _ in tagged_lines:
        values = split_values(value)
        if tag in {"feature", "features"}:
            features.extend(values)
        elif tag in {"dimension", "dimensions"}:
            dimensions.extend(values)
        elif tag in {"pair", "pairs"}:
            for pair in values:
                if pair.count(":") != 1:
                    raise ValueError(f"malformed legacy pair {pair!r}")
                feature, dimension = pair.split(":", 1)
                if not feature or not dimension:
                    raise ValueError(f"malformed legacy pair {pair!r}")
                pairs.add((feature, dimension))
    if pairs:
        return pairs
    return {(feature, dimension) for feature in features for dimension in dimensions}


def canonical_lines(cells: set[tuple[str, str]], prefix: str) -> list[str]:
    by_feature: dict[str, set[str]] = defaultdict(set)
    for feature, dimension in cells:
        by_feature[feature].add(dimension)

    by_dimensions: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for feature, dimensions in by_feature.items():
        by_dimensions[tuple(sorted(dimensions))].append(feature)

    matrices: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    singletons: list[str] = []
    for dimensions, features in by_dimensions.items():
        sorted_features = tuple(sorted(features))
        if len(sorted_features) * len(dimensions) == 1:
            singletons.append(f"{sorted_features[0]}:{dimensions[0]}")
        else:
            matrices.append((sorted_features, dimensions))

    output = [
        f"{prefix}@matrix {' '.join(features)} : {' '.join(dimensions)}\n"
        for features, dimensions in sorted(matrices)
    ]
    singletons.sort()
    if len(singletons) == 1:
        output.append(f"{prefix}@pair {singletons[0]}\n")
    elif singletons:
        output.append(f"{prefix}@pairs {' '.join(singletons)}\n")
    return output


def rewrite_lines(lines: list[str], path: Path) -> tuple[list[str], list[str]]:
    output: list[str] = []
    issues: list[str] = []
    index = 0
    while index < len(lines):
        parsed = parsed_tag(lines[index])
        if parsed is None:
            output.append(lines[index])
            index += 1
            continue

        end = index
        block: list[tuple[int, tuple[str, str, str]]] = []
        while end < len(lines):
            item = parsed_tag(lines[end])
            if item is None:
                break
            block.append((end, item))
            end += 1

        behavior = [(line_no, item) for line_no, item in block if item[0] in BEHAVIOR_TAGS]
        if not behavior:
            output.extend(lines[index:end])
            index = end
            continue

        first_behavior = behavior[0][0]
        tagged_behavior = [item for _, item in behavior]
        try:
            cells = exact_cells(tagged_behavior)
        except ValueError as exc:
            issues.append(f"{path}:{index + 1}: {exc}")
            output.extend(lines[index:end])
            index = end
            continue

        if not cells:
            features = [
                value
                for tag, raw, _ in tagged_behavior
                if tag in {"feature", "features"}
                for value in split_values(raw)
            ]
            dimensions = [
                value
                for tag, raw, _ in tagged_behavior
                if tag in {"dimension", "dimensions"}
                for value in split_values(raw)
            ]
            if (
                path.as_posix().endswith("lagniappe/core/tools/database/core.py")
                and features == ["database", "storage"]
                and not dimensions
            ):
                cells = {("database", "adc"), ("storage", "adc")}
            else:
                issues.append(
                    f"{path}:{first_behavior + 1}: behavior tags need both axes"
                )
                output.extend(lines[index:end])
                index = end
                continue

        prefix = behavior[0][1][2]
        replacement = canonical_lines(cells, prefix)
        for line_no in range(index, end):
            if line_no == first_behavior:
                output.extend(replacement)
            if all(line_no != behavior_line for behavior_line, _ in behavior):
                output.append(lines[line_no])
        index = end

    return output, issues


def candidate_files(paths: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file() and path.suffix in SOURCE_SUFFIXES:
            files.add(path)
        elif path.is_dir():
            files.update(
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
                and candidate.suffix in SOURCE_SUFFIXES
                and "lagniappe/web/static" not in candidate.as_posix()
            )
    return sorted(files)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = args.paths or [REPO_ROOT / root for root in DEFAULT_ROOTS]
    changed: list[Path] = []
    issues: list[str] = []
    for path in candidate_files(
        [candidate if candidate.is_absolute() else REPO_ROOT / candidate for candidate in paths]
    ):
        original = path.read_text(encoding="utf-8").splitlines(keepends=True)
        rewritten, file_issues = rewrite_lines(original, path.relative_to(REPO_ROOT))
        issues.extend(file_issues)
        if rewritten == original:
            continue
        changed.append(path)
        if args.write:
            path.write_text("".join(rewritten), encoding="utf-8")

    for issue in issues:
        print(issue, file=sys.stderr)
    for path in changed:
        print(path.relative_to(REPO_ROOT))
    if issues or (args.check and changed):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
