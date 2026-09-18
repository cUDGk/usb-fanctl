"""Small, standard-library-only KiCad 10 schematic generator.

The generator deliberately uses a conservative connection style: each logical
net is attached to a symbol pin by a short wire stub ending in either a global
label or a KiCad power symbol.  Symbol graphics and pin metadata are copied
from the installed KiCad standard symbol libraries into ``lib_symbols``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, radians, sin
from pathlib import Path
import re
import uuid


KICAD_SYMBOL_DIR = Path(
    r"C:\Users\user\AppData\Local\Programs\KiCad\10.0\share\kicad\symbols"
)
SCHEMATIC_VERSION = 20250610
_UUID_NAMESPACE = uuid.UUID("efebf570-6949-4e77-93f0-1cc3d87b8529")
GRID = 1.27


def _fmt(value: float) -> str:
    value = round(value, 6)
    if abs(value) < 0.0000005:
        value = 0.0
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def is_on_grid(value: float, grid: float = GRID) -> bool:
    return abs(value / grid - round(value / grid)) < 1e-6


def snap(value: float, grid: float = GRID) -> float:
    return round(value / grid) * grid


def _extract_named_symbol(text: str, name: str) -> str:
    """Return a top-level symbol block from a .kicad_sym document."""
    match = re.search(r'(?m)^\s*\(symbol\s+"' + re.escape(name) + r'"\s*', text)
    if not match:
        raise KeyError(f"symbol {name!r} not found")
    start = text.find("(symbol", match.start())
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError(f"unterminated symbol {name!r}")


def _sanitize_library_symbol(
    block: str, embedded_name: str, *, source_root_name: str | None = None
) -> str:
    """Convert a library symbol block to the embedded-schematic dialect."""
    block = re.sub(
        r'^\(symbol\s+"(?:[^"\\]|\\.)*"',
        f"(symbol {_quote(embedded_name)}",
        block,
        count=1,
    )
    # These are library-editor metadata, not fields in an embedded lib_symbol.
    block = re.sub(
        r"(?m)^[ \t]*\((?:in_pos_files|show_name|do_not_autoplace|embedded_fonts)"
        r"\s+(?:yes|no)\)[ \t]*(?:\r?\n|$)",
        "",
        block,
    )
    if source_root_name:
        # A schematic lib_symbol must be self-contained and its nested unit
        # names must share the root symbol name.  Library aliases use
        # ``extends`` instead, so rename the expanded base units here.
        embedded_short_name = embedded_name.split(":", 1)[1]
        block = re.sub(
            r'(\(symbol\s+")' + re.escape(source_root_name) + r"_",
            r"\g<1>" + embedded_short_name + "_",
            block,
        )
    return block


_TOKEN_RE = re.compile(r'\s*(?:(\()|(\))|("(?:\\.|[^"\\])*")|([^\s()]+))')


def _parse_sexpr(text: str) -> list:
    tokens: list[str] = []
    position = 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if not match:
            raise ValueError(f"cannot tokenize S-expression at offset {position}")
        position = match.end()
        token = next(group for group in match.groups() if group is not None)
        tokens.append(token)
    stack: list[list] = []
    root: list | None = None
    for token in tokens:
        if token == "(":
            node: list = []
            if stack:
                stack[-1].append(node)
            else:
                root = node
            stack.append(node)
        elif token == ")":
            if not stack:
                raise ValueError("unexpected closing parenthesis")
            stack.pop()
        else:
            if not stack:
                raise ValueError("atom outside an S-expression")
            if token.startswith('"'):
                token = bytes(token[1:-1], "utf-8").decode("unicode_escape")
            stack[-1].append(token)
    if stack or root is None:
        raise ValueError("unterminated S-expression")
    return root


def _child(node: list, key: str) -> list | None:
    for item in node[1:]:
        if isinstance(item, list) and item and item[0] == key:
            return item
    return None


def _descendants(node: list, key: str):
    for item in node:
        if isinstance(item, list):
            if item and item[0] == key:
                yield item
            yield from _descendants(item, key)


@dataclass(frozen=True)
class Pin:
    number: str
    name: str
    electrical_type: str
    x: float
    y: float
    angle: float


@dataclass
class _SourceSymbol:
    source_library: str
    source_name: str
    embedded_id: str
    block: str
    pins: list[Pin]
    extends: str | None = None


class SymbolLibrary:
    """Extract and cache standard symbols, plus define simple custom symbols."""

    def __init__(self, symbol_dir: Path = KICAD_SYMBOL_DIR):
        self.symbol_dir = Path(symbol_dir)
        self._sources: dict[tuple[str, str], tuple[str, list[Pin], str | None]] = {}
        self._embedded: dict[str, _SourceSymbol] = {}

    def _load_source(self, library: str, name: str):
        key = (library, name)
        if key in self._sources:
            return self._sources[key]
        path = self.symbol_dir / f"{library}.kicad_sym"
        if not path.is_file():
            raise FileNotFoundError(f"KiCad symbol library not found: {path}")
        block = _extract_named_symbol(path.read_text(encoding="utf-8"), name)
        tree = _parse_sexpr(block)
        extends_node = _child(tree, "extends")
        extends = str(extends_node[1]) if extends_node else None
        pins: list[Pin] = []
        for pin_node in _descendants(tree, "pin"):
            if len(pin_node) < 3:
                continue
            at = _child(pin_node, "at")
            pin_name = _child(pin_node, "name")
            number = _child(pin_node, "number")
            if not at or not pin_name or not number:
                continue
            pins.append(
                Pin(
                    number=str(number[1]),
                    name=str(pin_name[1]),
                    electrical_type=str(pin_node[1]),
                    x=float(at[1]),
                    y=float(at[2]),
                    angle=float(at[3]) if len(at) > 3 else 0.0,
                )
            )
        if extends:
            _, base_pins, _ = self._load_source(library, extends)
            if not pins:
                pins = list(base_pins)
        self._sources[key] = (block, pins, extends)
        return self._sources[key]

    def require(
        self,
        lib_id: str,
        *,
        source_library: str | None = None,
        source_name: str | None = None,
    ) -> _SourceSymbol:
        if lib_id in self._embedded:
            return self._embedded[lib_id]
        requested_library, requested_name = lib_id.split(":", 1)
        source_library = source_library or requested_library
        source_name = source_name or requested_name
        block, pins, extends = self._load_source(source_library, source_name)
        expanded_root_name = None
        if extends:
            # KiCad schematic files store a flattened snapshot of aliases.
            # Embedding ``extends`` directly leaves the instance without
            # concrete pin geometry and produces dangling wire endpoints.
            block, pins, _ = self._load_source(source_library, extends)
            expanded_root_name = extends
        symbol = _SourceSymbol(
            source_library=source_library,
            source_name=source_name,
            embedded_id=lib_id,
            block=_sanitize_library_symbol(
                block, lib_id, source_root_name=expanded_root_name
            ),
            pins=list(pins),
            extends=extends,
        )
        self._embedded[lib_id] = symbol
        return symbol

    def add_custom(
        self,
        lib_id: str,
        *,
        reference_prefix: str,
        description: str,
        pins: dict[str, dict],
        body_width: float = 15.24,
        body_height: float = 20.32,
    ) -> _SourceSymbol:
        """Create a rectangular one-unit symbol from a compact pin table.

        Each pin entry needs ``name``, ``type``, ``at=(x, y)``, and ``angle``.
        Pin positions are symbol-local KiCad coordinates in millimetres.
        """
        if lib_id in self._embedded:
            raise ValueError(f"duplicate custom symbol: {lib_id}")
        short_name = lib_id.split(":", 1)[1]
        pin_objects: list[Pin] = []
        pin_text: list[str] = []
        for number, spec in pins.items():
            x, y = spec["at"]
            angle = float(spec["angle"])
            electrical_type = str(spec["type"])
            name = str(spec["name"])
            pin_objects.append(
                Pin(str(number), name, electrical_type, float(x), float(y), angle)
            )
            pin_text.append(
                "\n".join(
                    [
                        f'\t\t\t(pin {electrical_type} line',
                        f"\t\t\t\t(at {_fmt(x)} {_fmt(y)} {_fmt(angle)})",
                        "\t\t\t\t(length 2.54)",
                        f"\t\t\t\t(name {_quote(name)}",
                        "\t\t\t\t\t(effects (font (size 1.27 1.27)))",
                        "\t\t\t\t)",
                        f"\t\t\t\t(number {_quote(str(number))}",
                        "\t\t\t\t\t(effects (font (size 1.27 1.27)))",
                        "\t\t\t\t)",
                        "\t\t\t)",
                    ]
                )
            )
        half_w = body_width / 2
        half_h = body_height / 2
        block = f"""(symbol {_quote(lib_id)}
\t(pin_names (offset 1.016))
\t(exclude_from_sim no)
\t(in_bom yes)
\t(on_board yes)
\t(duplicate_pin_numbers_are_jumpers no)
\t(property "Reference" {_quote(reference_prefix)}
\t\t(at {-half_w} {half_h + 2.54} 0)
\t\t(effects (font (size 1.27 1.27)) (justify left))
\t)
\t(property "Value" {_quote(short_name)}
\t\t(at {-half_w} {half_h + 5.08} 0)
\t\t(effects (font (size 1.27 1.27)) (justify left))
\t)
\t(property "Footprint" ""
\t\t(at 0 0 0) (hide yes)
\t\t(effects (font (size 1.27 1.27)))
\t)
\t(property "Datasheet" "~"
\t\t(at 0 0 0) (hide yes)
\t\t(effects (font (size 1.27 1.27)))
\t)
\t(property "Description" {_quote(description)}
\t\t(at 0 0 0) (hide yes)
\t\t(effects (font (size 1.27 1.27)))
\t)
\t(symbol {_quote(short_name + "_0_1")}
\t\t(rectangle
\t\t\t(start {_fmt(-half_w)} {_fmt(half_h)})
\t\t\t(end {_fmt(half_w)} {_fmt(-half_h)})
\t\t\t(stroke (width 0) (type default))
\t\t\t(fill (type background))
\t\t)
\t)
\t(symbol {_quote(short_name + "_1_1")}
{chr(10).join(pin_text)}
\t)
)"""
        symbol = _SourceSymbol(
            source_library=lib_id.split(":", 1)[0],
            source_name=short_name,
            embedded_id=lib_id,
            block=block,
            pins=pin_objects,
        )
        self._embedded[lib_id] = symbol
        return symbol

    @property
    def embedded_blocks(self) -> list[str]:
        return [symbol.block for symbol in self._embedded.values()]


@dataclass
class SymbolInstance:
    lib_id: str
    reference: str
    value: str
    footprint: str
    x: float
    y: float
    rotation: float
    pins: list[Pin]
    uuid: str
    in_bom: bool = True
    on_board: bool = True
    reference_at: tuple[float, float] | None = None
    value_at: tuple[float, float] | None = None
    property_justify: str | None = None

    def pins_named(self, name: str) -> list[Pin]:
        result = [pin for pin in self.pins if pin.name.casefold() == name.casefold()]
        if not result:
            raise KeyError(f"{self.reference}: pin named {name!r} not found")
        return result

    def pin_number(self, number: str) -> Pin:
        result = [pin for pin in self.pins if pin.number == str(number)]
        if not result:
            raise KeyError(f"{self.reference}: pin {number!r} not found")
        if len(result) != 1:
            raise ValueError(f"{self.reference}: pin {number!r} is ambiguous")
        return result[0]

    def pin_endpoint(self, pin: Pin) -> tuple[float, float]:
        theta = radians(self.rotation)
        # Symbol-local Y is Cartesian (up), while page Y grows downward.
        # At 90°, local (x, y) therefore becomes (-y, -x) on the page.
        x = self.x + pin.x * cos(theta) - pin.y * sin(theta)
        y = self.y - pin.x * sin(theta) - pin.y * cos(theta)
        return snap(x), snap(y)

    def outward_vector(self, pin: Pin) -> tuple[int, int]:
        # Pin angle points from the terminal into the body.  Convert the
        # opposite direction through the instance rotation into page axes.
        theta = radians(self.rotation + pin.angle)
        dx = -cos(theta)
        dy = sin(theta)
        if abs(dx) >= abs(dy):
            return (-1 if dx < 0 else 1, 0)
        return (0, -1 if dy < 0 else 1)


@dataclass
class _Wire:
    x1: float
    y1: float
    x2: float
    y2: float
    uuid: str


@dataclass
class _GlobalLabel:
    name: str
    x: float
    y: float
    angle: float
    uuid: str


@dataclass
class _NoConnect:
    x: float
    y: float
    uuid: str


class Schematic:
    def __init__(
        self,
        *,
        project_name: str,
        title: str,
        paper: str = "A3",
        symbol_dir: Path = KICAD_SYMBOL_DIR,
    ):
        self.project_name = project_name
        self.title = title
        self.paper = paper
        self.library = SymbolLibrary(symbol_dir)
        self.root_uuid = str(uuid.uuid5(_UUID_NAMESPACE, f"{project_name}/root"))
        self.symbols: dict[str, SymbolInstance] = {}
        self._symbol_order: list[SymbolInstance] = []
        self._wires: list[_Wire] = []
        self._labels: list[_GlobalLabel] = []
        self._no_connects: list[_NoConnect] = []
        self._used_pins: set[tuple[str, str]] = set()
        self._power_index = 0
        self._item_index = 0

    def _uuid(self, key: str) -> str:
        return str(uuid.uuid5(_UUID_NAMESPACE, f"{self.project_name}/{key}"))

    def _next_uuid(self, kind: str) -> str:
        self._item_index += 1
        return self._uuid(f"{kind}/{self._item_index}")

    def add_symbol(
        self,
        lib_id: str,
        reference: str,
        value: str,
        footprint: str,
        at: tuple[float, float],
        rotation: float = 0,
        *,
        source_library: str | None = None,
        source_name: str | None = None,
        in_bom: bool = True,
        on_board: bool = True,
        reference_at: tuple[float, float] | None = None,
        value_at: tuple[float, float] | None = None,
        property_justify: str | None = None,
    ) -> SymbolInstance:
        if reference in self.symbols:
            raise ValueError(f"duplicate reference: {reference}")
        x, y = at
        if not is_on_grid(x) or not is_on_grid(y) or rotation % 90:
            raise ValueError(f"{reference}: placement must use 1.27 mm grid and 90° rotation")
        for label, position in (
            ("reference_at", reference_at),
            ("value_at", value_at),
        ):
            if position and not all(is_on_grid(value) for value in position):
                raise ValueError(f"{reference}: {label} must use the 1.27 mm grid")
        if property_justify not in (None, "left", "right"):
            raise ValueError(f"{reference}: unsupported property justification")
        definition = self.library.require(
            lib_id, source_library=source_library, source_name=source_name
        )
        instance = SymbolInstance(
            lib_id=lib_id,
            reference=reference,
            value=value,
            footprint=footprint,
            x=x,
            y=y,
            rotation=rotation % 360,
            pins=list(definition.pins),
            uuid=self._uuid(f"symbol/{reference}"),
            in_bom=in_bom,
            on_board=on_board,
            reference_at=reference_at,
            value_at=value_at,
            property_justify=property_justify,
        )
        self.symbols[reference] = instance
        self._symbol_order.append(instance)
        return instance

    def _resolve_pins(self, reference: str, selector: str) -> list[Pin]:
        instance = self.symbols[reference]
        if selector.startswith("name:"):
            return instance.pins_named(selector[5:])
        return [instance.pin_number(selector)]

    def _claim_pin(self, reference: str, pin: Pin):
        key = (reference, pin.number)
        if key in self._used_pins:
            raise ValueError(f"{reference}.{pin.number} connected more than once")
        self._used_pins.add(key)

    def _add_wire(self, start: tuple[float, float], end: tuple[float, float]):
        if start == end:
            return
        length = abs(end[0] - start[0]) + abs(end[1] - start[1])
        if length + 1e-6 < 2.54:
            raise ValueError(
                f"refusing degenerate wire stub: {start} -> {end} ({length} mm)"
            )
        self._wires.append(
            _Wire(*start, *end, uuid=self._next_uuid("wire"))
        )

    def _signal_stub(
        self, net_name: str, instance: SymbolInstance, pin: Pin, stub: float
    ):
        start = instance.pin_endpoint(pin)
        dx, dy = instance.outward_vector(pin)
        end = (snap(start[0] + dx * stub), snap(start[1] + dy * stub))
        self._add_wire(start, end)
        label_angle = 180.0 if dx < 0 else 0.0
        self._labels.append(
            _GlobalLabel(
                net_name, end[0], end[1], label_angle, self._next_uuid("label")
            )
        )

    def _power_stub(
        self, net_name: str, instance: SymbolInstance, pin: Pin, stub: float
    ):
        start = instance.pin_endpoint(pin)
        dx, dy = instance.outward_vector(pin)
        # Power symbols are conventionally vertical.  Keep the stub short and
        # place the symbol terminal exactly at its end.
        end = (snap(start[0] + dx * stub), snap(start[1] + dy * stub))
        self._add_wire(start, end)
        if net_name == "GND":
            lib_id, value = "power:GND", "GND"
        elif net_name == "+3V3":
            lib_id, value = "power:+3V3", "+3V3"
        else:
            # VCC is a global power symbol whose instance value may name an
            # arbitrary positive rail such as VBUS_5V or P5V_N.
            lib_id, value = "power:VCC", net_name
        self._power_index += 1
        self.add_symbol(
            lib_id,
            f"#PWR{self._power_index:03d}",
            value,
            "",
            end,
            in_bom=False,
            on_board=False,
        )

    def connect(
        self,
        net_name: str,
        endpoints: list[tuple[str, str]],
        *,
        power: bool = False,
        signal_stub: float = 5.08,
        power_stub: float = 2.54,
    ):
        """Connect a named net to pin selectors.

        A selector is a pin number or ``name:PIN_NAME``.  A name selector
        intentionally expands to every same-named pin (for USB-C stacked
        supply pins, grounds, and similar symbols).
        """
        seen_positions: set[tuple[float, float]] = set()
        for reference, selector in endpoints:
            instance = self.symbols[reference]
            for pin in self._resolve_pins(reference, selector):
                self._claim_pin(reference, pin)
                position = instance.pin_endpoint(pin)
                if position in seen_positions:
                    continue
                seen_positions.add(position)
                if power:
                    self._power_stub(
                        net_name, instance, pin, max(power_stub, 2.54)
                    )
                else:
                    self._signal_stub(
                        net_name, instance, pin, max(signal_stub, 5.08)
                    )

    def add_power_flag(self, net_name: str, at: tuple[float, float]):
        """Add one PWR_FLAG and connect it to a named power-symbol instance."""
        self._power_index += 1
        flag = self.add_symbol(
            "power:PWR_FLAG",
            f"#FLG{self._power_index:03d}",
            "PWR_FLAG",
            "",
            at,
            in_bom=False,
            on_board=False,
        )
        flag_pin = flag.pin_number("1")
        start = flag.pin_endpoint(flag_pin)
        # Keep the flag graphic and the rail-name power symbol vertically
        # separated.  Positive rails point upward; GND points downward.
        power_dy = 7.62 if net_name == "GND" else -7.62
        end = (start[0], snap(start[1] + power_dy))
        self._add_wire(start, end)
        if net_name == "+3V3":
            lib_id = "power:+3V3"
        elif net_name == "GND":
            lib_id = "power:GND"
        else:
            lib_id = "power:VCC"
        self._power_index += 1
        self.add_symbol(
            lib_id,
            f"#PWR{self._power_index:03d}",
            net_name,
            "",
            end,
            in_bom=False,
            on_board=False,
        )

    def mark_unused_pins(self):
        seen_positions: set[tuple[float, float]] = set()
        for instance in self._symbol_order:
            if instance.reference.startswith("#"):
                continue
            for pin in instance.pins:
                key = (instance.reference, pin.number)
                if key in self._used_pins:
                    continue
                if pin.electrical_type == "no_connect":
                    self._used_pins.add(key)
                    continue
                position = instance.pin_endpoint(pin)
                if position not in seen_positions:
                    self._no_connects.append(
                        _NoConnect(*position, uuid=self._next_uuid("no_connect"))
                    )
                    seen_positions.add(position)
                self._used_pins.add(key)

    def _render_instance(self, instance: SymbolInstance) -> str:
        is_power = instance.lib_id.startswith("power:")
        is_port_connector = instance.lib_id == "Connector_Generic:Conn_01x04"
        is_small_esd = instance.lib_id == "Power_Protection:USBLC6-2SC6"
        if is_port_connector:
            ref_x = instance.x + 7.62
            ref_y = instance.y - 2.54
            value_x = instance.x + 7.62
            value_y = instance.y
            visible_justify = " (justify left)"
        elif is_small_esd:
            ref_x = instance.x - 10.16
            ref_y = instance.y - 7.62
            value_x = instance.x - 10.16
            value_y = instance.y - 5.08
            visible_justify = " (justify left)"
        elif is_power:
            ref_x = instance.x
            ref_y = instance.y
            value_x = instance.x
            value_y = (
                instance.y + 5.08
                if instance.lib_id == "power:GND"
                else instance.y - 5.08
            )
            visible_justify = ""
        else:
            ref_x = instance.x - 2.54
            ref_y = instance.y - 3.81
            value_x = ref_x
            value_y = instance.y - 1.27
            visible_justify = ""
        if instance.reference_at:
            ref_x, ref_y = instance.reference_at
        if instance.value_at:
            value_x, value_y = instance.value_at
        if instance.property_justify:
            visible_justify = f" (justify {instance.property_justify})"
        hidden = "\n\t\t\t(hide yes)"
        ref_hidden = hidden if instance.reference.startswith("#") else ""
        value_hidden = hidden if instance.lib_id == "power:PWR_FLAG" else ""
        pin_entries = "\n".join(
            f'\t\t(pin {_quote(pin.number)}\n'
            f'\t\t\t(uuid {_quote(self._uuid(f"symbol/{instance.reference}/pin/{pin.number}"))})\n'
            "\t\t)"
            for pin in instance.pins
        )
        return f"""\t(symbol
\t\t(lib_id {_quote(instance.lib_id)})
\t\t(at {_fmt(instance.x)} {_fmt(instance.y)} {_fmt(instance.rotation)})
\t\t(unit 1)
\t\t(exclude_from_sim no)
\t\t(in_bom {'yes' if instance.in_bom else 'no'})
\t\t(on_board {'yes' if instance.on_board else 'no'})
\t\t(dnp no)
\t\t(uuid {_quote(instance.uuid)})
\t\t(property "Reference" {_quote(instance.reference)}
\t\t\t(at {_fmt(ref_x)} {_fmt(ref_y)} 0){ref_hidden}
\t\t\t(effects (font (size 1.27 1.27)){visible_justify})
\t\t)
\t\t(property "Value" {_quote(instance.value)}
\t\t\t(at {_fmt(value_x)} {_fmt(value_y)} 0){value_hidden}
\t\t\t(effects (font (size 1.27 1.27)){visible_justify})
\t\t)
\t\t(property "Footprint" {_quote(instance.footprint)}
\t\t\t(at {_fmt(instance.x)} {_fmt(instance.y)} 0){hidden}
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Datasheet" "~"
\t\t\t(at {_fmt(instance.x)} {_fmt(instance.y)} 0){hidden}
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Description" ""
\t\t\t(at {_fmt(instance.x)} {_fmt(instance.y)} 0){hidden}
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
{pin_entries}
\t\t(instances
\t\t\t(project {_quote(self.project_name)}
\t\t\t\t(path {_quote('/' + self.root_uuid)}
\t\t\t\t\t(reference {_quote(instance.reference)})
\t\t\t\t\t(unit 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t)"""

    def render(self) -> str:
        lib_symbols = "\n".join(
            "\n".join("\t\t" + line for line in block.splitlines())
            for block in self.library.embedded_blocks
        )
        no_connects = "\n".join(
            f"\t(no_connect\n\t\t(at {_fmt(item.x)} {_fmt(item.y)})\n"
            f"\t\t(uuid {_quote(item.uuid)})\n\t)"
            for item in self._no_connects
        )
        wires = "\n".join(
            f"\t(wire\n\t\t(pts (xy {_fmt(item.x1)} {_fmt(item.y1)})"
            f" (xy {_fmt(item.x2)} {_fmt(item.y2)}))\n"
            f"\t\t(stroke (width 0) (type default))\n"
            f"\t\t(uuid {_quote(item.uuid)})\n\t)"
            for item in self._wires
        )
        labels = "\n".join(
            f"\t(global_label {_quote(item.name)}\n"
            f"\t\t(shape output)\n"
            f"\t\t(at {_fmt(item.x)} {_fmt(item.y)} {_fmt(item.angle)})\n"
            f"\t\t(fields_autoplaced yes)\n"
            f"\t\t(effects (font (size 1.27 1.27)))\n"
            f"\t\t(uuid {_quote(item.uuid)})\n"
            f'\t\t(property "Intersheetrefs" "${{INTERSHEET_REFS}}"\n'
            f"\t\t\t(at {_fmt(item.x)} {_fmt(item.y)} 0)\n"
            f"\t\t\t(hide yes)\n"
            f"\t\t\t(effects (font (size 1.27 1.27)))\n"
            f"\t\t)\n\t)"
            for item in self._labels
        )
        instances = "\n".join(
            self._render_instance(instance) for instance in self._symbol_order
        )
        sections = "\n".join(
            section for section in (no_connects, wires, labels, instances) if section
        )
        return f"""(kicad_sch
\t(version {SCHEMATIC_VERSION})
\t(generator "kischgen")
\t(generator_version "1.0")
\t(uuid {_quote(self.root_uuid)})
\t(paper {_quote(self.paper)})
\t(title_block
\t\t(title {_quote(self.title)})
\t\t(comment 1 "Generated from hub/DESIGN.md; edit the generator, not this file")
\t)
\t(lib_symbols
{lib_symbols}
\t)
{sections}
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
"""

    def write(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8", newline="\n")
