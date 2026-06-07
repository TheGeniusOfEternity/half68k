import os
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import machine
import translator


def load_golden_tests() -> list[dict[str, Any]]:
    """Loads golden tests YAML-files"""
    tests = []
    golden_dir = Path(__file__).parent.parent / "golden"
    for yaml_file in sorted(golden_dir.glob("*.yml")):
        with Path.open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["name"] = yaml_file.stem
        tests.append(data)
    return tests


def strip_lines(text: str) -> str:
    """Removes spaces from the end of each line."""
    return "\n".join(line.rstrip() for line in text.splitlines())


def match_log(actual: str, expected: str) -> bool:
    """
    Compares machine log with expected.
    If expected log contains '...' then check part before and after.
    """
    if "\n...\n" in expected:
        head, tail = expected.split("\n...\n", 1)
        return actual.startswith(head) and actual.endswith(tail)
    return actual == expected


@pytest.mark.parametrize("golden", load_golden_tests(), ids=lambda g: g["name"])
def test_golden(golden: dict[str, Any], tmp_path: Path) -> None:
    """Checks translator and machine by expected golden test."""
    # Prepare files
    source_path = tmp_path / "source.s"
    target_path = tmp_path / "target.bin"
    input_path = tmp_path / "input.txt"

    source_path.write_text(golden["in_source"], encoding="utf-8")

    if "in_text" in golden:
        input_path.write_text(golden["in_text"], encoding="utf-8")
        input_arg = str(input_path)
    else:
        input_arg = ""

    # Translation
    translator.main([str(source_path), str(target_path)])

    # Translation log
    log_path = target_path.with_suffix(".log")
    code_log = strip_lines(log_path.read_text(encoding="utf-8"))

    # Simulation (with superscalar)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        machine_args = [str(target_path), input_arg]
        machine.main(machine_args)
    finally:
        os.chdir(old_cwd)

    machine_log = strip_lines((tmp_path / "journal.log").read_text(encoding="utf-8"))

    # Assertion
    assert code_log == strip_lines(golden["out_code_log"]), "Лог транслятора не совпадает"
    assert match_log(machine_log, strip_lines(golden["out_log"])), "Журнал модели не совпадает"
