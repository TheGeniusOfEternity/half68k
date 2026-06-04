#!/usr/bin/env python3
"""
Half68k Processor Model
Usage: python machine.py <binary_file> [input_file]
"""

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from isa import DST_SHIFT, OPCODE_SHIFT, REVERSED_OPCODES, SIZE_SHIFT, SRC_SHIFT, calc_instr_size_from_modes

IN_PORT = 0xFFFFFF00
OUT_PORT = 0xFFFFFF04
DATA_MEM_SIZE = 1024 * 64


class MicroOp:
    def __init__(self, op: str, *args: str) -> None:
        self.op = op
        self.args = args

    def __repr__(self) -> str:
        return f"MicroOp({self.op}, {', '.join(map(str, self.args))})"


class MicrocodeMemory:
    def __init__(self) -> None:
        self.programs: dict[str, list[list[MicroOp]]] = {}

    def add(self, name: str, program: list[list[MicroOp]]) -> None:
        self.programs[name] = program

    def get(self, name: str) -> list[list[MicroOp]] | None:
        return self.programs.get(name)


@dataclass
class Flags:
    N: bool = False
    Z: bool = False
    C: bool = False
    V: bool = False


class DataPath:
    def __init__(self) -> None:
        self.regs = [0] * 8
        self.regs[7] = (DATA_MEM_SIZE * 4) - 4
        self.pc = 0
        self.flags = Flags()
        self.imm = 0
        self.mem_addr = 0
        self.mem_data = 0
        self.alu_out = 0
        self.opcode = 0
        self.size = 0
        self.src_mode = 0
        self.dst_mode = 0
        self.src_reg = 0
        self.dst_reg = 0
        self.pc_modified = False
        self.ext_offset = 0
        self.branch_cond = ""

    def set_reg(self, idx: int, val: int) -> None:
        self.regs[idx] = val & 0xFFFFFFFF

    def get_reg(self, idx: int) -> int:
        return self.regs[idx]

    def update_flags(self, result: int, size: str = "l", a: int = 0, b: int = 0, is_sub: bool = False) -> None:
        mask = 0xFF if size == "b" else 0xFFFFFFFF
        res_masked = result & mask
        a_masked = a & mask
        b_masked = b & mask
        sign_mask = 0x80 if size == "b" else 0x80000000
        self.flags.N = bool(result & sign_mask)
        self.flags.Z = res_masked == 0
        if not is_sub:
            self.flags.C = res_masked < a_masked
            self.flags.V = ((a_masked ^ res_masked) & (b_masked ^ res_masked) & sign_mask) != 0
        else:
            self.flags.C = a_masked < b_masked
            self.flags.V = ((a_masked ^ res_masked) & ((~b_masked) & mask ^ res_masked) & sign_mask) != 0


class Processor:
    def __init__(self, code: dict[int, int], data: list[int], code_start: int, input_buffer: bytes) -> None:
        self.code = code
        self.data_mem = bytearray(DATA_MEM_SIZE * 4)
        for i, w in enumerate(data):
            self.write_data_word(i * 4, w)
        self.input_buffer = input_buffer
        self.output_buffer = bytearray()
        self.input_pos = 0
        self.dp = DataPath()
        self.dp.pc = code_start
        self.cu = ControlUnit(self)
        self.clock = 0
        self.halted = False
        self.log_lines: list[str] = []

    def read_data_word(self, addr: int) -> int:
        if addr == IN_PORT:
            if self.input_pos >= len(self.input_buffer):
                return 0  # end of stream, return 0 but don't halt
            b = self.input_buffer[self.input_pos]
            self.input_pos += 1
            return b
        if addr == OUT_PORT:
            return 0
        offset = addr % (DATA_MEM_SIZE * 4)
        return int(struct.unpack_from("<I", self.data_mem, offset)[0])

    def write_data_word(self, addr: int, val: int) -> None:
        if addr == OUT_PORT:
            char_val = val & 0xFF
            self.output_buffer.append(char_val)
            return
        offset = addr % (DATA_MEM_SIZE * 4)
        struct.pack_into("<I", self.data_mem, offset, val & 0xFFFFFFFF)

    def tick(self) -> None:
        if self.halted:
            return
        self.clock += 1
        self.cu.step()
        self._log()

    def run(self) -> None:
        while not self.halted:
            self.tick()
        print("Output:\n", self.output_buffer.decode("ascii", errors="ignore"), sep="")
        journal_path = Path("journal.log")
        with journal_path.open("w") as f:
            f.write("\n".join(self.log_lines) + "\n")

    def _log(self) -> None:
        exec_str = ", ".join(str(op) for op in self.cu.current_micro_ops) if self.cu.current_micro_ops else "NOP"
        self.log_lines.append(
            f"Tick: {self.clock:04d} | PC: {self.dp.pc:04X} | "
            f"R0={self.dp.regs[0]:08X} R1={self.dp.regs[1]:08X} R2={self.dp.regs[2]:08X} R3={self.dp.regs[3]:08X} "
            f"R4={self.dp.regs[4]:08X} R5={self.dp.regs[5]:08X} R6={self.dp.regs[6]:08X} SP={self.dp.regs[7]:08X} "
            f"| Exec: {exec_str}"
        )


class ControlUnit:
    def __init__(self, proc: Processor) -> None:
        self.proc = proc
        self.mc = MicrocodeMemory()
        self._init_microcode()
        self.current_microprogram: list[list[MicroOp]] | None = None
        self.micro_pc = 0
        self.current_micro_ops: list[MicroOp] = []
        self.instr_done = False
        self.instr_size = 0

    def _init_microcode(self) -> None:
        # Basic
        self.mc.add("die", [[MicroOp("HALT")]])
        self.mc.add("jmp", [[MicroOp("LOAD_IMM_EXT")], [MicroOp("SET_PC", "IMM")]])
        self.mc.add("jsr", [[MicroOp("LOAD_IMM_EXT")], [MicroOp("PUSH_PC")], [MicroOp("SET_PC", "IMM")]])
        self.mc.add("rts", [[MicroOp("POP_PC")]])
        self.mc.add("branch_taken", [[MicroOp("LOAD_IMM_EXT")], [MicroOp("BRANCH_IF")]])
        self.mc.add("branch_not_taken", [])

        # MV variants
        self.mc.add("mv_reg_reg", [[MicroOp("EXEC", "MOV", "SRC_REG", "DST_REG")]])
        self.mc.add("mv_imm_reg", [[MicroOp("LOAD_IMM_EXT")], [MicroOp("EXEC", "MOV", "IMM", "DST_REG")]])
        self.mc.add("mv_indirect_reg", [[MicroOp("FETCH_SRC_ADDR")], [MicroOp("READ_MEM")], [MicroOp("EXEC", "MOV", "MEM", "DST_REG")]])
        self.mc.add(
            "mv_postinc_reg",
            [
                [MicroOp("LOAD_REG_EXT", "SRC")],
                [MicroOp("FETCH_SRC_ADDR"), MicroOp("POSTINC_SRC")],
                [MicroOp("READ_MEM")],
                [MicroOp("EXEC", "MOV", "MEM", "DST_REG")],
            ],
        )
        self.mc.add("mv_absolute_reg", [[MicroOp("LOAD_ABS_ADDR_EXT")], [MicroOp("READ_MEM")], [MicroOp("EXEC", "MOV", "MEM", "DST_REG")]])
        self.mc.add("mv_reg_indirect", [[MicroOp("FETCH_DST_ADDR")], [MicroOp("WRITE_MEM", "SRC_REG")]])
        self.mc.add("mv_reg_absolute", [[MicroOp("LOAD_ABS_ADDR_EXT")], [MicroOp("WRITE_MEM", "SRC_REG")]])
        self.mc.add(
            "mv_reg_predec", [[MicroOp("LOAD_REG_EXT", "DST")], [MicroOp("PREDEC_DST")], [MicroOp("FETCH_DST_ADDR")], [MicroOp("WRITE_MEM", "SRC_REG")]]
        )
        self.mc.add(
            "mv_reg_postinc", [[MicroOp("LOAD_REG_EXT", "DST")], [MicroOp("FETCH_DST_ADDR")], [MicroOp("WRITE_MEM", "SRC_REG")], [MicroOp("POSTINC_DST")]]
        )
        # displacement source -> register
        self.mc.add(
            "mv_src_displacement_reg",
            [
                [MicroOp("LOAD_REG_EXT", "SRC")],
                [MicroOp("FETCH_DISPLACEMENT_ADDR")],
                [MicroOp("READ_MEM")],
                [MicroOp("EXEC", "MOV", "MEM", "DST_REG")],
            ],
        )
        # register -> displacement destination
        self.mc.add(
            "mv_reg_disp_dst",
            [
                [MicroOp("LOAD_REG_EXT", "DST")],
                [MicroOp("FETCH_DISPLACEMENT_ADDR_DST")],
                [MicroOp("WRITE_MEM", "SRC_REG")],
            ],
        )

        # Arithmetic & Logic for imm & reg
        for op in ("add", "sub", "cmp", "and", "or", "xor", "mul", "div"):
            self.mc.add(f"{op}_imm_reg", [[MicroOp("LOAD_IMM_EXT")], [MicroOp("EXEC", op.upper(), "IMM", "DST_REG")]])
            self.mc.add(f"{op}_reg_reg", [[MicroOp("EXEC", op.upper(), "SRC_REG", "DST_REG")]])

        # Shifts for imm & reg
        for op in ("lsr", "lsl", "asr", "asl"):
            self.mc.add(f"{op}_imm_reg", [[MicroOp("LOAD_IMM_EXT")], [MicroOp("EXEC", op.upper(), "IMM", "DST_REG")]])
            self.mc.add(f"{op}_reg_reg", [[MicroOp("EXEC", op.upper(), "SRC_REG", "DST_REG")]])

        # Unary (only reg)
        for op in ("clr", "not", "neg"):
            self.mc.add(f"{op}_reg", [[MicroOp("EXEC", op.upper(), "NONE", "DST_REG")]])

    def fetch_micro_instr(self) -> list[MicroOp] | None:
        if self.current_microprogram is None or self.micro_pc >= len(self.current_microprogram):
            return None
        return self.current_microprogram[self.micro_pc]

    def step(self) -> None:
        if self.instr_done:
            self._advance_pc()
            self.instr_done = False
            self.current_microprogram = None
            return
        if self.current_microprogram is None:
            self._start_next_instruction()
            return
        micro_step = self.fetch_micro_instr()
        if micro_step is None:
            self.instr_done = True
            return
        self.current_micro_ops = micro_step
        for micro_op in micro_step:
            self._execute_micro_op(micro_op)
        self.micro_pc += 1

    def _advance_pc(self) -> None:
        if self.proc.dp.pc_modified:
            self.proc.dp.pc_modified = False
            return
        self.proc.dp.pc += self.instr_size

    def _start_next_instruction(self) -> None:
        self.micro_pc = 0
        pc = self.proc.dp.pc
        raw = self.proc.code.get(pc, 0)
        if raw == 0 and pc != 0:
            self.proc.halted = True
            return
        opcode = (raw >> OPCODE_SHIFT) & 0x3F
        size = (raw >> SIZE_SHIFT) & 1
        src_mode = (raw >> SRC_SHIFT) & 0x1F
        dst_mode = (raw >> DST_SHIFT) & 0x1F
        self.proc.dp.opcode = opcode
        self.proc.dp.size = size
        self.proc.dp.src_mode = src_mode
        self.proc.dp.dst_mode = dst_mode
        self.proc.dp.src_reg = 0
        self.proc.dp.dst_reg = 0
        self.proc.dp.pc_modified = False
        self.proc.dp.ext_offset = 4
        self.proc.dp.branch_cond = ""

        self.instr_size = calc_instr_size_from_modes(opcode, src_mode, dst_mode)

        mnemonic = REVERSED_OPCODES.get(opcode)
        if mnemonic is not None:
            if mnemonic == "mv":
                src_type = (src_mode >> 3) & 0x3
                dst_type = (dst_mode >> 3) & 0x3
                if src_type == 0:  # imm
                    self.current_microprogram = self.mc.get("mv_imm_reg")
                    self.proc.dp.dst_reg = dst_mode & 0x7
                elif src_type == 1:  # reg
                    self.proc.dp.src_reg = src_mode & 0x7
                    if dst_type == 1:
                        self.current_microprogram = self.mc.get("mv_reg_reg")
                        self.proc.dp.dst_reg = dst_mode & 0x7
                    elif dst_type == 2:
                        self.current_microprogram = self.mc.get("mv_reg_indirect")
                        self.proc.dp.dst_reg = dst_mode & 0x7
                    elif dst_type == 3:  # special
                        sub_mode = dst_mode & 0x7
                        if sub_mode == 0:  # postinc
                            self.current_microprogram = self.mc.get("mv_reg_postinc")
                        elif sub_mode == 1:  # predec
                            self.current_microprogram = self.mc.get("mv_reg_predec")
                        elif sub_mode == 2:  # d(Rn)
                            self.current_microprogram = self.mc.get("mv_reg_disp_dst")
                        elif sub_mode == 3:  # absolute
                            self.current_microprogram = self.mc.get("mv_reg_absolute")
                        else:
                            raise NotImplementedError("Unsupported mv dst special mode")
                    else:
                        raise NotImplementedError("Unsupported mv - dst type")
                elif src_type == 2:  # indirect (Rn)
                    self.proc.dp.src_reg = src_mode & 0x7
                    self.current_microprogram = self.mc.get("mv_indirect_reg")
                    self.proc.dp.dst_reg = dst_mode & 0x7
                elif src_type == 3:  # special
                    sub_mode = src_mode & 0x7
                    if sub_mode == 0:  # (Rn)+
                        self.current_microprogram = self.mc.get("mv_postinc_reg")
                        self.proc.dp.dst_reg = dst_mode & 0x7
                    elif sub_mode == 2:  # d(Rn)
                        self.current_microprogram = self.mc.get("mv_src_displacement_reg")
                        self.proc.dp.dst_reg = dst_mode & 0x7
                    elif sub_mode == 3:  # (abs)
                        self.current_microprogram = self.mc.get("mv_absolute_reg")
                        self.proc.dp.dst_reg = dst_mode & 0x7
                    else:
                        raise NotImplementedError(f"Unsupported mv special src mode: {sub_mode}")
                else:
                    raise NotImplementedError("Unsupported mv - src type")
            elif mnemonic in ("beq", "bne", "bcc", "bcs", "bmi", "bpl", "bvs", "bvc", "blt", "ble", "bgt", "bge"):
                cond_map = {
                    "beq": "Z",
                    "bne": "NZ",
                    "bcs": "C",
                    "bcc": "NC",
                    "bmi": "N",
                    "bpl": "NN",
                    "bvs": "V",
                    "bvc": "NV",
                    "blt": "LT",
                    "bge": "GE",
                    "ble": "LE",
                    "bgt": "GT",
                }
                self.proc.dp.branch_cond = cond_map.get(mnemonic, "")
                take = self._eval_condition(self.proc.dp.branch_cond)
                if take:
                    self.current_microprogram = self.mc.get("branch_taken")
                else:
                    self.current_microprogram = self.mc.get("branch_not_taken")
            elif mnemonic in ("add", "sub", "cmp", "and", "or", "xor", "mul", "div") or mnemonic in ("lsr", "lsl", "asr", "asl"):
                src_type = (src_mode >> 3) & 0x3
                if src_type == 0:  # imm
                    self.current_microprogram = self.mc.get(f"{mnemonic}_imm_reg")
                    self.proc.dp.dst_reg = dst_mode & 0x7
                elif src_type == 1:  # reg
                    self.proc.dp.src_reg = src_mode & 0x7
                    self.proc.dp.dst_reg = dst_mode & 0x7
                    self.current_microprogram = self.mc.get(f"{mnemonic}_reg_reg")
                else:
                    raise NotImplementedError(f"Unsupported {mnemonic} src type")

            elif mnemonic in ("jmp", "jsr", "rts", "die"):
                self.current_microprogram = self.mc.get(mnemonic)
        else:
            raise NotImplementedError(f"Unknown opcode: {opcode:06b}")

    def _eval_condition(self, cond: str) -> bool:
        flags = self.proc.dp.flags
        if cond == "Z":
            return flags.Z
        if cond == "NZ":
            return not flags.Z
        if cond == "C":
            return flags.C
        if cond == "NC":
            return not flags.C
        if cond == "N":
            return flags.N
        if cond == "NN":
            return not flags.N
        if cond == "V":
            return flags.V
        if cond == "NV":
            return not flags.V
        if cond == "LT":
            return flags.N != flags.V
        if cond == "GE":
            return flags.N == flags.V
        if cond == "LE":
            return flags.Z or (flags.N != flags.V)
        if cond == "GT":
            return (not flags.Z) and (flags.N == flags.V)
        return False

    def _execute_micro_op(self, micro_op: MicroOp) -> None:
        op = micro_op.op
        if op == "HALT":
            self.proc.halted = True
        elif op == "LOAD_IMM_EXT":
            self.proc.dp.imm = self.proc.code.get(self.proc.dp.pc + self.proc.dp.ext_offset, 0)
            self.proc.dp.ext_offset += 4
        elif op == "LOAD_ABS_ADDR_EXT":
            self.proc.dp.mem_addr = self.proc.code.get(self.proc.dp.pc + self.proc.dp.ext_offset, 0)
            self.proc.dp.ext_offset += 4
        elif op == "LOAD_REG_EXT":
            ext_word = self.proc.code.get(self.proc.dp.pc + self.proc.dp.ext_offset, 0)
            reg_num = (ext_word >> 16) & 0x7
            if micro_op.args[0] == "SRC":
                self.proc.dp.src_reg = reg_num
            else:
                self.proc.dp.dst_reg = reg_num
            self.proc.dp.ext_offset += 4
        elif op == "FETCH_SRC_ADDR":
            self.proc.dp.mem_addr = self.proc.dp.get_reg(self.proc.dp.src_reg)
        elif op == "FETCH_DST_ADDR":
            self.proc.dp.mem_addr = self.proc.dp.get_reg(self.proc.dp.dst_reg)
        elif op == "FETCH_DISPLACEMENT_ADDR":
            ext_word = self.proc.code.get(self.proc.dp.pc + self.proc.dp.ext_offset - 4, 0)
            displacement = ext_word & 0xFFFF
            if displacement & 0x8000:  # If handling negative displacement
                displacement -= 0x10000
            base_reg_val = self.proc.dp.get_reg(self.proc.dp.src_reg)
            self.proc.dp.mem_addr = base_reg_val + displacement
        elif op == "FETCH_DISPLACEMENT_ADDR_DST":
            # for displacement mode in dst
            ext_word = self.proc.code.get(self.proc.dp.pc + self.proc.dp.ext_offset - 4, 0)
            displacement = ext_word & 0xFFFF
            if displacement & 0x8000:
                displacement -= 0x10000
            base_reg_val = self.proc.dp.get_reg(self.proc.dp.dst_reg)
            self.proc.dp.mem_addr = base_reg_val + displacement
        elif op == "POSTINC_SRC":
            reg = self.proc.dp.src_reg
            self.proc.dp.set_reg(reg, self.proc.dp.get_reg(reg) + 4)
        elif op == "POSTINC_DST":
            reg = self.proc.dp.dst_reg
            self.proc.dp.set_reg(reg, self.proc.dp.get_reg(reg) + 4)
        elif op == "PREDEC_DST":
            reg = self.proc.dp.dst_reg
            self.proc.dp.set_reg(reg, self.proc.dp.get_reg(reg) - 4)
        elif op == "READ_MEM":
            self.proc.dp.mem_data = self.proc.read_data_word(self.proc.dp.mem_addr)
        elif op == "WRITE_MEM":
            if micro_op.args[0] == "SRC_REG":
                val = self.proc.dp.get_reg(self.proc.dp.src_reg)
            else:
                val = 0
            self.proc.write_data_word(self.proc.dp.mem_addr, val)
        elif op == "EXEC":
            cmd = micro_op.args[0]
            if cmd == "MOV":
                src = micro_op.args[1]
                dst = micro_op.args[2]
                if src == "SRC_REG":
                    val = self.proc.dp.get_reg(self.proc.dp.src_reg)
                elif src == "IMM":
                    val = self.proc.dp.imm
                elif src == "MEM":
                    val = self.proc.dp.mem_data
                else:
                    val = 0
                if dst == "DST_REG":
                    self.proc.dp.set_reg(self.proc.dp.dst_reg, val)
                self.proc.dp.update_flags(val, size=("b" if self.proc.dp.size == 1 else "l"))
            elif cmd in ("ADD", "SUB", "CMP", "AND", "OR", "XOR", "MUL", "DIV"):
                src_type = micro_op.args[1]
                if src_type == "IMM":
                    operand = self.proc.dp.imm
                elif src_type == "SRC_REG":
                    operand = self.proc.dp.get_reg(self.proc.dp.src_reg)
                else:
                    operand = 0

                dst_val = self.proc.dp.get_reg(self.proc.dp.dst_reg)
                is_sub = False

                if cmd == "ADD":
                    result = dst_val + operand
                elif cmd in ("SUB", "CMP"):
                    result = dst_val - operand
                    is_sub = True
                elif cmd == "AND":
                    result = dst_val & operand
                elif cmd == "OR":
                    result = dst_val | operand
                elif cmd == "XOR":
                    result = dst_val ^ operand
                elif cmd == "MUL":
                    result = dst_val * operand
                elif cmd == "DIV":
                    if operand == 0:
                        result = 0
                    else:
                        result = dst_val // operand
                else:
                    raise NotImplementedError(f"Unsupported command: {cmd}")

                self.proc.dp.update_flags(result, size=("b" if self.proc.dp.size == 1 else "l"), a=dst_val, b=operand, is_sub=is_sub)
                if cmd != "CMP":
                    self.proc.dp.set_reg(self.proc.dp.dst_reg, result)

            elif cmd in ("CLR", "NOT", "NEG", "ASL", "ASR", "LSL", "LSR"):
                dst_val = self.proc.dp.get_reg(self.proc.dp.dst_reg)
                # Define shift amount
                if len(micro_op.args) >= 2 and micro_op.args[1] == "IMM":
                    shift_amount = self.proc.dp.imm
                else:
                    shift_amount = 1

                if cmd == "CLR":
                    result = 0
                elif cmd == "NOT":
                    result = ~dst_val
                elif cmd == "NEG":
                    result = -dst_val
                elif cmd in ("ASL", "LSL"):
                    result = (dst_val << shift_amount) & 0xFFFFFFFF
                elif cmd == "ASR":
                    if dst_val & 0x80000000:
                        result = (dst_val >> shift_amount) | (0xFFFFFFFF << (32 - shift_amount))
                    else:
                        result = dst_val >> shift_amount
                elif cmd == "LSR":
                    result = (dst_val & 0xFFFFFFFF) >> shift_amount
                else:
                    raise NotImplementedError(f"Unsupported shift/clear command: {cmd}")

                self.proc.dp.update_flags(result, size=("b" if self.proc.dp.size == 1 else "l"))
                self.proc.dp.set_reg(self.proc.dp.dst_reg, result)

                self.proc.dp.update_flags(result, size=("b" if self.proc.dp.size == 1 else "l"))
                self.proc.dp.set_reg(self.proc.dp.dst_reg, result)
        elif op == "SET_PC":
            if micro_op.args[0] == "IMM":
                self.proc.dp.pc = self.proc.dp.imm
                self.proc.dp.pc_modified = True
        elif op == "PUSH_PC":
            sp = self.proc.dp.get_reg(7)
            sp -= 4
            self.proc.dp.set_reg(7, sp)
            ret_addr = self.proc.dp.pc + self.instr_size
            self.proc.write_data_word(sp, ret_addr)
        elif op == "POP_PC":
            sp = self.proc.dp.get_reg(7)
            ret_addr = self.proc.read_data_word(sp)
            sp += 4
            self.proc.dp.set_reg(7, sp)
            self.proc.dp.pc = ret_addr
            self.proc.dp.pc_modified = True
        elif op == "BRANCH_IF":
            take = self._eval_condition(self.proc.dp.branch_cond)
            if take:
                self.proc.dp.pc = self.proc.dp.imm
                self.proc.dp.pc_modified = True


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python machine.py <binary_file> [input_file]")
        sys.exit(1)

    bin_path = Path(sys.argv[1])
    input_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    with bin_path.open("rb") as f:
        data_count = struct.unpack("<I", f.read(4))[0]
        code_start = struct.unpack("<I", f.read(4))[0]
        data = [struct.unpack("<I", f.read(4))[0] for _ in range(data_count)]
        code = {}
        addr = code_start
        while True:
            word_bytes = f.read(4)
            if not word_bytes:
                break
            code[addr] = struct.unpack("<I", word_bytes)[0]
            addr += 4

    input_data = b""
    if input_path:
        with input_path.open("rb") as f:
            input_data = f.read()

    proc = Processor(code, data, code_start, input_data)
    proc.run()


if __name__ == "__main__":
    main()
