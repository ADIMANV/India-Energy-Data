"""Source plugin registry.

Each plugin module exposes:
    SOURCE: str                                  — plugin name
    fetch() -> list[RawResponse]                 — network I/O only, no parsing
    parse(raw: RawResponse) -> list[Datapoint]   — pure function of archived bytes
"""

from importlib import import_module
from types import ModuleType

PLUGINS = ["vidyut_pravah", "merit", "punjab_sldc", "delhi_sldc",
           "karnataka_sldc", "maha_vision", "chhattisgarh_sldc"]

# sources that publish real measured in-state generation by fuel; their mix
# outranks every estimated basis (psp / cea / merit) in the freshness ladder
MEASURED_MIX_SOURCES = ("punjab_sldc", "delhi_sldc", "karnataka_sldc",
                        "maha_vision", "chhattisgarh_sldc")

# measured sources that report ONLY a slice of the state's supply, not its
# whole demand — their generation is well under demand by design (Delhi: just
# its own gas+waste fleet; Chhattisgarh: in-state generation only, ~half its
# demand is central-sector drawl generated elsewhere). Their mix must NOT be
# reconciled against demand; their CI is in-state-generation, not consumption.
OWN_GENERATION_SOURCES = ("delhi_sldc", "chhattisgarh_sldc")


def load(name: str) -> ModuleType:
    if name not in PLUGINS:
        raise KeyError(f"unknown source {name!r}; available: {PLUGINS}")
    return import_module(f".{name}", __package__)
