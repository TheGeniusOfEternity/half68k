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
                lines.append(f"DATA {addr + i:08X} - {format_hex_word(word)}")
            data_offset += n
        elif item.kind == "pstr":
            s = str(item.values[0])  # string
            n = 1 + len(s)
            for i in range(n):
                word = program.data[data_offset + i]
                lines.append(f"DATA {addr + i:08X} - {format_hex_word(word)}")
            data_offset += n
    # Code
    for instr in program.code:
        for i, word in enumerate(instr.words):
            lines.append(f"CODE {instr.addr + i:08X} - {format_hex_word(word)} - {instr.mnemonic if i == 0 else ''}")
    with Path.open(log_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_binary(program: Program, bin_path: Path) -> None:
    """
    Saves binary fil in format:
    [4 bytes: size of 'data' in words (little-endian)]
    [data: words of data]
    [code: words of instructions]
    """
    data_words = program.data
    code_words = []
    for instr in program.code:
        code_words.extend(instr.words)

    with Path.open(bin_path, "wb") as f:
        # Header: words of data
        f.write(struct.pack("<I", len(data_words)))
        # Data
        for word in data_words:
            f.write(struct.pack("<I", word & 0xFFFFFFFF))
        for word in code_words:
            f.write(struct.pack("<I", word & 0xFFFFFFFF))


def main() -> None:
    args_num = 3
    if len(sys.argv) != args_num:
        print("Usage: translator.py <input.s> <output.bin>")
        sys.exit(1)

    asm_path = Path(sys.argv[1])
    bin_path = Path(sys.argv[2])
    log_path = bin_path.with_suffix(".log")

    # Read source file
    with Path.open(asm_path, encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Preprocessor
    processed_lines = preprocess(raw_lines)

    # Parser
    parser = Parser(processed_lines)
    program = parser.parse()

    # Output files generation
    write_binary(program, bin_path)
    generate_log(program, log_path)
    print(f"Translation complete: {bin_path}, {log_path}")


if __name__ == "__main__":
    main()
