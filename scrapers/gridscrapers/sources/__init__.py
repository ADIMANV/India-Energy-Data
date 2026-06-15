"""Source plugin registry.

Each plugin module exposes:
    SOURCE: str                                  — plugin name
    fetch() -> list[RawResponse]                 — network I/O only, no parsing
    parse(raw: RawResponse) -> list[Datapoint]   — pure function of archived bytes
"""

from importlib import import_module
from types import ModuleType

PLUGINS = ["vidyut_pravah", "merit", "punjab_sldc", "delhi_sldc",
           "karnataka_sldc", "maha_vision"]

# sources that publish real measured in-state generation by fuel; their mix
# outranks every estimated basis (psp / cea / merit) in the freshness ladder
MEASURED_MIX_SOURCES = ("punjab_sldc", "delhi_sldc", "karnataka_sldc", "maha_vision")

# measured sources that report ONLY the state's own (partial) fleet, not its
# whole supply — their generation is a small slice of demand by design (the
# rest is central imports), so their mix must NOT be reconciled against demand.
# Their CI is explicitly in-state-generation, not consumption.
OWN_GENERATION_SOURCES = ("delhi_sldc",)


def load(name: str) -> ModuleType:
    if name not in PLUGINS:
        raise KeyError(f"unknown source {name!r}; available: {PLUGINS}")
    return import_module(f".{name}", __package__)
