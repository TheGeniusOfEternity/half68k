# Operation sizes
SIZE_L = 0  # .l — 32 bit
SIZE_B = 1  # .b — 8 bit

# Instruction codes (6 bit, elder opcode fields)
OPCODES = {
    "mv": 0b000001,
    "add": 0b000010,
    "sub": 0b000011,
    "cmp": 0b000100,
    "mul": 0b000101,
    "div": 0b000110,
    "and": 0b000111,
    "or": 0b001000,
    "xor": 0b001001,
    "clr": 0b001010,
    "neg": 0b001011,
    "not": 0b001100,
    "asl": 0b001101,
    "asr": 0b001110,
    "lsl": 0b001111,
    "lsr": 0b010000,
    "jmp": 0b010001,
    "jsr": 0b010010,
    "rts": 0b010011,
    "die": 0b010100,
    "bcc": 0b010101,
    "bcs": 0b010110,
    "beq": 0b010111,
    "bne": 0b011000,
    "bmi": 0b011001,
    "bpl": 0b011010,
    "bvs": 0b011011,
    "bvc": 0b011100,
    "blt": 0b011101,
    "ble": 0b011110,
    "bgt": 0b011111,
    "bge": 0b100000,
}

# For reverse match
REVERSED_OPCODES = {v: k for k, v in OPCODES.items()}

# Instructions without size suffix required
NO_SIZE_MNEMONICS = {
    "jmp",
    "jsr",
    "rts",
    "die",
    "bcc",
    "bcs",
    "beq",
    "bne",
    "bmi",
    "bpl",
    "bvs",
    "bvc",
    "blt",
    "ble",
    "bgt",
    "bge",
}

# Instructions encoded as opcode + absolute address (2 words)
BRANCH_MNEMONICS = {"jmp", "jsr", "bcc", "bcs", "beq", "bne", "bmi", "bpl", "bvs", "bvc", "blt", "ble", "bgt", "bge"}

# Register code (3 bits)
REGISTERS = {
    "R0": 0,
    "R1": 1,
    "R2": 2,
    "R3": 3,
    "R4": 4,
    "R5": 5,
    "R6": 6,
    "SP": 7,
}

# Address modes for operand field (5 bit: [4:3] — mode, [2:0] — number of register/submode)
MODE_IMMEDIATE = 0b00 << 3  # immediate
MODE_REGISTER_DIRECT = 0b01 << 3  # direct register
MODE_REGISTER_INDIRECT = 0b10 << 3  # indirect register (Rn)

MODE_SPECIAL = 0b11 << 3  # special modes (bits [2:0] encode submode)
SPECIAL_POSTINC = 0b000  # (Rn)+
SPECIAL_PREDEC = 0b001  # -(Rn)
SPECIAL_DISPLACEMENT = 0b010  # d(Rn)
SPECIAL_ABSOLUTE = 0b011  # (abs)

# Bit shifts in opcode word
OPCODE_SHIFT = 26
SIZE_SHIFT = 25
SRC_SHIFT = 20
DST_SHIFT = 15


def encode_opcode(mnemonic: str) -> int:
    """Returns 6-bit operation code by mnemonic (lowercase)."""
    return OPCODES[mnemonic]


def encode_size(size: str) -> int:
    """Converts '.b' or '.l' into size bit."""
    return SIZE_B if size == "b" else SIZE_L


def encode_reg(reg_name: str) -> int:
    """Returns 3-bit register code."""
    return REGISTERS[reg_name]


def encode_operand_mode(op_type: str, reg: str | None = None) -> int:
    """
    Returns 5-bit operand field.
    op_type: 'imm', 'reg', 'indirect', 'postinc', 'predec', 'displacement', 'absolute'
    """
    if op_type == "imm":
        return MODE_IMMEDIATE | 0  # bits [2:0] not applied
    if op_type == "reg" and reg is not None:
        return MODE_REGISTER_DIRECT | encode_reg(reg)
    if op_type == "indirect" and reg is not None:
        return MODE_REGISTER_INDIRECT | encode_reg(reg)
    if op_type == "postinc":
        return MODE_SPECIAL | SPECIAL_POSTINC
    if op_type == "predec":
        return MODE_SPECIAL | SPECIAL_PREDEC
    if op_type == "displacement":
        return MODE_SPECIAL | SPECIAL_DISPLACEMENT
    if op_type == "absolute":
        return MODE_SPECIAL | SPECIAL_ABSOLUTE
    raise ValueError(f"Unknown operand mode: {op_type}")


def build_opcode_word(mnemonic: str, size: str, src_mode: int, dst_mode: int, extra_bits: int = 0) -> int:
    """
    Collects 32-bit opcode word.
    extra_bits: extra bits [14:0] for shifts/conditions (default 0).
    """
    op = encode_opcode(mnemonic)
    sz = encode_size(size)
    return (op << OPCODE_SHIFT) | (sz << SIZE_SHIFT) | (src_mode << SRC_SHIFT) | (dst_mode << DST_SHIFT) | extra_bits


def calc_instr_size_from_modes(opcode: int, src_mode: int, dst_mode: int) -> int:
    """Computes instruction size in bytes based on opcode and address mode."""
    mnemonic = REVERSED_OPCODES.get(opcode, "")

    # Control-flow instructions encode as opcode + absolute address (1 extension word)
    if mnemonic in BRANCH_MNEMONICS:
        return 8
    # Instructions without operands
    if mnemonic in ("rts", "die"):
        return 4

    size = 4  # opcode word

    # Unary instructions use only DST operand; SRC field is ignored by encoding.
    if mnemonic not in ("clr", "neg", "not"):
        src_type = (src_mode >> 3) & 0x3
        if src_type == 0:  # imm
            size += 4
        elif src_type == 3:  # special (postinc/predec/disp/abs)
            sub = src_mode & 0x7
            if sub in (0, 1, 2, 3):
                size += 4

    # Extensions for dst
    dst_type = (dst_mode >> 3) & 0x3
    if dst_type == 0:  # imm
        size += 4
    elif dst_type == 3:  # special
        sub = dst_mode & 0x7
        if sub in (0, 1, 2, 3):
            size += 4

    return size
