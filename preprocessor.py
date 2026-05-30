import re


def preprocess(lines: list[str]) -> list[str]:
    defines: dict[str, str] = {}
    macros: dict[str, tuple[list[str], list[str]]] = {}
    output: list[str] = []

    i = 0
    skip_depth = 0  # depth of inactive conditional blocks
    while i < len(lines):
        line = lines[i]

        # Remove comment for correct directive analysis
        stripped = line.strip().split(";", 1)[0].strip()

        # --- Conditional compile ---
        if stripped.startswith("%ifdef") or stripped.startswith("%ifndef"):
            if skip_depth == 0:
                if stripped.startswith("%ifdef"):
                    name = stripped[len("%ifdef") :].strip()
                    condition = name in defines
                else:
                    name = stripped[len("%ifndef") :].strip()
                    condition = name not in defines
                if not condition:
                    skip_depth = 1
            else:
                skip_depth += 1  # nested inactive block
            i += 1
            continue

        if stripped == "%else":
            if skip_depth == 1:
                # switch activity on the same level
                skip_depth = 0
            elif skip_depth == 0:
                skip_depth = 1
            i += 1
            continue

        if stripped == "%endif":
            if skip_depth > 0:
                skip_depth -= 1
            i += 1
            continue

        # --- Skip lines inside inactive blocks ---
        if skip_depth > 0:
            i += 1
            continue

        # --- Collect %define (only in active context) ---
        if stripped.startswith("%define"):
            parts = stripped.split(None, 2)
            if len(parts) >= 3:
                name = parts[1]
                value = parts[2]
                defines[name] = value
            i += 1
            continue

        # --- Collect %macro (only in active context) ---
        if stripped.startswith("%macro"):
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
                stripped_line = lines[i].strip().split(";", 1)[0].strip()
                if stripped_line == "%endmacro":
                    i += 1
                    break
                if stripped_line.startswith("%macro"):
                    raise ValueError("Nested macros are not supported")
                body_lines.append(lines[i])
                i += 1
            macros[macro_name] = (args, body_lines)
            continue

        if stripped == "%endmacro":
            i += 1
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

            # Validate amount of args
            expected = len(args_def)
            actual = len(call_args)
            if expected != actual:
                raise ValueError(f"Macro '{macro_name}' expects {expected} argument(s), but {actual} were given.")

            for body_line in body:
                new_line = body_line
                for k, arg_name in enumerate(args_def):
                    new_line = re.sub(r"\b" + re.escape(arg_name) + r"\b", call_args[k], new_line)
                output.append(new_line)
            i += 1
            continue

        output.append(line)
        i += 1

    return output
