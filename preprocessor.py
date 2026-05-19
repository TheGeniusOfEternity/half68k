import re
from typing import List, Dict, Tuple

def preprocess(lines: List[str]) -> List[str]:
    """
    Gets source .asm file as list of lines.

    Returns list of lines with precessed macros, inserted %define
    and removed directives of conditional compile.
    """
    # State of preprocessor
    defines: Dict[str, str] = {}                         # %define NAME -> value
    macros: Dict[str, Tuple[List[str], List[str]]] = {}  # name -> (args, body)
    output: List[str] = []

    # Index of current position in source lines
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- processing %define ---
        if stripped.startswith("%define"):
            parts = stripped.split(None, 2)  # ['%define', 'NAME', 'value...']
            if len(parts) >= 3:
                name = parts[1]
                value = parts[2]
                # remove comments after value, if exists
                if ";" in value:
                    value = value.split(";", 1)[0].strip()
                defines[name] = value
            i += 1
            continue

        # --- Capture multiline macro %macro ... %endmacro ---
        if stripped.startswith("%macro"):
            # format: %macro name arg1,arg2,...
            header = stripped[len("%macro"):].strip()
            # split macros name from args
            if " " in header:
                macro_name, args_str = header.split(None, 1)
            else:
                macro_name = header
                args_str = ""
            macro_name = macro_name.strip()
            args = [a.strip() for a in args_str.split(",") if a.strip()] if args_str else []
            # read macros body until %endmacro
            body_lines = []
            i += 1
            while i < len(lines):
                line = lines[i]
                stripped_line = line.strip()
                if stripped_line == "%endmacro":
                    i += 1
                    break
                body_lines.append(line)
                i += 1
            macros[macro_name] = (args, body_lines)
            continue

        # --- conditional compile %ifdef / %ifndef ---
        if stripped.startswith("%ifdef") or stripped.startswith("%ifndef"):
            # select, what condition and name
            if stripped.startswith("%ifdef"):
                name = stripped[len("%ifdef"):].strip()
                condition = name in defines
            else:
                name = stripped[len("%ifndef"):].strip()
                condition = name not in defines

            # search for matching %else and %endif with nested condition
            depth = 1
            block_lines_if = []
            block_lines_else = []
            current_block = block_lines_if
            i += 1
            else_found = False
            while i < len(lines) and depth > 0:
                line = lines[i]
                s = line.strip()
                if s.startswith("%ifdef") or s.startswith("%ifndef"):
                    depth += 1
                elif s == "%else" and depth == 1:
                    if else_found:
                        raise ValueError("Multiple %else in one condition")
                    else_found = True
                    current_block = block_lines_else
                    i += 1
                    continue
                elif s == "%endif":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                current_block.append(line)
                i += 1

            # display matched block
            if condition:
                output.extend(block_lines_if)
            else:
                output.extend(block_lines_else)
            continue

        # --- Processing macro calls (line starts with macros name) ---
        # Check if first token is macros name
        if stripped:
            first_token = stripped.split(None, 1)[0]
            if first_token in macros:
                macro_name = first_token
                args_def, body = macros[macro_name]
                call_args_str = stripped[len(macro_name):].strip()
                call_args = [a.strip() for a in call_args_str.split(",") if a.strip()] if call_args_str else []
                for body_line in body:
                    new_line = body_line
                    for j, arg_name in enumerate(args_def):
                        if j < len(call_args):
                            # Замена только целых слов (границы \b)
                            new_line = re.sub(
                                r'\b' + re.escape(arg_name) + r'\b',
                                call_args[j],
                                new_line
                            )
                    output.append(new_line)
                i += 1
                continue

        # --- Default line: %define replacement ---
        # Replace all entries of specific names with their values
        for name, value in defines.items():
            line = line.replace(name, value)
        output.append(line)
        i += 1

    return output