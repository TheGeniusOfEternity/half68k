import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser import Parser
from preprocessor import preprocess

# Preprocessor


def test_define_replacement() -> None:
    lines = ["%define A 42", "mv.l #A, R0"]
    result = preprocess(lines)
    assert result == ["mv.l #42, R0"]


def test_macro_expansion() -> None:
    lines = ["%macro inc_r0", "    add.l #1, R0", "%endmacro", "inc_r0"]
    result = preprocess(lines)
    assert result == ["    add.l #1, R0"]


def test_ifdef_true() -> None:
    lines = ["%define DEBUG 1", "%ifdef DEBUG", "    mv.l #1, R0", "%else", "    mv.l #2, R0", "%endif"]
    result = preprocess(lines)
    assert result == ["    mv.l #1, R0"]


def test_ifdef_false() -> None:
    lines = ["%ifdef DEBUG", "    mv.l #1, R0", "%else", "    mv.l #2, R0", "%endif"]
    result = preprocess(lines)
    assert result == ["    mv.l #2, R0"]


def test_ifndef() -> None:
    lines = ["%define DEBUG 1", "%ifndef DEBUG", "    mv.l #1, R0", "%endif"]
    result = preprocess(lines)
    assert result == []


# Parser: addresses modes


def parse_one_line(line: str) -> list[int]:
    """Helper function: parses one instruction line in .code section"""
    prog_lines = [".code", ".org 0x1000", "start:", line, "die"]
    parser = Parser(prog_lines)
    program = parser.parse()
    return program.code[0].words


def test_register_mode() -> None:
    words = parse_one_line("mv.l R0, R1")
    assert len(words) == 1
    # Check if registers codes are contained in opcode (src=R0, dst=R1)
    assert words[0] == 0x04848000


def test_immediate_mode() -> None:
    words = parse_one_line("mv.l #42, R1")
    assert len(words) == 2
    assert words[1] == 42


def test_indirect_mode() -> None:
    words = parse_one_line("mv.l (R0), R1")
    assert len(words) == 1


def test_postinc_mode() -> None:
    words = parse_one_line("mv.b (R0)+, R1")
    assert len(words) == 2  # opcode + extended word for register
    # extended word contains R0 (code 0) in bits [19:16]
    assert (words[1] >> 16) & 0x7 == 0  # R0 = 0


def test_predec_mode() -> None:
    words = parse_one_line("mv.b -(SP), R0")
    assert len(words) == 2
    # SP equals 7
    assert (words[1] >> 16) & 0x7 == 7


def test_displacement_mode() -> None:
    words = parse_one_line("mv.l 8(R0), R1")
    assert len(words) == 2  # opcode + extended word with shift
    assert words[1] & 0xFFFF == 8
    assert (words[1] >> 16) & 0x7 == 0  # R0


def test_absolute_mode() -> None:
    words = parse_one_line("mv.l (0x1000), R0")
    assert len(words) == 2
    assert words[1] == 0x1000


# Data generation


def test_db_directive() -> None:
    lines = [".data", "db 1,2,3", ".code", ".org 0x1000", "start:", "die"]
    parser = Parser(lines)
    program = parser.parse()
    assert len(program.data) == 3
    assert program.data == [1, 2, 3]


def test_pstr_directive() -> None:
    lines = [".data", 'msg: pstr "Hi"', ".code", ".org 0x1000", "start:", "die"]
    parser = Parser(lines)
    program = parser.parse()
    assert len(program.data) == 3
    assert program.data == [2, ord("H"), ord("i")]


# Labels and transitions


def test_jump_label() -> None:
    lines = [".code", ".org 0x1000", "start:", "jmp start"]
    parser = Parser(lines)
    program = parser.parse()
    # jmp takes 2 words: opcode + address
    assert len(program.code[0].words) == 2
    # transition address must be 0x1000
    assert program.code[0].words[1] == 0x1000


def test_forward_label() -> None:
    lines = [".code", ".org 0x1000", "jmp end", "end:", "die"]
    parser = Parser(lines)
    program = parser.parse()
    # jmp end: end address = 0x1002 (jmp takes 2 words)
    assert program.code[0].words[1] == 0x1002


if __name__ == "__main__":
    pytest.main([__file__])
