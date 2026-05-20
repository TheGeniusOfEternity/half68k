#!/usr/bin/env python3
"""
Half68k Translator
Usage: translator.py input.asm output.bin
"""

import sys
import struct
from pathlib import Path

from preprocessor import preprocess
from parser import Parser


def format_hex_word(word: int) -> str:
    """Formats 32-bit word as 8-symbol HEX-string."""
    return f"{word:08X}"


def generate_log(program, log_path: Path) -> None:
    """
    Generates text debugging dump.
    Format: <address> - <HEXCODE> - <mnemonic>
    """
    lines = []
    # Data
    for addr, word in enumerate(program.data, start=0):
        hex_str = format_hex_word(word)
        lines.append(f"{addr:08X} - {hex_str} - data")
    # Code
    for instr in program.code:
        for i, word in enumerate(instr.words):
            addr = instr.addr + i
            hex_str = format_hex_word(word)
            # Use mnemonics only for first word of the instruction
            mnem = instr.mnemonic if i == 0 else ""
            lines.append(f"{addr:08X} - {hex_str} - {mnem}")
    with open(log_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_binary(program, bin_path: Path) -> None:
    """
    Saves binary file: sequence of 32-bit words in little-endian.
    Order: data first, then code.
    """
    words = []
    # Data
    words.extend(program.data)
    # Code (all words of all instructions)
    for instr in program.code:
        words.extend(instr.words)

    with open(bin_path, "wb") as f:
        for word in words:
            f.write(struct.pack("<I", word))


def main():
    if len(sys.argv) != 3:
        print("Usage: translator.py <input.s> <output.bin>")
        sys.exit(1)

    asm_path = Path(sys.argv[1])
    bin_path = Path(sys.argv[2])
    log_path = bin_path.with_suffix(".log")

    # Read source file
    with open(asm_path, "r", encoding="utf-8") as f:
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