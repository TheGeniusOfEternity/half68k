import re

from isa import (
    BRANCH_MNEMONICS,
    MODE_IMMEDIATE,
    MODE_REGISTER_DIRECT,
    MODE_REGISTER_INDIRECT,
    MODE_SPECIAL,
    NO_SIZE_MNEMONICS,
    SPECIAL_ABSOLUTE,
    SPECIAL_DISPLACEMENT,
    SPECIAL_POSTINC,
    SPECIAL_PREDEC,
    build_opcode_word,
    encode_reg,
)

# Regular expression for string tokenization
TOKEN_RE = re.compile(
    r"""
    (?P<label>^[A-Za-z_]\w*:)                               # label
    |(?P<mnemonic>                                          # mnemonic
        mv|add|sub|cmp|mul|div
        |and|or|xor
        |clr|neg|not
        |asl|asr|lsl|lsr
        |jmp|jsr|rts|die
        |bcc|bcs|beq|bne|bmi|bpl|bvs|bvc|blt|ble|bgt|bge
    )(?=\s|$|\.)
    |(?P<size>\.[bl])                                       # size .b or .l
    |(?P<comma>,)                                           # comma
    |(?P<directive>db|dw|pstr|\.org|\.data|\.code)          # directives
    |(?P<number>0x[0-9a-fA-F]+|0b[01]+|\d+)                 # numbers
    |(?P<reg>R[0-6]|SP)                                     # registers
    |(?P<immediate>\#)                                      # immediate operand symbol
    |(?P<lparen>\()                                         # opening bracket
    |(?P<rparen>\))                                         # closing bracket
    |(?P<plus>\+)                                           # plus (for shifts and post-increment)
    |(?P<minus>-)                                           # minus (for expressions and pre-decrement)
    |(?P<ident>[A-Za-z_]\w*)                                # identifier (label, constant)
    |(?P<string>"[^"]*")                                    # string in quotes
    |(?P<comment>;.*)                                       # comment
    |(?P<whitespace>\s+)                                    # spaces (ignore)
""",
    re.VERBOSE,
)


class Token:
    def __init__(self, kind: str, value: str, pos: int) -> None:
        self.kind = kind
        self.value = value
        self.pos = pos


class Tokenizer:
    """Splits string into tokens via regular expression."""

    def __init__(self, line: str) -> None:
        self.tokens: list[Token] = []
        for m in TOKEN_RE.finditer(line):
            kind = m.lastgroup
            value = m.group()
            if kind in ["whitespace", "comment"]:
                continue  # skip
            assert kind is not None
            self.tokens.append(Token(kind, value, m.start()))
        self.pos = 0

    def peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def next(self) -> Token | None:
        tok = self.peek()
        if tok:
            self.pos += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.next()
        if tok is None or tok.kind != kind:
            raise SyntaxError(f"Expected {kind}, got {tok}")
        return tok

    def maybe(self, kind: str) -> Token | None:
        peek = self.peek()
        if peek and peek.kind == kind:
            return self.next()
        return None


class Operand:
    """Stores information about instruction operand."""

    def __init__(self, mode: str, reg: str | None = None, imm: int | str | None = None, disp: int | str | None = None, abs_addr: int | str | None = None):
        self.mode = mode  # 'imm', 'reg', 'indirect', 'postinc', 'predec', 'displacement', 'absolute'
        self.reg = reg  # name of the register or None
        self.imm = imm  # immediate value (if mode=='imm')
        self.disp = disp  # shift (for displacement)
        self.abs_addr = abs_addr  # absolute address


class Instruction:
    """Describes a single machine instruction."""

    def __init__(self, mnemonic: str, size: str, operands: list[Operand], addr: int):
        self.mnemonic = mnemonic
        self.size = size
        self.operands = operands
        self.addr = addr
        self.words: list[int] = []  # binary code (list of 32-bit words)


class DataItem:
    """Saves information about the element of the data section for the second pass."""

    def __init__(self, kind: str, addr: int) -> None:
        self.kind = kind  # 'db', 'dw' или 'pstr'
        self.addr = addr  # address of this element's start
        self.values: list[int | str] = []  # for db/dw: numbers list (int or str for labels)
        # for pstr: list from one element - line


class Program:
    """Parse result: list of instructions/data and table of labels."""

    def __init__(self) -> None:
        self.code: list[Instruction] = []  # instructions (.code section)
        self.data: list[int] = []  # flat data words list
        self.data_addr: int = 0  # start data address (set by .org)
        self.code_addr: int = 0
        self.symbols: dict[str, int] = {}  # labels -> address (for code) or offset in data
        self.data_symbols: dict[str, int] = {}  # labels in data section -> address
        self.data_items: list[DataItem] = []  # elements of data section


def _calc_instr_size(mnemonic: str, operands: list[Operand]) -> int:
    """Computes length of instruction in words."""
    # Control-flow instructions encode as two words: opcode + absolute address
    if mnemonic in BRANCH_MNEMONICS:
        return 2
    # For other instructions
    words = 1
    for op in operands:
        if op.mode in ("imm", "displacement", "absolute", "postinc", "predec"):
            words += 1
    return words


def _eval_token_value(tok: Token) -> int | str:
    """Converts number's or identifier's token"""
    if tok.kind == "number":
        if tok.value.startswith("0x"):
            return int(tok.value, 16)
        if tok.value.startswith("0b"):
            return int(tok.value, 2)
        return int(tok.value)
    if tok.kind == "ident":
        return tok.value  # save label's name as string
    raise SyntaxError(f"Cannot evaluate token {tok}")


def _operand_to_field(op: Operand, words_ext: list[int]) -> int:
    """Encodes operand into 5-bit fields by adding extension words if required in words_ext.
    Returns 5-bit field for opcode.
    """
    if op.mode == "imm" and op.imm is not None:
        field = MODE_IMMEDIATE | 0
        words_ext.append(int(op.imm))  # 32-bit value
    elif op.mode == "reg" and op.reg is not None:
        field = MODE_REGISTER_DIRECT | encode_reg(op.reg)
    elif op.mode == "indirect" and op.reg is not None:
        field = MODE_REGISTER_INDIRECT | encode_reg(op.reg)
    elif op.mode == "postinc" and op.reg is not None:
        field = MODE_SPECIAL | SPECIAL_POSTINC
        # Store register number in extended word
        # Scheme: bits [19:16] for register number, [15:0] — shift
        ext_word = (encode_reg(op.reg) << 16) & 0x70000
        words_ext.append(ext_word)
    elif op.mode == "predec" and op.reg is not None:
        field = MODE_SPECIAL | SPECIAL_PREDEC
        ext_word = (encode_reg(op.reg) << 16) & 0x70000
        words_ext.append(ext_word)
    elif op.mode == "displacement" and op.disp is not None and op.reg is not None:
        field = MODE_SPECIAL | SPECIAL_DISPLACEMENT
        # extended word: bits [19:16] — register, [15:0] — signed shift
        ext_word = (encode_reg(op.reg) << 16) | (int(op.disp) & 0xFFFF)
        words_ext.append(ext_word)
    elif op.mode == "absolute" and op.abs_addr is not None:
        field = MODE_SPECIAL | SPECIAL_ABSOLUTE
        words_ext.append(int(op.abs_addr))  # full 32-bit address
    else:
        raise ValueError(f"Unknown operand mode: {op.mode}")
    return field


def _generate_instruction_words(instr: Instruction) -> list[int]:
    """Returns the list of 32-bit words for instruction."""
    words = []
    # Define operand mode and collect fields src/dst
    # For instructions with one operand (clr, neg, not) second operand is the same
    # For transitions operands are non-standard.

    # Copying opcode
    mnemonic = instr.mnemonic
    size = instr.size
    ops = instr.operands

    # If instruction is flow controlling (jmp, jsr, bcc, ...) then format is different: opcode + 32-bit address
    if mnemonic in BRANCH_MNEMONICS:
        word = build_opcode_word(mnemonic, size, 0, 0, 0)
        words.append(word)
        addr = 0
        for op in ops:
            if op.mode == "absolute":
                if isinstance(op.abs_addr, int):
                    addr = op.abs_addr
                else:
                    raise ValueError("Unresolved label in branch target")
        words.append(addr)
        return words

    # Instructions without operands (rts, die)
    if mnemonic in ("rts", "die"):
        word = build_opcode_word(mnemonic, size, 0, 0, 0)
        words.append(word)
        return words

    # Default instructions with operands
    # Define src and dst modes
    src_mode = 0
    dst_mode = 0
    # For instructions with one operand (clr, neg, not) second operand is ignored
    if len(ops) == 1:
        dst_mode = _operand_to_field(ops[0], words)
    else:
        if len(ops) >= 1:
            src_mode = _operand_to_field(ops[0], words)
        if len(ops) >= 2:
            dst_mode = _operand_to_field(ops[1], words)

    extra = 0  # for shifts
    word = build_opcode_word(mnemonic, size, src_mode, dst_mode, extra)
    # Insert opcode into start of the list of words (_operand_to_field added extension to the end)
    words.insert(0, word)
    return words


class Parser:
    def __init__(self, lines: list[str]):
        self.lines = lines
        self.program = Program()

    def parse(self) -> Program:
        # First pass: collect labels and compute addresses
        self._first_pass()
        # Second pass: generate binary
        self._second_pass()
        return self.program

    def _first_pass(self) -> None:
        current_section = ""  # 'data' or 'code'
        addrs = {"data": 0, "code": 0}  # independent address counters

        for line in self.lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue

            tok = Tokenizer(stripped)
            t = tok.peek()
            if t is None:
                continue

            # Check if label
            if t.kind == "label":
                label_name = t.value[:-1]  # remove ':'
                tok.next()
                if current_section == "data":
                    self.program.data_symbols[label_name] = addrs["data"]
                elif current_section == "code":
                    self.program.symbols[label_name] = addrs["code"]
                else:
                    raise SyntaxError(f"Label without section: {label_name}")
                t = tok.peek()
                if t is None:
                    continue

            # Check if directive
            if t.kind == "directive" and t.value in (".data", ".code"):
                current_section = t.value[1:]
                # don't reset counter on second entry, switch only
                tok.next()
                continue

            # .org
            if t.kind == "directive" and t.value == ".org":
                tok.next()
                new_addr = self._parse_expression_int(tok)
                if not current_section:
                    raise SyntaxError(".org without section")
                addrs[current_section] = new_addr
                continue

            # In data section: directives db, dw, pstr
            if current_section == "data":
                if t.kind == "directive":
                    directive = t.value
                    tok.next()
                    item = DataItem(directive, addrs["data"])
                    if directive == "db":
                        while tok.peek() is not None:
                            # Parse expression without computation, if label — save token as string
                            self._parse_data_operand(tok, item)
                            addrs["data"] += 1
                            if tok.maybe("comma") is None:
                                break
                    elif directive == "dw":
                        while tok.peek() is not None:
                            self._parse_data_operand(tok, item)
                            addrs["data"] += 1
                            if tok.maybe("comma") is None:
                                break
                    elif directive == "pstr":
                        str_tok = tok.expect("string")
                        s = str_tok.value[1:-1]
                        item.values.append(s)
                        addrs["data"] += 1 + len(s)
                    else:
                        raise SyntaxError(f"Unknown data directive: {directive}")
                    self.program.data_items.append(item)
                continue

            # In code section: instructions
            if current_section == "code":
                # Define size of the instruction (based on operand modes)
                mnemonic, size, operands = self._parse_instruction(tok)
                instr_size = _calc_instr_size(mnemonic, operands)
                self.program.code.append(Instruction(mnemonic, size, operands, addrs["code"]))
                addrs["code"] += instr_size
                continue

            # If token was not matched
            raise SyntaxError(f"Unexpected token: {t}")

        # Remember max addresses
        self.program.data_addr = addrs["data"]
        self.program.code_addr = addrs["code"]

    def _parse_instruction(self, tok: Tokenizer) -> tuple[str, str, list[Operand]]:
        """Process mnemonics, size, operands."""
        mnemonic_tok = tok.expect("mnemonic")
        mnemonic = mnemonic_tok.value

        if mnemonic in NO_SIZE_MNEMONICS:
            size = "l"  # mock size will be ignored
        else:
            size_tok = tok.maybe("size")
            if size_tok:
                size = size_tok.value[1:]  # remove dot
            else:
                raise SyntaxError(f"Size suffix required for {mnemonic}")

        operands = []
        # For transition instructions (jmp, jsr, branches) operand is expression (absolute address)
        if mnemonic in BRANCH_MNEMONICS:
            val = self._parse_expression(tok)
            operands.append(Operand(mode="absolute", abs_addr=val))
            return mnemonic, size, operands

        # Process operands by comma
        while True:
            op = self._parse_operand(tok)
            if op:
                operands.append(op)
            if tok.maybe("comma") is None:
                break
        return mnemonic, size, operands

    def _parse_operand(self, tok: Tokenizer) -> Operand | None:
        """Processes one operand (register, #imm, (abs), (Rn), (Rn)+, -(Rn), disp(Rn))."""
        t = tok.peek()
        if t is None:
            return None

        # Register
        if t.kind == "reg":
            tok.next()
            return Operand(mode="reg", reg=t.value)

        # Immediate values: #number or #ident
        if t.kind == "immediate":
            tok.next()
            val = self._parse_expression(tok)
            return Operand(mode="imm", imm=val)

        # Absolute address or indirect via register
        if t.kind == "lparen":
            tok.next()  # skip '('
            next_t = tok.peek()
            # Check if next token is register (for (Rn), (Rn)+)
            if next_t and next_t.kind == "reg":
                reg_tok = tok.next()  # skip register
                after_reg = tok.peek()
                if after_reg and after_reg.kind == "rparen" and reg_tok is not None:
                    reg = reg_tok.value
                    tok.next()  # skip ')'
                    # check '+'
                    plus_tok = tok.peek()
                    if plus_tok and plus_tok.kind == "plus":
                        tok.next()
                        return Operand(mode="postinc", reg=reg)
                    return Operand(mode="indirect", reg=reg)
                raise SyntaxError(f"Expected ')' after register in brackets, got {after_reg}")
            # Otherwise process expression from brackets (absolute address)
            sign = 1
            peek = tok.peek()
            if peek and peek.kind == "minus":
                tok.next()
                sign = -1
            abs_val: int | str = self._parse_expression(tok)
            if sign == -1:
                if isinstance(abs_val, str):
                    abs_val = f"-{abs_val}"
                else:
                    abs_val = -abs_val
            tok.expect("rparen")
            return Operand(mode="absolute", abs_addr=abs_val)

        # Predecrement
        if t.kind == "minus":
            saved_pos = tok.pos
            tok.next()  # consume '-'
            next_t = tok.peek()
            if next_t and next_t.kind == "lparen":
                tok.next()  # consume '('
                reg_tok = tok.expect("reg")
                reg = reg_tok.value
                tok.expect("rparen")
                return Operand(mode="predec", reg=reg)
            # not a predecrement, rewind to let displacement/expression handle it
            tok.pos = saved_pos

        # Shift: disp(Rn)  (i.e., 8(R0) or -4(SP))
        if t.kind in ("number", "ident", "minus"):
            disp_sign = 1
            if t.kind == "minus":
                tok.next()
                disp_sign = -1
                # after minus there must be a number or an identifier
                disp_tok = tok.peek()
                if not disp_tok or disp_tok.kind not in ("number", "ident"):
                    raise SyntaxError("Expected number or identifier after '-' in displacement")
            else:
                disp_tok = tok.next()  # already number/identifier

            if disp_tok is not None:
                disp_val = _eval_token_value(disp_tok)
                disp: int | str
                if isinstance(disp_val, str) and disp_sign == -1:
                    disp = f"-{disp_val}"
                elif isinstance(disp_val, int):
                    disp = disp_val * disp_sign
                else:
                    disp = disp_val  # string without minus
                tok.expect("lparen")
                reg_tok = tok.expect("reg")
                reg = reg_tok.value
                tok.expect("rparen")
                return Operand(mode="displacement", reg=reg, disp=disp)

        return None

    def _parse_expression_int(self, tok: Tokenizer) -> int:
        val = self._parse_expression(tok)
        if isinstance(val, int):
            return val
        raise SyntaxError(f"Expected a number, got identifier '{val}'")

    def _parse_expression(self, tok: Tokenizer) -> int | str:
        """Processes simple expression (no brackets).
        All computations are immediate, no labels (labels are processed in the second pass).
        In the first pass, the expression can't contain labels, numbers only.
        """
        t = tok.peek()
        if t and t.kind in ("number", "ident"):
            tok.next()
            return _eval_token_value(t)
        # If there is unary minus
        if t and t.kind == "minus":
            tok.next()
            nt = tok.peek()
            if nt and nt.kind == "ident":
                tok.next()
                return f"-{nt.value}"  # save as string with minus
            val = self._parse_expression(tok)
            if isinstance(val, int):
                return -val
            # if string is here
            raise SyntaxError("Cannot negate a label")
        raise SyntaxError(f"Expected number in expression, got {t}")

    def _parse_data_operand(self, tok: Tokenizer, item: DataItem) -> None:
        """Saves numeric value or label name into the data element."""
        t = tok.peek()
        if t is None:
            raise SyntaxError("Expected data operand")
        # Use _parse_expression
        val = self._parse_expression(tok)
        item.values.append(val)

    def _second_pass(self) -> None:
        """Generates binary code for instructions and data, processing labels."""
        # Instructions
        for instr in self.program.code:
            for op in instr.operands:
                self._resolve_operand(op)
            instr.words = _generate_instruction_words(instr)

        # Data
        data_words = []
        for item in self.program.data_items:
            if item.kind in ["db", "dw"]:
                for v in item.values:
                    data_words.append(self._resolve_value(v))
            elif item.kind == "pstr":
                s = item.values[0]  # string
                if not isinstance(s, str):
                    raise ValueError("Expected string in pstr")
                data_words.append(len(s))
                for ch in s:
                    data_words.append(ord(ch))
        self.program.data = data_words

    def _resolve_value(self, val: int | str) -> int:
        """Converts number or label's name into the numeric address."""
        if isinstance(val, int):
            return val
        # if string – label's name (could be with minus)
        negate = False
        name = val
        if val.startswith("-"):
            negate = True
            name = val[1:]
        # Search in symbols tables
        if name in self.program.symbols:
            addr = self.program.symbols[name]
        elif name in self.program.data_symbols:
            addr = self.program.data_symbols[name]
        else:
            raise ValueError(f"Undefined label: {name}")
        return -addr if negate else addr

    def _resolve_operand(self, op: Operand) -> None:
        """Replaces string label names in operand with numbers"""
        if op.imm is not None:
            op.imm = self._resolve_value(op.imm)
        if op.disp is not None:
            op.disp = self._resolve_value(op.disp)
        if op.abs_addr is not None:
            op.abs_addr = self._resolve_value(op.abs_addr)
