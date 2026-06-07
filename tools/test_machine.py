"""
Unit-tests for Half68k processor model.
Check instructions execution and their impact on registers/flags.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import machine
from machine import DATA_MEM_SIZE, Processor


def make_code(code: list[int], code_start: int = 0x1000) -> dict[int, int]:
    """Create code dictionary from words list."""
    return {code_start + i * 4: w for i, w in enumerate(code)}


def run_program(
    code_words: list[int], data_words: list[int] | None = None, input_bytes: bytes = b"", code_start: int = 0x1000, superscalar: bool = True
) -> Processor:
    """Executes processor on provided code and return Processor obj."""
    if data_words is None:
        data_words = []
    code_dict = make_code(code_words, code_start)
    proc = machine.Processor(code_dict, data_words, code_start, input_bytes, superscalar=superscalar)
    proc.run()
    return proc


# Tested instruction: die


def test_die() -> None:
    # Simplest program - die
    code = [
        0b010100_0_00000_00000_000000000000000,  # (opcode die = 0b010100)
    ]
    proc = run_program(code, [])
    assert proc.halted
    assert proc.clock == 1


# Tested instruction: mv


def test_mv_imm_reg() -> None:
    # mv.l #42, R0  =>  R0 = 42
    # opcode: mv = 0b000001, size .l = 0, src=imm (00 000), dst=R0 (01 000)
    opcode = (0b000001 << 26) | (0 << 25) | (0b00000 << 20) | (0b01000 << 15)
    code = [
        opcode,
        42,  # imm = 42
        0b010100_0_00000_00000_000000000000000,
    ]  # die
    proc = run_program(code, [])
    assert proc.dp.get_reg(0) == 42
    assert not proc.dp.flags.N
    assert not proc.dp.flags.Z


def test_mv_reg_reg() -> None:
    # mv.l R0, R1  (R0=42 заранее)
    # opcode: mv .l, src=R0 (01 000), dst=R1 (01 001)
    opcode = (0b000001 << 26) | (0 << 25) | (0b01000 << 20) | (0b01001 << 15)
    # First load 42 into R0, then move to R1, then die
    code = [
        0b000001_0_00000_01000_000000000000000,  # mv.l #42, R0 (imm=42)
        42,
        opcode,
        0b010100_0_00000_00000_000000000000000,  # die
    ]
    proc = run_program(code, [])
    assert proc.dp.get_reg(0) == 42
    assert proc.dp.get_reg(1) == 42


# Tested instructions: add/sub/cmp - arithmetic


def test_add_imm_reg() -> None:
    # add.l #1, R0  (R0=41 from the start)
    code = [
        0b000001_0_00000_01000_000000000000000,  # mv.l #41, R0
        41,
        0b000010_0_00000_01000_000000000000000,  # add.l #1, R0
        1,
        0b010100_0_00000_00000_000000000000000,  # die
    ]
    proc = run_program(code, [])
    assert proc.dp.get_reg(0) == 42
    assert not proc.dp.flags.Z
    assert not proc.dp.flags.N


def test_sub_imm_reg() -> None:
    # sub.l #1, R0  (R0=42 from the start)
    code = [
        0b000001_0_00000_01000_000000000000000,  # mv.l #42, R0
        42,
        0b000011_0_00000_01000_000000000000000,  # sub.l #1, R0
        1,
        0b010100_0_00000_00000_000000000000000,  # die
    ]
    proc = run_program(code, [])
    assert proc.dp.get_reg(0) == 41
    assert not proc.dp.flags.C  # no carry


def test_cmp_imm_reg() -> None:
    # cmp.l #42, R0  (R0=42) → Z=1
    code = [
        0b000001_0_00000_01000_000000000000000,  # mv.l #42, R0
        42,
        0b000100_0_00000_01000_000000000000000,  # cmp.l #42, R0
        42,
        0b010100_0_00000_00000_000000000000000,  # die
    ]
    proc = run_program(code, [])
    assert proc.dp.get_reg(0) == 42  # did not change
    assert proc.dp.flags.Z


# Tested instructions: jmp/beq/jsr/rts - transitions


def test_jmp() -> None:
    # jmp skips die and executes mv.l #99, R0
    # Instruction index: 3 (after jmp(2) + die(1) = 3)
    target = 0x1000 + 3 * 4  # 0x100C
    code = [
        0b010001_0_00000_00000_000000000000000,
        target,
        0b010100_0_00000_00000_000000000000000,  # die (must be skipped)
        # 0x100C:
        0b000001_0_00000_01000_000000000000000,
        99,
        0b010100_0_00000_00000_000000000000000,  # die2 (must be executed)
    ]
    proc = run_program(code)
    assert proc.halted
    assert proc.dp.get_reg(0) == 99


def test_beq_taken() -> None:
    # beq label (Z=1) → переход на label, где mv.l #1, R0
    code = [
        0b000001_0_00000_01000_000000000000000,  # mv.l #0, R0
        0,
        0b000100_0_00000_01000_000000000000000,  # cmp.l #0, R0
        0,
        0b010111_0_00000_00000_000000000000000,  # beq 0x101C
        0x101C,
        0b010100_0_00000_00000_000000000000000,  # die (must be skipped)
        # 0x101C:
        0b000001_0_00000_01000_000000000000000,  # mv.l #1, R0
        1,
        0b010100_0_00000_00000_000000000000000,  # die2 (must be executed)
    ]
    proc = run_program(code)
    assert proc.halted
    assert proc.dp.get_reg(0) == 1  # means transition was successful


def test_beq_not_taken() -> None:
    # beq label (Z=0) → do not go, execute mv.l #2, R0
    code = [
        0b000001_0_00000_01000_000000000000000,  # mv.l #1, R0  (Z=0)
        1,
        0b000100_0_00000_01000_000000000000000,  # cmp.l #0, R0
        0,
        0b010111_0_00000_00000_000000000000000,  # beq 0x101C
        0x101C,
        0b000001_0_00000_01000_000000000000000,  # mv.l #2, R0
        2,
        0b010100_0_00000_00000_000000000000000,  # die
    ]
    proc = run_program(code)
    assert proc.halted
    assert proc.dp.get_reg(0) == 2  # means transition was not applied


def test_jsr_rts() -> None:
    # jsr my_func → my_func: mv.l #3, R0 → rts → die
    # Subroute index: 3 (after jsr(2) + die(1) = 3)
    target = 0x1000 + 3 * 4  # 0x100C
    code = [
        0b010010_0_00000_00000_000000000000000,
        target,
        0b010100_0_00000_00000_000000000000000,  # die (must be returned here to halt)
        # 0x100C:
        0b000001_0_00000_01000_000000000000000,
        3,
        0b010011_0_00000_00000_000000000000000,  # rts
    ]
    proc = run_program(code)
    assert proc.halted
    assert proc.dp.get_reg(0) == 3
    expected_sp = DATA_MEM_SIZE * 4 - 4
    assert proc.dp.get_reg(7) == expected_sp
