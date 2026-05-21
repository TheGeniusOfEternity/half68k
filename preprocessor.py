import re


def preprocess(lines: list[str]) -> list[str]:
    defines: dict[str, str] = {}
    macros: dict[str, tuple[list[str], list[str]]] = {}

    # First pass: collect %define and %macro
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("%define"):
            parts = stripped.split(None, 2)
            if len(parts) >= 3:
                name = parts[1]
                value = parts[2]
                if ";" in value:
                    value = value.split(";", 1)[0].strip()
                defines[name] = value
            i += 1
        elif stripped.startswith("%macro"):
            header = stripped[len("%macro") :].strip()
            if " " in header:
                macro_name, args_str = header.split(None, 1)
            else:
                macro_name = header
                args_str = ""
            macro_name = macro_name.strip()
            args = [a.strip() for a in args_str.split(",") if a.strip()] if args_str else []
            body_lines = []
            i += 1
            while i < len(lines):
                if lines[i].strip() == "%endmacro":
                    i += 1
                    break
                body_lines.append(lines[i])
                i += 1
            macros[macro_name] = (args, body_lines)
        else:
            i += 1

    # Second pass: processing conditional compile and macros
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # skip %define, %macro and %endmacro
        if stripped.startswith("%define") or stripped.startswith("%macro"):
            # if %macro, skip until %endmacro included
            if stripped.startswith("%macro"):
                i += 1
                while i < len(lines) and lines[i].strip() != "%endmacro":
                    i += 1
                if i < len(lines):
                    i += 1  # skip %endmacro
            else:
                i += 1
            continue
        if stripped.startswith("%endmacro"):
            i += 1
            continue

        # Conditional compile
        if stripped.startswith("%ifdef") or stripped.startswith("%ifndef"):
            if stripped.startswith("%ifdef"):
                name = stripped[len("%ifdef") :].strip()
                condition = name in defines
            else:
                name = stripped[len("%ifndef") :].strip()
                condition = name not in defines

            depth = 1
            block_if: list[str] = []
            block_else: list[str] = []
            current_block = block_if
            i += 1
            else_found = False
            while i < len(lines) and depth > 0:
                s = lines[i].strip()
                if s.startswith("%ifdef") or s.startswith("%ifndef"):
                    depth += 1
                elif s == "%else" and depth == 1:
                    if else_found:
                        raise ValueError("Multiple %else in one condition")
                    else_found = True
                    current_block = block_else
                    i += 1
                    continue
                elif s == "%endif":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                current_block.append(lines[i])
                i += 1

            selected_block = block_if if condition else block_else
            # Handle selected block
            j = 0
            while j < len(selected_block):
                bline = selected_block[j]
                for name, value in defines.items():
                    bline = re.sub(r"\b" + re.escape(name) + r"\b", value, bline)
                stripped_bline = bline.strip()
                first_token = stripped_bline.split(None, 1)[0] if stripped_bline else ""
                if first_token in macros:
                    macro_name = first_token
                    args_def, body = macros[macro_name]
                    call_args_str = stripped_bline[len(macro_name) :].strip()
                    call_args = [a.strip() for a in call_args_str.split(",") if a.strip()] if call_args_str else []
                    expanded = []
                    for body_line in body:
                        new_line = body_line
                        for k, arg_name in enumerate(args_def):
                            if k < len(call_args):
                                new_line = re.sub(r"\b" + re.escape(arg_name) + r"\b", call_args[k], new_line)
                        expanded.append(new_line)
                    selected_block = selected_block[:j] + expanded + selected_block[j + 1 :]
                    continue
                selected_block[j] = bline
                j += 1
            output.extend(selected_block)
            continue

        # Default string
        for name, value in defines.items():
            line = re.sub(r"\b" + re.escape(name) + r"\b", value, line)
        first_token = stripped.split(None, 1)[0] if stripped else ""
        if first_token in macros:
            macro_name = first_token
            args_def, body = macros[macro_name]
            call_args_str = stripped[len(macro_name) :].strip()
            call_args = [a.strip() for a in call_args_str.split(",") if a.strip()] if call_args_str else []
            for body_line in body:
                new_line = body_line
                for k, arg_name in enumerate(args_def):
                    if k < len(call_args):
                        new_line = re.sub(r"\b" + re.escape(arg_name) + r"\b", call_args[k], new_line)
                output.append(new_line)
            i += 1
            continue

        output.append(line)
        i += 1

    return output
