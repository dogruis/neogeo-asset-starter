import re


def enum_name(prefix: str, stem: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_").upper()
    if not cleaned:
        raise ValueError(f"{stem!r}: no letters or digits to build a {prefix}_ name from")
    return f"{prefix}_{cleaned}"


class Symbols:
    def __init__(self, reserved: dict) -> None:
        self.owners = dict(reserved)

    def add(self, name: str, owner: str) -> str:
        if name in self.owners:
            raise ValueError(f"{owner} and {self.owners[name]} both become {name}; rename one")
        self.owners[name] = owner
        return name


def c_array_rows(values: list[str], per_row: int) -> list[str]:
    return [
        "    " + ", ".join(values[start : start + per_row]) + ","
        for start in range(0, len(values), per_row)
    ]
