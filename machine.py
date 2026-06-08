#!/usr/bin/env python3
"""
Half68k Processor Model
Usage: python machine.py <binary_file> [input_file] [--no-superscalar]
"""

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

from isa import (
    DST_SHIFT,
    NO_SIZE_MNEMONICS,
    OPCODE_SHIFT,
    REVERSED_OPCODES,
    SIZE_SHIFT,
    SPECIAL_ABSOLUTE,
    SPECIAL_POSTINC,
    SPECIAL_PREDEC,
    SRC_SHIFT,
    calc_instr_size_from_modes,
)

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
        # Global state
        self.regs = [0] * 8
        self.regs[7] = (DATA_MEM_SIZE * 4) - 4
        self.pc = 0
        self.flags = Flags()
        self.pc_modified = False

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
        self.flags.N = bool(res_masked & sign_mask)
        self.flags.Z = res_masked == 0
        if not is_sub:
            self.flags.C = res_masked < a_masked
            self.flags.V = ((a_masked ^ res_masked) & (b_masked ^ res_masked) & sign_mask) != 0
        else:
            self.flags.C = a_masked < b_masked
            self.flags.V = ((a_masked ^ res_masked) & ((~b_masked) & mask ^ res_masked) & sign_mask) != 0


class LaneState:
    """State of the separate execution lane"""

    def __init__(self, lane_id: int):
        self.lane_id = lane_id
        self.active = False
        self.instr_pc = 0
        self.micro_pc = 0
        self.current_microprogram: list[list[MicroOp]] | None = None
        self.instr_done = False
        self.instr_size = 0
        self.mnemonic = ""

        # Local state of the instruction
        self.imm = 0
        self.mem_addr = 0
        self.mem_data = 0
        self.opcode = 0
        self.size = 0
        self.src_mode = 0
        self.dst_mode = 0
        self.src_reg = 0
        self.dst_reg = 0
        self.ext_offset = 0
        self.branch_cond = ""


class Processor:
    def __init__(self, code: dict[int, int], data: list[int], code_start: int, input_buffer: bytes, superscalar: bool = True) -> None:
        self.code = code
        self.data_mem = bytearray(DATA_MEM_SIZE * 4)
        for i, w in enumerate(data):
            self.write_data_word(i * 4, w)
        self.input_buffer = input_buffer
        self.output_buffer = bytearray()
        self.input_pos = 0
        self.dp = DataPath()
        self.dp.pc = code_start
        self.cu = ControlUnit(self, superscalar)
        self.clock = 0
        self.instr_count = 0
        self.halted = False
        self.log_lines: list[str] = []

    @staticmethod
    def _analyze_operand(mode: int, reg: int, is_dst: bool) -> tuple[set[int], set[int], bool]:
        reads, writes, mem = set(), set(), False

        # mode 0: Immediate - read only (src)
        if mode == 0:
            pass
            # mode 1: Register
        elif mode == 1:
            if is_dst:
                writes.add(reg)
            else:
                reads.add(reg)
        # mode 2: Register Indirect - (Rn)
        elif mode in (2, 3):
            reads.add(reg)
            mem = True

        return reads, writes, mem

    def read_data_word(self, addr: int) -> int:
        if addr == IN_PORT:
            if self.input_pos >= len(self.input_buffer):
                return 0
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

        max_display = 7
        for line in self.log_lines[:max_display]:
            print(line)
        if len(self.log_lines) > max_display:
            print("...")
        output_text = self.output_buffer.decode("ascii", errors="ignore")
        print(f"Total Ticks: {self.clock}")
        print(f"Instructions Executed: {self.instr_count}")
        print(f"Output: {output_text}")

        journal_path = Path("journal.log")
        with journal_path.open("w") as f:
            f.write("\n".join(self.log_lines) + "\n")
            f.write(f"Total Ticks: {self.clock}\n")
            f.write(f"Instructions Executed: {self.instr_count}\n")
            f.write(f"Output: {output_text}\n")

    def _log(self) -> None:
        exec_str = ", ".join([f"{lane.mnemonic} (L{lane.lane_id})" for lane in self.cu.lanes if lane.active])
        if not exec_str:
            exec_str = "IDLE"
        self.log_lines.append(f"Tick: {self.clock:04d} | PC: {self.dp.pc:04X} | SP: {self.dp.regs[7]:08X} | Exec: {exec_str}")


class ControlUnit:
    def __init__(self, proc: Processor, superscalar: bool = True) -> None:
        self.proc = proc
        self.mc = MicrocodeMemory()
        self._init_microcode()
        self.superscalar = superscalar
        self.lanes = [LaneState(0), LaneState(1)]

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
        self.mc.add(
            "mv_src_displacement_reg",
            [[MicroOp("LOAD_REG_EXT", "SRC")], [MicroOp("FETCH_DISPLACEMENT_ADDR")], [MicroOp("READ_MEM")], [MicroOp("EXEC", "MOV", "MEM", "DST_REG")]],
        )
        self.mc.add("mv_reg_disp_dst", [[MicroOp("LOAD_REG_EXT", "DST")], [MicroOp("FETCH_DISPLACEMENT_ADDR_DST")], [MicroOp("WRITE_MEM", "SRC_REG")]])

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

    def step(self) -> None:
        # 1. Clear retired instructions from previous tick
        all_done = True
        has_active = False
        for lane in self.lanes:
            if lane.active:
                has_active = True
                if not lane.instr_done:
                    all_done = False

        if has_active and all_done:
            if self.proc.dp.pc_modified:
                self.proc.dp.pc_modified = False
            else:
                advance = sum(lane.instr_size for lane in self.lanes if lane.active)
                self.proc.dp.pc += advance

            for lane in self.lanes:
                lane.active = False
                lane.instr_done = False
                lane.current_microprogram = None

        # 2.If all lanes are inactive then issue new instructions
        if all(not lane.active for lane in self.lanes):
            self._issue_instructions()
            if all(not lane.active for lane in self.lanes):
                return

        # 3. Execute microcode
        for lane in self.lanes:
            if lane.active and not lane.instr_done:
                micro_step = self._fetch_micro_instr(lane)
                if micro_step is not None:
                    for micro_op in micro_step:
                        self._execute_micro_op(micro_op, lane)
                    lane.micro_pc += 1

                # Check if complete immediately after microcode step execution
                if lane.current_microprogram is None or lane.micro_pc >= len(lane.current_microprogram):
                    lane.instr_done = True

    @staticmethod
    def _fetch_micro_instr(lane: LaneState) -> list[MicroOp] | None:
        if lane.current_microprogram is None or lane.micro_pc >= len(lane.current_microprogram):
            return None
        return lane.current_microprogram[lane.micro_pc]

    @staticmethod
    def _get_deps(raw: int, pc: int, code: dict[int, int]) -> tuple[set[int], set[int], bool, bool]:
        """Searches for dependencies in instruction before injecting onto the lane"""
        opcode = (raw >> OPCODE_SHIFT) & 0x3F
        src_mode = (raw >> SRC_SHIFT) & 0x1F
        dst_mode = (raw >> DST_SHIFT) & 0x1F

        reads, writes = set(), set()
        mem, ctrl = False, False

        mnemonic = REVERSED_OPCODES.get(opcode, "")

        # Check control flow
        if mnemonic in NO_SIZE_MNEMONICS:
            ctrl = True

        src_type = (src_mode >> 3) & 0x3
        dst_type = (dst_mode >> 3) & 0x3

        # Compute shift for extension words
        src_has_ext = src_type in (0, 3)
        src_ext_addr = pc + 4
        dst_ext_addr = pc + 4 + (4 if src_has_ext else 0)

        # Analyze SOURCE operand
        if src_type == 1:  # REGISTER_DIRECT
            src_reg = src_mode & 0x7
            reads.add(src_reg)
        elif src_type == 2:  # REGISTER_INDIRECT
            src_reg = src_mode & 0x7
            reads.add(src_reg)
            mem = True
        elif src_type == 3:  # MODE_SPECIAL
            src_submode = src_mode & 0x7
            if src_submode != SPECIAL_ABSOLUTE:
                # Extract base register from extension word
                ext_word = code.get(src_ext_addr, 0)
                src_reg = (ext_word >> 16) & 0x7
                reads.add(src_reg)
                mem = True

                # POSTINC and PREDEC change base register
                if src_submode in (SPECIAL_POSTINC, SPECIAL_PREDEC):
                    writes.add(src_reg)
            else:
                mem = True  # Absolute also uses memory

        # Analyze DESTINATION operand
        if dst_type == 1:  # REGISTER_DIRECT
            dst_reg = dst_mode & 0x7
            writes.add(dst_reg)
            if mnemonic in ("add", "sub", "cmp", "and", "or", "xor", "mul", "div"):
                reads.add(dst_reg)
        elif dst_type == 2:  # REGISTER_INDIRECT
            dst_reg = dst_mode & 0x7
            reads.add(dst_reg)
            mem = True
        elif dst_type == 3:  # MODE_SPECIAL
            dst_submode = dst_mode & 0x7
            if dst_submode != SPECIAL_ABSOLUTE:
                # Extract base register from extension word
                ext_word = code.get(dst_ext_addr, 0)
                dst_reg = (ext_word >> 16) & 0x7
                reads.add(dst_reg)
                mem = True

                # POSTINC and PREDEC change base register
                if dst_submode in (SPECIAL_POSTINC, SPECIAL_PREDEC):
                    writes.add(dst_reg)
            else:
                mem = True  # Absolute also uses memory

        # Shifts and unary operations
        if mnemonic in ("lsr", "lsl", "asr", "asl", "clr", "not", "neg"):
            dst_reg = dst_mode & 0x7
            reads.add(dst_reg)
            writes.add(dst_reg)

        return reads, writes, mem, ctrl

    def _issue_instructions(self) -> None:
        """Superscalar issue logic (up to 2 independent instructions)"""
        pc = self.proc.dp.pc
        raw1 = self.proc.code.get(pc, 0)
        if raw1 == 0 and pc != 0:
            self.proc.halted = True
            return

        # Decode first instruction onto Lane 0
        self._decode_to_lane(raw1, pc, self.lanes[0])

        if self.superscalar:
            reads1, writes1, mem1, ctrl1 = self._get_deps(raw1, pc, self.proc.code)
            # Control instructions are executed strictly one by one
            if not ctrl1:
                pc2 = pc + self.lanes[0].instr_size
                raw2 = self.proc.code.get(pc2, 0)
                if raw2 != 0:
                    reads2, writes2, mem2, ctrl2 = self._get_deps(raw2, pc, self.proc.code)
                    if not ctrl2:
                        # Conflict check (RAW, WAR, WAW, memory structure)
                        conflict = False
                        if reads1.intersection(writes2) or writes1.intersection(reads2) or writes1.intersection(writes2):
                            conflict = True
                        if mem1 and mem2:  # restrict two memory usages at the same time
                            conflict = True

                        if not conflict:
                            # Both are independent - send second instruction onto Lane 1
                            self._decode_to_lane(raw2, pc2, self.lanes[1])

    def _decode_to_lane(self, raw: int, pc: int, lane: LaneState) -> None:
        self.proc.instr_count += 1
        opcode = (raw >> OPCODE_SHIFT) & 0x3F
        size = (raw >> SIZE_SHIFT) & 1
        src_mode = (raw >> SRC_SHIFT) & 0x1F
        dst_mode = (raw >> DST_SHIFT) & 0x1F

        lane.active = True
        lane.instr_pc = pc
        lane.micro_pc = 0
        lane.opcode = opcode
        lane.size = size
        lane.src_mode = src_mode
        lane.dst_mode = dst_mode
        lane.src_reg = 0
        lane.dst_reg = 0
        lane.ext_offset = 4
        lane.branch_cond = ""
        lane.instr_size = calc_instr_size_from_modes(opcode, src_mode, dst_mode)

        mnemonic = REVERSED_OPCODES.get(opcode)
        lane.mnemonic = mnemonic if mnemonic else "???"

        if mnemonic is not None:
            if mnemonic == "die":
                self.proc.halted = True
                lane.instr_done = True
                lane.current_microprogram = self.mc.get("die")
                return
            if mnemonic == "mv":
                src_type = (src_mode >> 3) & 0x3
                dst_type = (dst_mode >> 3) & 0x3
                if src_type == 0:
                    lane.current_microprogram = self.mc.get("mv_imm_reg")
                    lane.dst_reg = dst_mode & 0x7
                elif src_type == 1:
                    lane.src_reg = src_mode & 0x7
                    if dst_type == 1:
                        lane.current_microprogram = self.mc.get("mv_reg_reg")
                        lane.dst_reg = dst_mode & 0x7
                    elif dst_type == 2:
                        lane.current_microprogram = self.mc.get("mv_reg_indirect")
                        lane.dst_reg = dst_mode & 0x7
                    elif dst_type == 3:
                        sub_mode = dst_mode & 0x7
                        if sub_mode == 0:
                            lane.current_microprogram = self.mc.get("mv_reg_postinc")
                        elif sub_mode == 1:
                            lane.current_microprogram = self.mc.get("mv_reg_predec")
                        elif sub_mode == 2:
                            lane.current_microprogram = self.mc.get("mv_reg_disp_dst")
                        elif sub_mode == 3:
                            lane.current_microprogram = self.mc.get("mv_reg_absolute")
                        else:
                            raise NotImplementedError("Unsupported mv dst special mode")
                    else:
                        raise NotImplementedError("Unsupported mv - dst type")
                elif src_type == 2:
                    lane.src_reg = src_mode & 0x7
                    lane.current_microprogram = self.mc.get("mv_indirect_reg")
                    lane.dst_reg = dst_mode & 0x7
                elif src_type == 3:
                    sub_mode = src_mode & 0x7
                    if sub_mode == 0:
                        lane.current_microprogram = self.mc.get("mv_postinc_reg")
                        lane.dst_reg = dst_mode & 0x7
                    elif sub_mode == 2:
                        lane.current_microprogram = self.mc.get("mv_src_displacement_reg")
                        lane.dst_reg = dst_mode & 0x7
                    elif sub_mode == 3:
                        lane.current_microprogram = self.mc.get("mv_absolute_reg")
                        lane.dst_reg = dst_mode & 0x7
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
                lane.branch_cond = cond_map.get(mnemonic, "")
                take = self._eval_condition(lane.branch_cond)
                lane.current_microprogram = self.mc.get("branch_taken") if take else self.mc.get("branch_not_taken")
            elif mnemonic in ("clr", "not", "neg"):
                lane.dst_reg = dst_mode & 0x7
                lane.current_microprogram = self.mc.get(f"{mnemonic}_reg")
            elif mnemonic in ("add", "sub", "cmp", "and", "or", "xor", "mul", "div") or mnemonic in ("lsr", "lsl", "asr", "asl"):
                src_type = (src_mode >> 3) & 0x3
                if src_type == 0:
                    lane.current_microprogram = self.mc.get(f"{mnemonic}_imm_reg")
                    lane.dst_reg = dst_mode & 0x7
                elif src_type == 1:
                    lane.src_reg = src_mode & 0x7
                    lane.dst_reg = dst_mode & 0x7
                    lane.current_microprogram = self.mc.get(f"{mnemonic}_reg_reg")
                else:
                    raise NotImplementedError(f"Unsupported {mnemonic} src type")
            elif mnemonic in ("jmp", "jsr", "rts", "die"):
                lane.current_microprogram = self.mc.get(mnemonic)
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

    def _execute_micro_op(self, micro_op: MicroOp, lane: LaneState) -> None:
        op = micro_op.op
        if op == "HALT":
            self.proc.halted = True
            lane.instr_done = True
        elif op == "LOAD_IMM_EXT":
            lane.imm = self.proc.code.get(lane.instr_pc + lane.ext_offset, 0)
            lane.ext_offset += 4
        elif op == "LOAD_ABS_ADDR_EXT":
            lane.mem_addr = self.proc.code.get(lane.instr_pc + lane.ext_offset, 0)
            lane.ext_offset += 4
        elif op == "LOAD_REG_EXT":
            ext_word = self.proc.code.get(lane.instr_pc + lane.ext_offset, 0)
            reg_num = (ext_word >> 16) & 0x7
            if micro_op.args[0] == "SRC":
                lane.src_reg = reg_num
            else:
                lane.dst_reg = reg_num
            lane.ext_offset += 4
        elif op == "FETCH_SRC_ADDR":
            lane.mem_addr = self.proc.dp.get_reg(lane.src_reg)
        elif op == "FETCH_DST_ADDR":
            lane.mem_addr = self.proc.dp.get_reg(lane.dst_reg)
        elif op == "FETCH_DISPLACEMENT_ADDR":
            ext_word = self.proc.code.get(lane.instr_pc + lane.ext_offset - 4, 0)
            displacement = ext_word & 0xFFFF
            if displacement & 0x8000:
                displacement -= 0x10000
            base_reg_val = self.proc.dp.get_reg(lane.src_reg)
            lane.mem_addr = base_reg_val + displacement
        elif op == "FETCH_DISPLACEMENT_ADDR_DST":
            ext_word = self.proc.code.get(lane.instr_pc + lane.ext_offset - 4, 0)
            displacement = ext_word & 0xFFFF
            if displacement & 0x8000:
                displacement -= 0x10000
            base_reg_val = self.proc.dp.get_reg(lane.dst_reg)
            lane.mem_addr = base_reg_val + displacement
        elif op == "POSTINC_SRC":
            reg = lane.src_reg
            self.proc.dp.set_reg(reg, self.proc.dp.get_reg(reg) + 4)
        elif op == "POSTINC_DST":
            reg = lane.dst_reg
            self.proc.dp.set_reg(reg, self.proc.dp.get_reg(reg) + 4)
        elif op == "PREDEC_DST":
            reg = lane.dst_reg
            self.proc.dp.set_reg(reg, self.proc.dp.get_reg(reg) - 4)
        elif op == "READ_MEM":
            lane.mem_data = self.proc.read_data_word(lane.mem_addr)
        elif op == "WRITE_MEM":
            val = self.proc.dp.get_reg(lane.src_reg) if micro_op.args[0] == "SRC_REG" else 0
            self.proc.write_data_word(lane.mem_addr, val)
        elif op == "EXEC":
            cmd = micro_op.args[0]
            if cmd == "MOV":
                src = micro_op.args[1]
                dst = micro_op.args[2]
                if src == "SRC_REG":
                    val = self.proc.dp.get_reg(lane.src_reg)
                elif src == "IMM":
                    val = lane.imm
                elif src == "MEM":
                    val = lane.mem_data
                else:
                    val = 0

                if dst == "DST_REG":
                    self.proc.dp.set_reg(lane.dst_reg, val)
                self.proc.dp.update_flags(val, size=("b" if lane.size == 1 else "l"))

            elif cmd in ("ADD", "SUB", "CMP", "AND", "OR", "XOR", "MUL", "DIV"):
                src_type = micro_op.args[1]
                if src_type == "IMM":
                    operand = lane.imm
                elif src_type == "SRC_REG":
                    operand = self.proc.dp.get_reg(lane.src_reg)
                else:
                    operand = 0

                dst_val = self.proc.dp.get_reg(lane.dst_reg)
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
                    result = 0 if operand == 0 else dst_val // operand
                else:
                    raise NotImplementedError(f"Unsupported command: {cmd}")

                self.proc.dp.update_flags(result, size=("b" if lane.size == 1 else "l"), a=dst_val, b=operand, is_sub=is_sub)
                if cmd != "CMP":
                    self.proc.dp.set_reg(lane.dst_reg, result)

            elif cmd in ("CLR", "NOT", "NEG", "ASL", "ASR", "LSL", "LSR"):
                dst_val = self.proc.dp.get_reg(lane.dst_reg)
                if len(micro_op.args) >= 2 and micro_op.args[1] == "IMM":
                    shift_amount = lane.imm & 0x1F
                elif len(micro_op.args) >= 2 and micro_op.args[1] == "SRC_REG":
                    shift_amount = self.proc.dp.get_reg(lane.src_reg) & 0x1F
                else:
                    shift_amount = 1
                result = 0

                if cmd == "CLR":
                    result = 0
                elif cmd == "NOT":
                    result = ~dst_val
                elif cmd == "NEG":
                    result = -dst_val
                elif cmd in ("ASL", "LSL"):
                    result = (dst_val << shift_amount) & 0xFFFFFFFF
                elif cmd == "ASR":
                    if shift_amount == 0:
                        result = dst_val
                    elif dst_val & 0x80000000:
                        result = (dst_val >> shift_amount) | ((0xFFFFFFFF << (32 - shift_amount)) & 0xFFFFFFFF)
                    else:
                        result = dst_val >> shift_amount
                elif cmd == "LSR":
                    result = (dst_val & 0xFFFFFFFF) >> shift_amount

                self.proc.dp.update_flags(result, size=("b" if lane.size == 1 else "l"))
                self.proc.dp.set_reg(lane.dst_reg, result)

        elif op == "SET_PC":
            if micro_op.args[0] == "IMM":
                self.proc.dp.pc = lane.imm
                self.proc.dp.pc_modified = True
        elif op == "PUSH_PC":
            sp = self.proc.dp.get_reg(7)
            sp -= 4
            self.proc.dp.set_reg(7, sp)
            ret_addr = lane.instr_pc + lane.instr_size
            self.proc.write_data_word(sp, ret_addr)
        elif op == "POP_PC":
            sp = self.proc.dp.get_reg(7)
            ret_addr = self.proc.read_data_word(sp)
            sp += 4
            self.proc.dp.set_reg(7, sp)
            self.proc.dp.pc = ret_addr
            self.proc.dp.pc_modified = True
        elif op == "BRANCH_IF":
            take = self._eval_condition(lane.branch_cond)
            if take:
                self.proc.dp.pc = lane.imm
                self.proc.dp.pc_modified = True


def main(cmd_args: None | list[str] = None) -> None:
    parser = argparse.ArgumentParser(description="Half68k Processor Model")
    parser.add_argument("binary_file", help="Path to the binary file")
    parser.add_argument("input_file", nargs="?", help="Optional input file")
    parser.add_argument("--no-superscalar", action="store_true", help="Disable superscalar execution mode")
    args = parser.parse_args(cmd_args)

    bin_path = Path(args.binary_file)
    input_path = Path(args.input_file) if args.input_file else None

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

    # Superscalar is enabled by default, disable by --no-superscalar flag
    is_superscalar = not args.no_superscalar

    proc = Processor(code, data, code_start, input_data, superscalar=is_superscalar)
    proc.run()


if __name__ == "__main__":
    main()
