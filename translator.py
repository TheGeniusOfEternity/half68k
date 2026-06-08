#!/usr/bin/env python3
"""
Half68k Translator
Usage: translator.py input.s output.bin
"""

import struct
import sys
from pathlib import Path

from parser import Parser, Program
from preprocessor import preprocess


def format_hex_word(word: int) -> str:
    """Formats 32-bit word as 8-symbol HEX-string."""
    return f"{word & 0xFFFFFFFF:08X}"


def generate_log(program: Program, log_path: Path) -> None:
    """
    Generates text debugging dump.
    Format: <address> - <HEXCODE> - <mnemonic>
    """
    lines = []
    # Data: use data_items for correct addresses
    data_offset = 0
    for item in program.data_items:
        addr = item.addr
        if item.kind in ("db", "dw"):
            n = len(item.values)
            for i in range(n):
                word = program.data[data_offset + i]
                lines.append(f"DATA {addr + i * 4:08X} - {format_hex_word(word)}")
            data_offset += n
        elif item.kind == "pstr":
            s = str(item.values[0])  # string
            n = 1 + len(s)
            for i in range(n):
                word = program.data[data_offset + i]
                lines.append(f"DATA {addr + i * 4:08X} - {format_hex_word(word)}")
            data_offset += n
    # Code
    for instr in program.code:
        for i, word in enumerate(instr.words):
            lines.append(f"CODE {instr.addr + i * 4:08X} - {format_hex_word(word)} - {instr.mnemonic if i == 0 else ''}")
    with log_path.open("w") as f:
        if lines:
            f.write("\n".join(lines) + "\n")


def write_binary(program: Program, bin_path: Path) -> None:
    """
    Saves binary file in format:
    [4 bytes: size of 'data' in words (little-endian)]
    [data: words of data]
    [code: words of instructions]
    """
    data_words = program.data
    code_words = []
    for instr in program.code:
        code_words.extend(instr.words)

    with bin_path.open("wb") as f:
        # Header: words of data
        f.write(struct.pack("<I", len(data_words)))
        # Header: code start address
        code_start_addr = program.code[0].addr if program.code else 0
        f.write(struct.pack("<I", code_start_addr))
        # Data
        for word in data_words:
            f.write(struct.pack("<I", word & 0xFFFFFFFF))
        for word in code_words:
            f.write(struct.pack("<I", word & 0xFFFFFFFF))


def main(cmd_args: None | list[str] = None) -> None:
    if cmd_args is None:
        cmd_args = sys.argv[1:]
    if len(cmd_args) < 2:
        print("Usage: translator.py <input.s> <output.bin> [-DNAME1] [-DNAME2] ...")
        sys.exit(1)

    src_path = Path(cmd_args[0])
    bin_path = Path(cmd_args[1])
    log_path = bin_path.with_suffix(".log")

    # Collect flags: args that start with -D
    defines: dict[str, str] = {}
    for arg in cmd_args[2:]:
        if arg.startswith("-D"):
            flag_name = arg[2:]
            if flag_name:
                defines[flag_name] = "1"

    # Read source file
    with src_path.open(encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Preprocessor
    processed_lines = preprocess(raw_lines, defines=defines)

    # Parser
    parser = Parser(processed_lines)
    program = parser.parse()

    # Output files generation
    write_binary(program, bin_path)
    generate_log(program, log_path)
    print(f"Translation complete: {bin_path}, {log_path} (Flags: {list(defines.keys())})")


if __name__ == "__main__":
    main()
