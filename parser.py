import re
from typing import List, Dict, Tuple, Optional
from isa import (
    encode_opcode, encode_size, encode_reg,
    build_opcode_word,
    MODE_IMMEDIATE, MODE_REGISTER_DIRECT, MODE_REGISTER_INDIRECT, MODE_SPECIAL,
    SPECIAL_POSTINC, SPECIAL_PREDEC, SPECIAL_DISPLACEMENT, SPECIAL_ABSOLUTE
)

# Regular expression for string tokenization
TOKEN_RE = re.compile(r'''
    (?P<label>^[A-Za-z_]\w*:)                       # label
    |(?P<mnemonic>mv|add|sub|cmp|mul|div|and|or|xor|clr|neg|not|asl|asr|lsl|lsr|jmp|jsr|rts|die|bcc|bcs|beq|bne|bmi|bpl|bvs|bvc|blt|ble|bgt|bge)(?=\s|$|\.)  # мнемоника
    |(?P<size>\.\w+)                                # size .b or .l
    |(?P<comma>,)                                   # comma
    |(?P<directive>db|dw|pstr|\.org|\.data|\.code)  # directives
    |(?P<number>\d+|0x[0-9a-fA-F]+|0b[01]+)         # numbers
    |(?P<reg>R[0-6]|SP)                             # registers
    |(?P<immediate>\#)                              # immediate operand symbol
    |(?P<lparen>\()                                 # opening bracket
    |(?P<rparen>\))                                 # closing bracket
    |(?P<plus>\+)                                   # plus (for shifts и post-increment)
    |(?P<minus>-)                                   # minus (for expressions and pre-decrement)
    |(?P<ident>[A-Za-z_]\w*)                        # identifier (label, constand)
    |(?P<string>"[^"]*")                            # string in quotes
    |(?P<comment>;.*)                               # comment
    |(?P<whitespace>\s+)                            # spaces (ingnore)
''', re.VERBOSE)


class Token:
    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

class Tokenizer:
    """Splits string into tokens via regular expression."""
    def __init__(self, line: str):
        self.tokens = []
        for m in TOKEN_RE.finditer(line):
            kind = m.lastgroup
            value = m.group()
            if kind == 'whitespace' or kind == 'comment':
                continue  # пропускаем
            self.tokens.append(Token(kind, value, m.start()))
        self.pos = 0

    def peek(self) -> Optional[Token]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def next(self) -> Optional[Token]:
        tok = self.peek()
        if tok:
            self.pos += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.next()
        if tok is None or tok.kind != kind:
            raise SyntaxError(f"Expected {kind}, got {tok}")
        return tok

    def maybe(self, kind: str) -> Optional[Token]:
        peek = self.peek()
        if peek and peek.kind == kind:
            return self.next()
        return None


class Operand:
    """Stores information about instruction operand."""
    def __init__(self, mode: str, reg: Optional[str] = None, imm: Optional[int] = None,
                 disp: Optional[int] = None, abs_addr: Optional[int] = None):
        self.mode = mode          # 'imm', 'reg', 'indirect', 'postinc', 'predec', 'displacement', 'absolute'
        self.reg = reg            # name of the register or None
        self.imm = imm            # immediate value (if mode=='imm')
        self.disp = disp          # shift (for displacement)
        self.abs_addr = abs_addr  # absolute address

class Instruction:
    """Describes single machine instruction."""
    def __init__(self, mnemonic: str, size: str, operands: List[Operand], addr: int):
        self.mnemonic = mnemonic
        self.size = size
        self.operands = operands
        self.addr = addr
        self.words: List[int] = []  # binary code (list of 32-bit words)

class DataItem:
    """Saves information about element of data section for second pass."""
    def __init__(self, kind: str, addr: int):
        self.kind = kind          # 'db', 'dw' или 'pstr'
        self.addr = addr          # address of this element's start
        self.values: List = []    # for db/dw: numbers list (int or str for labels)
        # for pstr: list from one element - line

class Program:
    """Parse result: list of instructions/data and labels table."""
    def __init__(self):
        self.code: List[Instruction] = []       # instructions (.code section)
        self.data: List[int] = []               # flat data words list
        self.data_addr: int = 0                 # start data address (set by .org)
        self.code_addr: int = 0
        self.symbols: Dict[str, int] = {}       # labels -> address (for code) or offset in data
        self.data_symbols: Dict[str, int] = {}  # labels in data section -> address
        self.data_items: List[DataItem] = []    # elements of data section


def _calc_instr_size(mnemonic: str, operands: List[Operand]) -> int:
    """Computes length of instruction in words."""
    # Basic opcode word
    words = 1
    # Extensions for operands
    for op in operands:
        if op.mode == 'imm':
            words += 1  # 32-bit value
        elif op.mode == 'displacement':
            words += 1  # 16-bit shift (in separate word)
        elif op.mode == 'absolute':
            words += 1  # 32-bit address
        # postinc, predec, reg, indirect — without extensions
    # For transitions (jmp, jsr, bc*) there is always 32-bit address
    if mnemonic in ('jmp', 'jsr') or mnemonic.startswith('b'):
        words += 1  # absolute address
    return words


def _eval_token_value(tok: Token) -> int:
    """Converts number's or identifier's token into integer (for first pass — numbers only)."""
    if tok.kind == 'number':
        if tok.value.startswith('0x'):
            return int(tok.value, 16)
        elif tok.value.startswith('0b'):
            return int(tok.value, 2)
        else:
            return int(tok.value)
    elif tok.kind == 'ident':
        # TODO: identifiers convert
        return 0
    else:
        raise SyntaxError(f"Cannot evaluate token {tok}")


def _operand_to_field(op: Operand, words_ext: List[int]) -> int:
    """Encodes operand into 5-bit fields by adding extension words if required in words_ext.
    Returns 5-bit field for opcode.
    """
    if op.mode == 'imm' and op.imm is not None:
        field = MODE_IMMEDIATE | 0
        words_ext.append(op.imm)  # 32-bit value
    elif op.mode == 'reg' and op.reg is not None:
        field = MODE_REGISTER_DIRECT | encode_reg(op.reg)
    elif op.mode == 'indirect' and op.reg is not None:
        field = MODE_REGISTER_INDIRECT | encode_reg(op.reg)
    elif op.mode == 'postinc' and op.reg is not None:
        field = MODE_SPECIAL | SPECIAL_POSTINC
        # Store register number in extended word
        # Scheme: bits [19:16] for register number, [15:0] — shift
        ext_word = (encode_reg(op.reg) << 16) & 0xF0000
        words_ext.append(ext_word)
    elif op.mode == 'predec' and op.reg is not None:
        field = MODE_SPECIAL | SPECIAL_PREDEC
        ext_word = (encode_reg(op.reg) << 16) & 0xF0000
        words_ext.append(ext_word)
    elif op.mode == 'displacement' and op.disp is not None and op.reg is not None:
        field = MODE_SPECIAL | SPECIAL_DISPLACEMENT
        # extended word: bits [19:16] — register, [15:0] — signed shift
        ext_word = (encode_reg(op.reg) << 16) | (op.disp & 0xFFFF)
        words_ext.append(ext_word)
    elif op.mode == 'absolute' and op.abs_addr is not None:
        field = MODE_SPECIAL | SPECIAL_ABSOLUTE
        words_ext.append(op.abs_addr)  # full 32-bit address
    else:
        raise ValueError(f"Unknown operand mode: {op.mode}")
    return field


def _resolve_value(val: int, symbol_table: Dict[str, int]) -> int:
    # TODO: resolve value in second pass
    return val


def _generate_instruction_words(instr: Instruction) -> List[int]:
    """Returns list of 32-bit words for instruction."""
    words = []
    # Define operands mode and collect fields src/dst
    # For instructions with one operand (clr, neg, not) second operand is the same
    # For transitions operands are non-standard.

    # Copying opcode
    mnemonic = instr.mnemonic
    size = instr.size
    ops = instr.operands

    # If instruction is flow controlling (jmp, jsr, bcc, ...) then format is different: opcode + 32-bit address
    if mnemonic in ('jmp', 'jsr') or mnemonic.startswith('b'):
        opcode = encode_opcode(mnemonic)
        sz = encode_size(size)  # размер не важен для переходов, но поле оставим
        # Fields src/dst are not used, reset
        word = (opcode << 26) | (sz << 25)
        words.append(word)
        # Add transition address (пока не знаем, в первом проходе у нас операнд absolute)
        # Search operand with absolute address
        addr = 0
        for op in ops:
            if op.mode == 'absolute':
                addr = op.abs_addr
            elif op.mode == 'imm':
                addr = op.imm
        # TODO: handle identifiers
        words.append(addr)
        return words

    # Instructions without operands (rts, die)
    if mnemonic in ('rts', 'die'):
        opcode = encode_opcode(mnemonic)
        sz = encode_size(size)
        word = (opcode << 26) | (sz << 25)
        words.append(word)
        return words

    # Default instructions with operands
    # Define src and dst modes
    src_mode = 0
    dst_mode = 0
    if len(ops) >= 1:
        src_mode = _operand_to_field(ops[0], words)
    if len(ops) >= 2:
        dst_mode = _operand_to_field(ops[1], words)
    elif len(ops) == 1:
        # For instructions with one operand (clr, neg, not) second operand is ignored
        dst_mode = 0

    extra = 0  # for shifts
    word = build_opcode_word(mnemonic, size, src_mode, dst_mode, extra)
    # Insert opcode into start of the words list (_operand_to_field added extension to the end)
    words.insert(0, word)
    return words


class Parser:
    def __init__(self, lines: List[str]):
        self.lines = lines
        self.program = Program()

    def parse(self) -> Program:
        # First pass: collect labels and compute addresses
        self._first_pass()
        # Second pass: generate binary
        self._second_pass()
        return self.program

    def _first_pass(self):
        current_section = None  # 'data' или 'code'
        addr = 0                # current address in section

        for line in self.lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue

            tok = Tokenizer(stripped)
            t = tok.peek()
            if t is None:
                continue

            # Check if label
            if t.kind == 'label':
                label_name = t.value[:-1]  # remove ':'
                tok.next()
                if current_section == 'data':
                    self.program.data_symbols[label_name] = addr
                elif current_section == 'code':
                    self.program.symbols[label_name] = addr
                else:
                    raise SyntaxError(f"Label without section: {label_name}")
                # After label there might be instruction/directive on the same line
                t = tok.peek()
                if t is None:
                    continue

            # Check if directive
            if t.kind == 'directive' and t.value in ('.data', '.code'):
                current_section = t.value[1:]  # 'data' or 'code'
                tok.next()
                continue

            # .org
            if t.kind == 'directive' and t.value == '.org':
                tok.next()
                addr = self._parse_expression(tok)
                continue

            # In data section: directives db, dw, pstr
            if current_section == 'data':
                if t.kind == 'directive':
                    directive = t.value
                    tok.next()
                    item = DataItem(directive, addr)
                    if directive == 'db':
                        while tok.peek() is not None:
                            # Parse expression without computation, if label — save token as string
                            self._parse_data_operand(tok, item)
                            addr += 1
                            if tok.maybe('comma') is None:
                                break
                    elif directive == 'dw':
                        while tok.peek() is not None:
                            self._parse_data_operand(tok, item)
                            addr += 1
                            if tok.maybe('comma') is None:
                                break
                    elif directive == 'pstr':
                        str_tok = tok.expect('string')
                        s = str_tok.value[1:-1]
                        item.values.append(s)
                        addr += 1 + len(s)
                    else:
                        raise SyntaxError(f"Unknown data directive: {directive}")
                    self.program.data_items.append(item)
                continue

            # In code section: instructions
            if current_section == 'code':
                # Define size of the instruction (based on operand modes)
                mnemonic, size, operands = self._parse_instruction(tok)
                instr_size = _calc_instr_size(mnemonic, operands)
                # Write information for second pass
                # Пока сохраняем только адрес, инструкцию сохраним во втором проходе
                self.program.code.append(Instruction(mnemonic, size, operands, addr))
                addr += instr_size
                continue

            # If token was not matched
            raise SyntaxError(f"Unexpected token: {t}")

        # Remember max addresses
        if current_section == 'code':
            self.program.code_addr = addr  # end address (next free)

    def _parse_instruction(self, tok: Tokenizer) -> Tuple[str, str, List[Operand]]:
        """Process mnemonics, size and operands."""
        mnemonic_tok = tok.expect('mnemonic')
        mnemonic = mnemonic_tok.value

        # Check size (.b or .l)
        size_tok = tok.maybe('size')
        if size_tok:
            size = size_tok.value[1:]  # убираем точку
        else:
            raise SyntaxError(f"Size suffix required for {mnemonic}")

        operands = []
        # Process operands by comma
        while True:
            op = self._parse_operand(tok)
            if op:
                operands.append(op)
            if tok.maybe('comma') is None:
                break
        return mnemonic, size, operands

    def _parse_operand(self, tok: Tokenizer) -> Optional[Operand]:
        """Processes one operand (register, #imm, (abs), (Rn), (Rn)+, -(Rn), disp(Rn))."""
        t = tok.peek()
        if t is None:
            return None

        # Register
        if t.kind == 'reg':
            tok.next()
            return Operand(mode='reg', reg=t.value)

        # Immediate values: #number or #ident
        if t.kind == 'immediate':
            tok.next()
            val = self._parse_expression(tok)
            return Operand(mode='imm', imm=val)

        # Absolute address or indirect via register
        if t.kind == 'lparen':
            tok.next()  # skip '('
            next_t = tok.peek()
            # Check if next token is register (for (Rn), (Rn)+)
            if next_t and next_t.kind == 'reg':
                reg_tok = tok.next()          # skip register
                after_reg = tok.peek()
                if after_reg and after_reg.kind == 'rparen' and reg_tok is not None:
                    reg = reg_tok.value
                    tok.next()                # skip ')'
                    # check '+'
                    plus_tok = tok.peek()
                    if plus_tok and plus_tok.kind == 'plus':
                        tok.next()
                        return Operand(mode='postinc', reg=reg)
                    return Operand(mode='indirect', reg=reg)
                else:
                    raise SyntaxError(f"Expected ')' after register in brackets, got {after_reg}")
            # Otherwise process expression from brackets (absolute address)
            else:
                sign = 1
                peek = tok.peek()
                if peek and peek.kind == 'minus':
                    tok.next()
                    sign = -1
                val = self._parse_expression(tok) * sign
                tok.expect('rparen')
                return Operand(mode='absolute', abs_addr=val)

        # Shift: disp(Rn)  (i.e., 8(R0) or -4(SP))
        if t.kind in ('number', 'ident', 'minus'):
            disp_sign = 1
            if t.kind == 'minus':
                tok.next()
                disp_sign = -1
                # after minus there must be a number or an identifier
                disp_tok = tok.peek()
                if not disp_tok or disp_tok.kind not in ('number', 'ident'):
                    raise SyntaxError("Expected number or identifier after '-' in displacement")
            else:
                disp_tok = tok.next()  # already number/identifier

            if disp_tok is not None:
                disp = _eval_token_value(disp_tok) * disp_sign
                tok.expect('lparen')
                reg_tok = tok.expect('reg')
                reg = reg_tok.value
                tok.expect('rparen')
                return Operand(mode='displacement', reg=reg, disp=disp)

        return None

    def _parse_expression(self, tok: Tokenizer) -> int:
        """Processes simple expression: term + term - term ... (no brackets).
        All computations immediate, no labels (label are processed in second pass).
        In first pass expression can't contain labels, numbers only.
        """
        t = tok.peek()
        if t and t.kind in ('number', 'ident'):
            tok.next()
            return _eval_token_value(t)
        # If there is unary minus
        if t and t.kind == 'minus':
            tok.next()
            val = self._parse_expression(tok)
            return -val
        raise SyntaxError(f"Expected number in expression, got {t}")

    def _parse_data_operand(self, tok: Tokenizer, item: DataItem):
        """Saves numeric value or label name into data element."""
        t = tok.peek()
        if t is None:
            raise SyntaxError("Expected data operand")
        if t.kind == 'minus':
            tok.next()
            # After minus there must be a number or an identifier
            nt = tok.peek()
            if nt is None or nt.kind not in ('number', 'ident'):
                raise SyntaxError("Expected number or identifier after '-'")
            self._parse_expression(tok)
            if nt.kind == 'ident':
                tok.next()  # съедаем ident
                item.values.append(f"-{nt.value}")  # save as string
            else:
                # число
                tok.next()
                val = _eval_token_value(nt)
                item.values.append(-val)
            return
        elif t.kind == 'number':
            tok.next()
            item.values.append(_eval_token_value(t))
        elif t.kind == 'ident':
            tok.next()
            item.values.append(t.value)  # save as string label name
        elif t.kind == 'string':
            raise SyntaxError("Unexpected string in data directive")
        else:
            raise SyntaxError(f"Unexpected token in data directive: {t}")

    def _second_pass(self):
        """Generates binary for all instructions using symbols."""
        # Clear words of instructions
        for instr in self.program.code:
            instr.words = _generate_instruction_words(instr)
        # Generate words for data
        data_words = []
        for line in self.lines:
            # TODO: processing
            pass
        self.program.data = data_words

