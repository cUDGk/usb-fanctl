"""Small pcbnew-based PCB generator shared by hub, node, and dongle.

Run board-specific entry points with KiCad's bundled Python.  The generator
loads only installed KiCad footprints, assigns the schematic nets to physical
pads, creates a two-layer outline, and exports a Specctra DSN for freerouting.
After routing, ``import_and_finish`` imports the SES file and adds filled GND
zones on both copper layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import re
from types import ModuleType
from typing import Iterable

import pcbnew
from PIL import Image, ImageFilter
from check_silk_tracks import (
    circle_hits_box,
    footprint_body_box,
    footprint_component_box,
    point_box_distance,
    segment_hits_box,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
KICAD_ROOT = Path(r"C:\Users\user\AppData\Local\Programs\KiCad\10.0\share\kicad")
FOOTPRINT_ROOT = KICAD_ROOT / "footprints"
PROJECT_FOOTPRINT_ROOT = REPO_ROOT / "lib"


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    rotation: float = 0.0
    side: str = "F"


@dataclass
class BoardConfig:
    name: str
    module: ModuleType
    output: Path
    origin: tuple[float, float]
    size: tuple[float, float]
    placements: dict[str, Placement]
    holes: list[tuple[float, float]]
    silk_text: list[tuple[str, float, float, float]] = field(default_factory=list)
    pad_aliases: dict[tuple[str, str], str] = field(default_factory=dict)
    antenna_keepout: tuple[float, float, float, float] | None = None
    clearance: float = 0.2
    reference_positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    silk_graphics_to_fab: set[str] = field(default_factory=set)
    logo_rect: tuple[float, float, float, float] | None = None
    logo_rule_rect: tuple[float, float, float, float] | None = None
    logo_image: Path | None = None
    logo_glyph_count: int = 0
    logo_min_gap: float = 0.18
    avoid_reference_routing: bool = False
    placement_overrides_after_import: set[str] = field(default_factory=set)
    zone_disconnected_pads: set[tuple[str, str]] = field(default_factory=set)
    pre_routes: list[tuple[str, str, float, list[tuple[float, float]]]] = field(
        default_factory=list
    )
    pre_vias: list[tuple[str, float, float]] = field(default_factory=list)
    replacement_routes: list[
        tuple[str, str, float, list[tuple[float, float]]]
    ] = field(default_factory=list)
    replacement_vias: list[tuple[str, float, float]] = field(default_factory=list)
    route_removals: list[
        tuple[str, str, tuple[float, float], tuple[float, float]]
    ] = field(default_factory=list)
    post_routes: list[tuple[str, str, float, list[tuple[float, float]]]] = field(
        default_factory=list
    )
    post_vias: list[tuple[str, float, float]] = field(default_factory=list)
    copper_zones: list[
        tuple[str, str, tuple[float, float, float, float]]
    ] = field(default_factory=list)
    zone_keepouts: list[
        tuple[str, tuple[float, float, float, float]]
    ] = field(default_factory=list)
    # 自動配線に渡さないネット (大電流ネットはポリゴンで手配置する)
    unrouted_nets: set[str] = field(default_factory=set)
    # DSN 出力時だけ置く配線禁止領域 (layer, 頂点列)。SES 取込後に削除する
    route_keepouts: list[tuple[str, list[tuple[float, float]]]] = field(default_factory=list)
    # 大電流ポリゴン (net, layer, 頂点列, 優先度)。パッドはサーマルなしで直結する
    power_zones: list[tuple[str, str, list[tuple[float, float]], int]] = field(default_factory=list)
    # 配線後に追加するビア径の既定 (mm)
    stitch_via: tuple[float, float] = (0.5, 0.3)
    # 銅層数。4 のとき In1/In2 はプレーン扱いで自動配線に使わせない
    copper_layers: int = 2
    # DSN に書く導体プレーン (net, layer, 頂点列)。freerouting はビアで落として接続する
    dsn_planes: list[tuple[str, str, list[tuple[float, float]]]] = field(default_factory=list)
    power_track_width: float = 0.5
    # 配線前にパッド脇へ自動でビアを置くネット (内層プレーンに落とす)
    auto_via_nets: set[str] = field(default_factory=set)
    # 露出パッド内に打つビア {(ref, pad): [(dx, dy), ...]}
    pad_vias: dict = field(default_factory=dict)
    pad_via_skip: set = field(default_factory=set)

    @property
    def dsn(self) -> Path:
        return self.output.with_suffix(".dsn")


# 各基板の kicad_pro の min_via_diameter と一致させる下限。JLCPCB の製造下限
# (0.45mm 外径 / 0.3mm 穴) には余裕がある。
# 0.6mm にしないのは、node の UP_IN ビアが 0.6mm だと隣の IMU_SCL トラックとの
# クリアランスが 0.121mm となり JLCPCB の最小 0.127mm を割るため。狭所では
# 0.5mm を許し、手動で置くビア (post_vias 等) は従来どおり 0.6mm を使う。
VIA_MIN_DIAMETER_MM = 0.5


def mm(value: float) -> int:
    return pcbnew.FromMM(value)


def point(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I_MM(x, y)


def load_footprint(identifier: str) -> pcbnew.FOOTPRINT:
    library, name = identifier.split(":", 1)
    candidates = [
        PROJECT_FOOTPRINT_ROOT / f"{library}.pretty",
        FOOTPRINT_ROOT / f"{library}.pretty",
    ]
    for library_path in candidates:
        if not library_path.is_dir():
            continue
        footprint = pcbnew.FootprintLoad(str(library_path), name)
        if footprint is not None:
            if library_path == PROJECT_FOOTPRINT_ROOT / f"{library}.pretty":
                footprint.SetFPID(pcbnew.LIB_ID(library, name))
            return footprint
    raise FileNotFoundError(
        f"KiCad footprint not found: {identifier}; searched {candidates}"
    )


def _add_outline(board: pcbnew.BOARD, origin: tuple[float, float], size: tuple[float, float]):
    x0, y0 = origin
    x1, y1 = x0 + size[0], y0 + size[1]
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for start, end in zip(corners, corners[1:] + corners[:1]):
        line = pcbnew.PCB_SHAPE(board)
        line.SetShape(pcbnew.SHAPE_T_SEGMENT)
        line.SetLayer(pcbnew.Edge_Cuts)
        line.SetWidth(mm(0.05))
        line.SetStart(point(*start))
        line.SetEnd(point(*end))
        board.Add(line)


def _add_silk_text(
    board: pcbnew.BOARD, text: str, x: float, y: float, rotation: float = 0.0
):
    item = pcbnew.PCB_TEXT(board)
    item.SetText(text)
    item.SetLayer(pcbnew.F_SilkS)
    item.SetPosition(point(x, y))
    item.SetTextSize(point(1.0, 1.0))
    item.SetTextThickness(mm(0.15))
    item.SetTextAngleDegrees(rotation)
    board.Add(item)


def _add_silk_rectangle(
    board: pcbnew.BOARD, center_x: float, center_y: float, width: float, height: float
):
    x0, x1 = center_x - width / 2, center_x + width / 2
    y0, y1 = center_y - height / 2, center_y + height / 2
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for start, end in zip(corners, corners[1:] + corners[:1]):
        line = pcbnew.PCB_SHAPE(board)
        line.SetShape(pcbnew.SHAPE_T_SEGMENT)
        line.SetLayer(pcbnew.F_SilkS)
        line.SetWidth(mm(0.15))
        line.SetStart(point(*start))
        line.SetEnd(point(*end))
        board.Add(line)


def _add_logo_rule_area(
    board: pcbnew.BOARD, center_x: float, center_y: float, width: float, height: float
):
    x0, x1 = center_x - width / 2, center_x + width / 2
    y0, y1 = center_y - height / 2, center_y + height / 2
    area = pcbnew.ZONE(board)
    area.SetIsRuleArea(True)
    area.SetLayer(pcbnew.F_Cu)
    # Footprint courtyards can extend beyond the actual body (notably USB-C).
    # Pads are forbidden below, while body clearance is validated separately.
    area.SetDoNotAllowFootprints(False)
    area.SetDoNotAllowPads(True)
    area.SetDoNotAllowTracks(True)
    area.SetDoNotAllowVias(True)
    area.SetDoNotAllowZoneFills(False)
    outline = area.Outline()
    outline.NewOutline()
    for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        outline.Append(point(x, y))
    board.Add(area)


def _trace_bitmap_loops(mask: list[list[bool]]) -> list[list[tuple[int, int]]]:
    """Trace clockwise pixel-boundary loops with foreground on the right."""
    height, width = len(mask), len(mask[0])
    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for y, row in enumerate(mask):
        for x, filled in enumerate(row):
            if not filled:
                continue
            if y == 0 or not mask[y - 1][x]:
                edges.add(((x, y), (x + 1, y)))
            if x == width - 1 or not mask[y][x + 1]:
                edges.add(((x + 1, y), (x + 1, y + 1)))
            if y == height - 1 or not mask[y + 1][x]:
                edges.add(((x + 1, y + 1), (x, y + 1)))
            if x == 0 or not mask[y][x - 1]:
                edges.add(((x, y + 1), (x, y)))

    outgoing: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for start, end in edges:
        outgoing.setdefault(start, set()).add(end)
    directions = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
    loops: list[list[tuple[int, int]]] = []
    while edges:
        first = next(iter(edges))
        start, current = first
        edges.remove(first)
        loop = [start, current]
        previous = start
        while current != start:
            candidates = [
                end for end in outgoing.get(current, ()) if (current, end) in edges
            ]
            if not candidates:
                raise ValueError("open contour while tracing logo bitmap")
            incoming = directions[(current[0] - previous[0], current[1] - previous[1])]
            # At a diagonal pixel contact, keep the foreground on the right:
            # right turn, straight, left turn, then backtrack.
            priorities = {
                (incoming + 1) % 4: 0,
                incoming: 1,
                (incoming - 1) % 4: 2,
                (incoming + 2) % 4: 3,
            }
            end = min(
                candidates,
                key=lambda p: priorities[
                    directions[(p[0] - current[0], p[1] - current[1])]
                ],
            )
            edges.remove((current, end))
            previous, current = current, end
            loop.append(current)
        loops.append(loop[:-1])
    return loops


def _simplify_orthogonal_loop(
    loop: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Remove redundant collinear raster vertices without thinning the logo."""
    points = loop[:]
    changed = True
    while changed and len(points) > 3:
        changed = False
        result: list[tuple[int, int]] = []
        count = len(points)
        for index, current in enumerate(points):
            previous = points[index - 1]
            following = points[(index + 1) % count]
            if (
                (previous[0] == current[0] == following[0])
                or (previous[1] == current[1] == following[1])
            ):
                changed = True
            else:
                result.append(current)
        points = result
    return points


def _signed_area(loop: list[tuple[int, int]]) -> float:
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1])
    ) / 2


def _point_in_polygon(point_xy: tuple[int, int], polygon: list[tuple[int, int]]) -> bool:
    x, y = point_xy
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if crossing > x:
                inside = not inside
    return inside


def _add_silk_logo(
    board: pcbnew.BOARD,
    image_path: Path,
    center_x: float,
    center_y: float,
    frame_width: float,
    frame_height: float,
    glyph_count: int = 0,
    minimum_gap: float = 0.18,
):
    """Threshold, gap-open, contour-trace, and embed a raster logo as F.SilkS."""
    rgba = Image.open(image_path).convert("RGBA")
    white = Image.new("RGBA", rgba.size, "white")
    gray = Image.alpha_composite(white, rgba).convert("L")
    foreground = gray.point(lambda value: 255 if value < 128 else 0)
    crop_box = foreground.getbbox()
    if crop_box is None:
        raise ValueError(f"logo contains no pixels below threshold 128: {image_path}")
    gray = gray.crop(crop_box)

    usable_width = frame_width - 0.6
    usable_height = frame_height - 0.6
    source_aspect = gray.width / gray.height
    target_width = min(usable_width, usable_height * source_aspect)
    target_height = target_width / source_aspect
    # 0.025 mm/px: fine enough that the traced outline follows the italic
    # curves without visible stairsteps at silkscreen resolution.
    raster_pitch = 0.025
    raster_width = max(1, round(target_width / raster_pitch))
    raster_pitch = target_width / raster_width
    raster_height = max(1, round(target_height / raster_pitch))
    resized = gray.resize((raster_width, raster_height), Image.Resampling.LANCZOS)
    # Faithful conversion: threshold only.  Erosion/opening/glyph-cut passes
    # were removed after they visibly notched the italic strokes (掠れ).  The
    # source wordmark's strokes are >=0.4 mm at all board scales, and slight
    # ink bleed in sub-0.15 mm inter-letter gaps reads better than cuts.
    binary = resized.point(lambda value: 255 if value < 128 else 0)
    measured_gaps: list[float] = []
    pixels = binary.load()
    mask = [
        [pixels[x, y] >= 128 for x in range(raster_width)]
        for y in range(raster_height)
    ]
    loops = [
        _simplify_orthogonal_loop(loop)
        for loop in _trace_bitmap_loops(mask)
        if len(loop) >= 3
    ]
    outers = [loop for loop in loops if _signed_area(loop) > 0]
    holes = [loop for loop in loops if _signed_area(loop) < 0]
    x0 = center_x - raster_width * raster_pitch / 2
    y0 = center_y - raster_height * raster_pitch / 2
    for outer in outers:
        poly = pcbnew.SHAPE_POLY_SET()
        outline_index = poly.NewOutline()
        for x, y in outer:
            poly.Append(point(x0 + x * raster_pitch, y0 + y * raster_pitch), outline_index)
        for hole in holes:
            if _point_in_polygon(hole[0], outer):
                hole_index = poly.NewHole(outline_index)
                for x, y in hole:
                    poly.Append(
                        point(x0 + x * raster_pitch, y0 + y * raster_pitch),
                        outline_index,
                        hole_index,
                    )
        graphic = pcbnew.PCB_SHAPE(board)
        graphic.SetShape(pcbnew.SHAPE_T_POLY)
        graphic.SetLayer(pcbnew.F_SilkS)
        graphic.SetFilled(True)
        graphic.SetWidth(0)
        graphic.SetPolyShape(poly)
        board.Add(graphic)
    printed_bbox = binary.getbbox()
    if printed_bbox:
        print(
            f"{image_path.name}: silk {printed_bbox[2] - printed_bbox[0]:.0f}x"
            f"{printed_bbox[3] - printed_bbox[1]:.0f} px = "
            f"{(printed_bbox[2] - printed_bbox[0]) * raster_pitch:.3f}x"
            f"{(printed_bbox[3] - printed_bbox[1]) * raster_pitch:.3f} mm; "
            f"minimum glyph gap "
            f"{min(measured_gaps) if measured_gaps else 0.0:.3f} mm"
        )


def _configure_rules(
    board: pcbnew.BOARD, power_nets: Iterable[str], clearance: float, layers: int = 2,
    power_width: float = 0.5,
):
    settings = board.GetDesignSettings()
    settings.SetBoardThickness(mm(1.6))
    settings.SetCopperLayerCount(layers)
    settings.m_MinClearance = mm(clearance)
    settings.m_TrackMinWidth = mm(0.2)
    settings.m_ViasMinSize = mm(0.5)
    settings.m_MicroViasMinDrill = mm(0.3)
    # The ESP32-S3-WROOM footprint has 0.20 mm plated thermal-pad holes.
    # Routed vias remain 0.60/0.30 mm through the net-class definitions.
    settings.m_MinThroughDrill = mm(0.2)
    settings.m_HoleClearance = mm(clearance)
    settings.m_HoleToHoleMin = mm(clearance)
    settings.m_CopperEdgeClearance = mm(clearance)
    # Dense USB-C/LGA pads can legitimately expose one thermal spoke while
    # remaining connected to a routed ground track and the opposite plane.
    settings.m_MinResolvedSpokes = 1

    net_settings = settings.m_NetSettings
    default = net_settings.GetDefaultNetclass()
    default.SetClearance(mm(clearance))
    default.SetTrackWidth(mm(0.2))
    default.SetViaDiameter(mm(0.5))
    default.SetViaDrill(mm(0.3))

    power = pcbnew.NETCLASS("Power")
    power.SetClearance(mm(clearance))
    power.SetTrackWidth(mm(power_width))
    power.SetViaDiameter(mm(0.5))
    power.SetViaDrill(mm(0.3))
    net_settings.SetNetclass("Power", power)
    for net_name in sorted(set(power_nets)):
        net_settings.SetNetclassPatternAssignment(net_name, "Power")


def _bbox_mm(item) -> tuple[float, float, float, float]:
    bbox = item.GetBoundingBox()
    return (
        pcbnew.ToMM(bbox.GetX()),
        pcbnew.ToMM(bbox.GetY()),
        pcbnew.ToMM(bbox.GetRight()),
        pcbnew.ToMM(bbox.GetBottom()),
    )


def _boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    clearance: float = 0.0,
) -> bool:
    return not (
        first[2] + clearance <= second[0]
        or second[2] + clearance <= first[0]
        or first[3] + clearance <= second[1]
        or second[3] + clearance <= first[1]
    )


def _reposition_references_away_from_routing(
    board: pcbnew.BOARD, config: BoardConfig
) -> dict[str, tuple[float, float]]:
    """Place every reference near its footprint without touching copper or silk."""
    tracks = []
    for item in board.Tracks():
        if isinstance(item, pcbnew.PCB_VIA):
            position = item.GetPosition()
            tracks.append(
                (
                    "via",
                    (pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)),
                    pcbnew.ToMM(item.GetWidth(pcbnew.F_Cu)) / 2,
                )
            )
        elif item.GetLayer() == pcbnew.F_Cu:
            start, end = item.GetStart(), item.GetEnd()
            tracks.append(
                (
                    "track",
                    (pcbnew.ToMM(start.x), pcbnew.ToMM(start.y)),
                    (pcbnew.ToMM(end.x), pcbnew.ToMM(end.y)),
                    pcbnew.ToMM(item.GetWidth()) / 2,
                )
            )

    fixed_obstacles: list[tuple[float, float, float, float]] = []
    component_body_obstacles: list[tuple[float, float, float, float]] = []
    for drawing in board.Drawings():
        if drawing.GetLayer() == pcbnew.F_SilkS:
            fixed_obstacles.append(_bbox_mm(drawing))
    for footprint in board.GetFootprints():
        component_body_obstacles.append(footprint_component_box(footprint))
        for graphic in footprint.GraphicalItems():
            if graphic.GetLayer() == pcbnew.F_SilkS:
                fixed_obstacles.append(_bbox_mm(graphic))
        for pad in footprint.Pads():
            if pad.IsOnLayer(pcbnew.F_Cu):
                fixed_obstacles.append(_bbox_mm(pad))

    references = {
        footprint.GetReference(): footprint.Reference()
        for footprint in board.GetFootprints()
        if footprint.Reference().IsVisible()
        and footprint.Reference().GetLayer() == pcbnew.F_SilkS
    }
    body_boxes = {
        reference: footprint_body_box(board.FindFootprintByReference(reference))
        for reference in references
    }
    placed_reference_boxes: dict[str, tuple[float, float, float, float]] = {}
    x0, y0 = config.origin
    x1, y1 = x0 + config.size[0], y0 + config.size[1]
    moved: dict[str, tuple[float, float]] = {}
    fallback: dict[str, float] = {}
    exceptions: dict[str, float] = {}

    def routing_clear(box):
        for item in tracks:
            if item[0] == "via":
                if circle_hits_box(item[1], item[2], box):
                    return False
            elif segment_hits_box(item[1], item[2], box, item[3]):
                return False
        return True

    def field_area(reference: str) -> float:
        box = _bbox_mm(references[reference])
        return (box[2] - box[0]) * (box[3] - box[1])

    for reference in sorted(
        references,
        key=lambda ref: (
            ref not in config.reference_positions,
            -field_area(ref),
            ref,
        ),
    ):
        footprint = board.FindFootprintByReference(reference)
        field = references[reference]
        footprint_position = footprint.GetPosition()
        origin_xy = (
            pcbnew.ToMM(footprint_position.x),
            pcbnew.ToMM(footprint_position.y),
        )
        body_box = body_boxes[reference]
        preferred = config.reference_positions.get(reference, origin_xy)
        if point_box_distance(preferred, body_box) > 5.0:
            preferred = origin_xy
        local_x0 = max(x0 + 0.5, body_box[0] - 5.0)
        local_y0 = max(y0 + 0.5, body_box[1] - 5.0)
        local_x1 = min(x1 - 0.5, body_box[2] + 5.0)
        local_y1 = min(y1 - 0.5, body_box[3] + 5.0)
        # Dense 0402/0.5-mm-pitch areas frequently have a valid text slot
        # between routes that a 0.25 mm search grid skips.
        step = 0.1
        candidates = [
            (local_x0 + ix * step, local_y0 + iy * step)
            for ix in range(max(1, int((local_x1 - local_x0) / step) + 1))
            for iy in range(max(1, int((local_y1 - local_y0) / step) + 1))
        ]
        if preferred not in candidates:
            candidates.append(preferred)

        def inside_body(candidate: tuple[float, float]) -> bool:
            return (
                body_box[0] <= candidate[0] <= body_box[2]
                and body_box[1] <= candidate[1] <= body_box[3]
            )

        candidates.sort(
            key=lambda candidate: (
                (candidate[0] - preferred[0]) ** 2
                + (candidate[1] - preferred[1]) ** 2
                > 1e-9,
                inside_body(candidate),
                point_box_distance(candidate, body_box),
                (candidate[0] - preferred[0]) ** 2
                + (candidate[1] - preferred[1]) ** 2,
                (candidate[0] - origin_xy[0]) ** 2
                + (candidate[1] - origin_xy[1]) ** 2,
            ),
        )
        original_position = field.GetPosition()
        original_angle = field.GetTextAngleDegrees()
        candidate_angles = [original_angle]
        rotated_angle = (original_angle + 90.0) % 180.0
        if all(abs(rotated_angle - angle) > 1e-6 for angle in candidate_angles):
            candidate_angles.append(rotated_angle)
        selected = None
        selected_distance = 0.0

        def candidate_is_safe(
            candidate: tuple[float, float], angle: float, allow_body_overlap: bool = False
        ) -> bool:
            if inside_body(candidate):
                return False
            field.SetPosition(point(*candidate))
            field.SetTextAngleDegrees(angle)
            box = _bbox_mm(field)
            if (
                box[0] < x0 + 0.2
                or box[1] < y0 + 0.2
                or box[2] > x1 - 0.2
                or box[3] > y1 - 0.2
            ):
                return False
            if not routing_clear(box):
                return False
            if any(
                _boxes_overlap(box, obstacle, 0.15)
                for obstacle in fixed_obstacles
            ):
                return False
            if not allow_body_overlap and any(
                _boxes_overlap(box, obstacle, 0.15)
                for obstacle in component_body_obstacles
            ):
                return False
            if any(
                _boxes_overlap(box, obstacle, 0.15)
                for obstacle in placed_reference_boxes.values()
            ):
                return False
            return True

        for distance_limit in (3.0, 5.0):
            for candidate in candidates:
                distance = point_box_distance(candidate, body_box)
                if distance > distance_limit + 1e-6:
                    continue
                for angle in candidate_angles:
                    if not candidate_is_safe(candidate, angle):
                        continue
                    selected = candidate
                    selected_distance = distance
                    break
                if selected is not None:
                    break
            if selected is not None:
                break
        # Dense layouts can have no slot that clears every 3D body box even
        # though the text clears all actual pads, silk graphics, tracks, and
        # vias.  In that case allow the text box to project over a component
        # body boundary while keeping its center outside its own body.
        if selected is None:
            for candidate in candidates:
                distance = point_box_distance(candidate, body_box)
                if distance > 5.0 + 1e-6:
                    continue
                for angle in candidate_angles:
                    if not candidate_is_safe(candidate, angle, True):
                        continue
                    selected = candidate
                    selected_distance = distance
                    break
                if selected is not None:
                    break
        if selected is None:
            global_grid = [
                (x0 + 0.5 + ix * 0.25, y0 + 0.5 + iy * 0.25)
                for ix in range(max(1, int((config.size[0] - 1.0) / 0.25) + 1))
                for iy in range(max(1, int((config.size[1] - 1.0) / 0.25) + 1))
            ]
            global_grid.sort(
                key=lambda candidate: (
                    point_box_distance(candidate, body_box),
                    (candidate[0] - origin_xy[0]) ** 2
                    + (candidate[1] - origin_xy[1]) ** 2,
                )
            )
            for candidate in global_grid:
                for angle in candidate_angles:
                    if not candidate_is_safe(candidate, angle):
                        continue
                    selected = candidate
                    selected_distance = point_box_distance(candidate, body_box)
                    exceptions[reference] = selected_distance
                    break
                if selected is not None:
                    break
        if selected is not None:
            if field.GetPosition() != original_position:
                moved[reference] = selected
            if (
                selected_distance > 3.0 + 1e-6
                and reference not in exceptions
            ):
                fallback[reference] = selected_distance
            placed_reference_boxes[reference] = _bbox_mm(field)
        else:
            field.SetPosition(original_position)
            field.SetTextAngleDegrees(original_angle)
            distance = point_box_distance(
                (
                    pcbnew.ToMM(original_position.x),
                    pcbnew.ToMM(original_position.y),
                ),
                body_box,
            )
            exceptions[reference] = distance
            placed_reference_boxes[reference] = _bbox_mm(field)
    if fallback:
        details = ", ".join(
            f"{reference}={distance:.3f}mm"
            for reference, distance in sorted(fallback.items())
        )
        print(f"{config.name}: reference fallback within 5 mm: {details}")
    if exceptions:
        details = ", ".join(
            f"{reference}={distance:.3f}mm"
            for reference, distance in sorted(exceptions.items())
        )
        print(f"{config.name}: reference placement exceptions: {details}")
    return moved


def _add_track_polyline(
    board: pcbnew.BOARD,
    net: pcbnew.NETINFO_ITEM,
    layer_name: str,
    width: float,
    vertices: list[tuple[float, float]],
):
    layer = _layer_id(layer_name)
    for start, end in zip(vertices, vertices[1:]):
        track = pcbnew.PCB_TRACK(board)
        track.SetLayer(layer)
        track.SetNet(net)
        track.SetWidth(mm(width))
        track.SetStart(point(*start))
        track.SetEnd(point(*end))
        board.Add(track)


def _net_pad_map(module: ModuleType) -> tuple[dict[str, set[tuple[str, str]]], set[str]]:
    """Resolve symbol pin-name selectors into physical pin numbers."""
    schematic = module.build()
    resolved: dict[str, set[tuple[str, str]]] = {}
    power_nets: set[str] = set()
    for net_name, is_power, endpoints in module.NETS:
        if is_power:
            power_nets.add(net_name)
        bucket = resolved.setdefault(net_name, set())
        for reference, selector in endpoints:
            for pin in schematic._resolve_pins(reference, selector):
                bucket.add((reference, pin.number))
    return resolved, power_nets


def build_board(config: BoardConfig) -> pcbnew.BOARD:
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(config.copper_layers)
    _add_outline(board, config.origin, config.size)

    net_map, power_nets = _net_pad_map(config.module)
    _configure_rules(
        board, power_nets, config.clearance, config.copper_layers, config.power_track_width
    )

    nets: dict[str, pcbnew.NETINFO_ITEM] = {}
    for code, net_name in enumerate(sorted(net_map), start=1):
        net = pcbnew.NETINFO_ITEM(board, net_name, code)
        board.Add(net)
        nets[net_name] = net

    pad_to_net: dict[tuple[str, str], str] = {}
    for net_name, endpoints in net_map.items():
        for endpoint in endpoints:
            previous = pad_to_net.setdefault(endpoint, net_name)
            if previous != net_name:
                raise ValueError(f"{endpoint} belongs to both {previous} and {net_name}")

    components = {component["ref"]: component for component in config.module.COMPONENTS}
    missing = sorted(set(components) - set(config.placements))
    extra = sorted(set(config.placements) - set(components))
    if missing or extra:
        raise ValueError(f"placement mismatch: missing={missing}, extra={extra}")

    for reference, component in components.items():
        placement = config.placements[reference]
        footprint = load_footprint(component["fp"])
        footprint.SetReference(reference)
        footprint.SetValue(component["value"])
        # SetLayerAndFlip needs a board parent in KiCad 10's Python wrapper.
        board.Add(footprint)
        if placement.side.upper() == "B":
            footprint.SetLayerAndFlip(pcbnew.B_Cu)
        footprint.SetOrientationDegrees(placement.rotation)
        footprint.SetPosition(point(placement.x, placement.y))
        footprint.Value().SetVisible(False)
        footprint.Reference().SetTextSize(point(0.8, 0.8))
        footprint.Reference().SetTextThickness(mm(0.12))
        if reference in config.reference_positions:
            footprint.Reference().SetPosition(
                point(*config.reference_positions[reference])
            )
        if reference in config.silk_graphics_to_fab:
            for graphic in footprint.GraphicalItems():
                if graphic.GetLayer() == pcbnew.F_SilkS:
                    graphic.SetLayer(pcbnew.F_Fab)

        if component["fp"] == "RF_Module:ESP32-S3-WROOM-1":
            # The library antenna rule area extends 15 mm past both sides of
            # the module.  Keep its copper/track/via restrictions, but allow
            # footprints and pads in those lateral extensions.  No component
            # is placed beneath the physical antenna itself.
            for keepout in footprint.Zones():
                keepout.SetDoNotAllowFootprints(False)
                keepout.SetDoNotAllowPads(False)
                if config.antenna_keepout:
                    x0, y0, x1, y1 = config.antenna_keepout
                    outline = keepout.Outline()
                    while outline.OutlineCount():
                        outline.RemoveOutline(0)
                    outline.NewOutline()
                    for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
                        outline.Append(point(x, y))
            # KiCad's library courtyard follows the full 48 mm recommended
            # antenna keepout instead of the 18 x 25.5 mm component body,
            # which makes unrelated edge hardware look mechanically
            # overlapping.  Keep the geometry as a fabrication drawing while
            # the rule area continues to enforce the copper exclusion.
            for graphic in footprint.GraphicalItems():
                if graphic.GetLayer() == pcbnew.F_CrtYd:
                    graphic.SetLayer(pcbnew.Dwgs_User)

        physical_pad_numbers = {pad.GetNumber() for pad in footprint.Pads()}
        expected = {
            pin for ref, pin in pad_to_net if ref == reference
        }
        for pin in expected:
            physical = config.pad_aliases.get((reference, pin), pin)
            if physical not in physical_pad_numbers:
                raise ValueError(
                    f"{reference} schematic pin {pin} maps to absent footprint pad {physical}"
                )
        for pad in footprint.Pads():
            physical = pad.GetNumber()
            logical = next(
                (
                    logical_pin
                    for (ref, logical_pin), alias in config.pad_aliases.items()
                    if ref == reference and alias == physical
                ),
                physical,
            )
            net_name = pad_to_net.get((reference, logical))
            if net_name:
                pad.SetNet(nets[net_name])

    for index, (x, y) in enumerate(config.holes, start=1):
        hole = load_footprint("MountingHole:MountingHole_2.2mm_M2")
        hole.SetReference(f"H{index}")
        hole.SetValue("M2")
        hole.SetPosition(point(x, y))
        hole.Reference().SetVisible(False)
        hole.Value().SetVisible(False)
        board.Add(hole)

    for text, x, y, rotation in config.silk_text:
        _add_silk_text(board, text, x, y, rotation)
    if config.logo_rect:
        if config.logo_image:
            _add_silk_logo(
                board,
                config.logo_image,
                *config.logo_rect,
                config.logo_glyph_count,
                config.logo_min_gap,
            )
        else:
            _add_silk_rectangle(board, *config.logo_rect)
        _add_logo_rule_area(board, *(config.logo_rule_rect or config.logo_rect))

    board.BuildListOfNets()
    for net_name, layer, width, vertices in config.pre_routes:
        _add_track_polyline(board, nets[net_name], layer, width, vertices)
    for net_name, x, y in config.pre_vias:
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(point(x, y))
        via.SetWidth(mm(config.stitch_via[0]))
        via.SetDrill(mm(0.3))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNet(nets[net_name])
        board.Add(via)
    for item in board.GetTracks():
        item.SetLocked(True)  # 手配線は freerouting に動かさせない
    if config.auto_via_nets:
        import autovia

        x0, y0 = config.origin
        failed = autovia.place(
            board,
            config.auto_via_nets,
            [(n, layer, pts) for n, layer, pts, _ in config.power_zones],
            (x0, y0, x0 + config.size[0], y0 + config.size[1]),
            nets,
            config.pad_vias,
            config.pad_via_skip,
        )
        if failed:
            print(f"{config.name}: auto-via failed for {failed}")
    for layer_name, points in config.route_keepouts:
        _add_route_keepout(board, layer_name, points)
    board.SynchronizeNetsAndNetClasses(False)
    config.output.parent.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(config.output), board)
    if not pcbnew.ExportSpecctraDSN(board, str(config.dsn)):
        raise RuntimeError(f"failed to export DSN: {config.dsn}")
    if config.unrouted_nets:
        _strip_nets_from_dsn(config.dsn, config.unrouted_nets)
    if config.dsn_planes:
        _add_dsn_planes(config.dsn, config.dsn_planes)
    if config.copper_layers == 4:
        text = config.dsn.read_text(encoding="utf-8")
        text, n = re.subn(r"(\(layer In[12]\.Cu\s*\(type )signal", r"\1power", text)
        if n != 2:
            raise ValueError(f"expected 2 inner layers in DSN, patched {n}")
        config.dsn.write_text(text, encoding="utf-8")
    return board


def _remove_existing_zones(board: pcbnew.BOARD):
    for zone in list(board.Zones()):
        if not zone.GetIsRuleArea() or zone.GetZoneName() == ROUTE_KEEPOUT_NAME:
            board.Remove(zone)


def _remove_serialized_routes(
    path: Path,
    removals: list[tuple[str, str, tuple[float, float], tuple[float, float]]],
):
    """Remove exact generated segments after saving, avoiding pcbnew SWIG deletion bugs."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"\n\t\(segment\n(?:\t\t.*\n)+?\t\)")

    def keep_or_drop(match: re.Match[str]) -> str:
        block = match.group(0)
        start_match = re.search(r"\(start ([-\d.]+) ([-\d.]+)\)", block)
        end_match = re.search(r"\(end ([-\d.]+) ([-\d.]+)\)", block)
        layer_match = re.search(r'\(layer "([^"]+)"\)', block)
        net_match = re.search(r'\(net "?([^")]+)"?\)', block)
        if not all((start_match, end_match, layer_match, net_match)):
            return block
        actual = {
            tuple(round(float(value), 4) for value in start_match.groups()),
            tuple(round(float(value), 4) for value in end_match.groups()),
        }
        for net_name, layer, start, end in removals:
            if (
                net_match.group(1) == net_name
                and layer_match.group(1) == layer
                and actual == {start, end}
            ):
                return ""
        return block

    path.write_text(pattern.sub(keep_or_drop, text), encoding="utf-8")


def _remove_serialized_net_routes(path: Path, net_names: set[str]):
    """Remove every imported segment/via for selected nets before replacing them."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"\n\t\((?:segment|via)\n(?:\t\t.*\n)+?\t\)")

    def keep_or_drop(match: re.Match[str]) -> str:
        block = match.group(0)
        net_match = re.search(r'\(net "?([^")]+)"?\)', block)
        if net_match and net_match.group(1) in net_names:
            return ""
        return block

    path.write_text(pattern.sub(keep_or_drop, text), encoding="utf-8")


def _add_ground_zone(
    board: pcbnew.BOARD,
    gnd: pcbnew.NETINFO_ITEM,
    layer: int,
    origin: tuple[float, float],
    size: tuple[float, float],
    clearance: float,
):
    inset = 0.25
    x0, y0 = origin[0] + inset, origin[1] + inset
    x1, y1 = origin[0] + size[0] - inset, origin[1] + size[1] - inset
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(gnd)
    zone.SetLocalClearance(mm(clearance))
    zone.SetMinThickness(mm(0.2))
    zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    zone.SetThermalReliefGap(mm(0.25))
    zone.SetThermalReliefSpokeWidth(mm(0.3))
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        outline.Append(point(x, y))
    board.Add(zone)


def _add_rect_copper_zone(
    board: pcbnew.BOARD,
    net: pcbnew.NETINFO_ITEM,
    layer_name: str,
    rect: tuple[float, float, float, float],
    clearance: float,
):
    """Add a priority local copper area, used for regulator heat spreading."""
    layer = _layer_id(layer_name)
    x0, y0, x1, y1 = rect
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(net)
    zone.SetAssignedPriority(1)
    zone.SetLocalClearance(mm(clearance))
    zone.SetMinThickness(mm(0.2))
    zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    zone.SetThermalReliefGap(mm(0.25))
    zone.SetThermalReliefSpokeWidth(mm(0.3))
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        outline.Append(point(x, y))
    board.Add(zone)


def _add_zone_fill_keepout(
    board: pcbnew.BOARD,
    layer_name: str,
    rect: tuple[float, float, float, float],
):
    """Prevent poured copper in a local area without blocking pads/tracks/vias."""
    layer = _layer_id(layer_name)
    x0, y0, x1, y1 = rect
    area = pcbnew.ZONE(board)
    area.SetIsRuleArea(True)
    area.SetLayer(layer)
    area.SetDoNotAllowFootprints(False)
    area.SetDoNotAllowPads(False)
    area.SetDoNotAllowTracks(False)
    area.SetDoNotAllowVias(False)
    area.SetDoNotAllowZoneFills(True)
    outline = area.Outline()
    outline.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        outline.Append(point(x, y))
    board.Add(area)


ROUTE_KEEPOUT_NAME = "ROUTE_KEEPOUT"


def _layer_id(layer_name: str) -> int:
    return {"F": pcbnew.F_Cu, "B": pcbnew.B_Cu, "IN1": pcbnew.In1_Cu, "IN2": pcbnew.In2_Cu}[layer_name.upper()]


def _add_route_keepout(board: pcbnew.BOARD, layer_name: str, points):
    area = pcbnew.ZONE(board)
    area.SetIsRuleArea(True)
    area.SetZoneName(ROUTE_KEEPOUT_NAME)
    area.SetLayer(_layer_id(layer_name))
    area.SetDoNotAllowFootprints(False)
    area.SetDoNotAllowPads(False)
    area.SetDoNotAllowTracks(True)
    area.SetDoNotAllowVias(True)
    area.SetDoNotAllowZoneFills(False)
    outline = area.Outline()
    outline.NewOutline()
    for x, y in points:
        outline.Append(point(x, y))
    board.Add(area)


def _add_power_zone(board, net, layer_name, points, priority, clearance):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(_layer_id(layer_name))
    zone.SetNet(net)
    zone.SetAssignedPriority(priority)
    zone.SetLocalClearance(mm(clearance))
    zone.SetMinThickness(mm(0.2))
    zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in points:
        outline.Append(point(x, y))
    board.Add(zone)


def _strip_nets_from_dsn(dsn: Path, nets: set[str]):
    """指定ネットを自動配線の対象外にする。

    ネット自体を消すと、手配置した同ネットのビア・配線を freerouting が捨ててしまい
    障害物として扱われなくなる。そこでネットは残し、ピン列を先頭 1 本だけにする
    (繋ぐ相手がいないので配線されない)。残りのピンは無所属パッドの障害物になる。
    """
    text = dsn.read_text(encoding="utf-8")
    for name in nets:
        pattern = re.compile(
            r"(\(net " + re.escape(name) + r"\s*\(pins\s+)(\S+)[^)]*(\))"
        )
        text, count = pattern.subn(lambda m: m.group(1) + m.group(2) + m.group(3), text)
        if count != 1:
            raise ValueError(f"DSN net {name!r}: expected 1 entry, patched {count}")
    dsn.write_text(text, encoding="utf-8")


def _add_dsn_planes(dsn: Path, planes):
    """structure 節に (plane ...) を足す。KiCad の DSN は um 単位で y 軸が反転している。"""
    text = dsn.read_text(encoding="utf-8")
    lines = []
    for net, layer_name, points in planes:
        layer = {"F": "F.Cu", "B": "B.Cu", "IN1": "In1.Cu", "IN2": "In2.Cu"}[layer_name.upper()]
        coords = " ".join(f"{round(x * 1000)} {round(-y * 1000)}" for x, y in points + points[:1])
        lines.append(f"    (plane {net} (polygon {layer} 0 {coords}))")
    marker = "    (via "
    if marker not in text:
        raise ValueError("DSN structure via marker not found")
    text = text.replace(marker, "\n".join(lines) + "\n" + marker, 1)
    dsn.write_text(text, encoding="utf-8")


def _enlarge_undersized_vias(config: BoardConfig) -> None:
    """Bring stray autorouter vias up to the board's minimum diameter.

    Freerouting sometimes emits a via from a padstack narrower than our own
    0.6 mm rule (JLCPCB itself can make 0.5/0.3, so it is a rule mismatch, not
    a manufacturing fault).  This runs on the serialized board rather than
    through pcbnew: in KiCad 10 a via carries a per-layer padstack, and calling
    PCB_VIA::GetWidth/SetWidth without a layer trips a wxWidgets assert that
    opens a modal dialog and hangs a headless run.  Only the annular ring
    grows; the drill is left alone.
    """
    text = config.output.read_text(encoding="utf-8")
    minimum = VIA_MIN_DIAMETER_MM
    enlarged = 0

    def fix(match: re.Match[str]) -> str:
        nonlocal enlarged
        size = float(match.group("size"))
        if size >= minimum:
            return match.group(0)
        enlarged += 1
        return match.group(0).replace(
            f"(size {match.group('size')})", f"(size {minimum})", 1
        )

    pattern = re.compile(
        r"\(via\b(?:[^()]|\((?:[^()]|\([^()]*\))*\))*?"
        r"\(size (?P<size>[0-9.]+)\)",
        re.DOTALL,
    )
    patched = pattern.sub(fix, text)
    if enlarged:
        config.output.write_text(patched, encoding="utf-8")
        print(f"{config.name}: enlarged {enlarged} via(s) to {minimum} mm")


def import_and_finish(config: BoardConfig, ses_path: Path) -> pcbnew.BOARD:
    board = pcbnew.LoadBoard(str(config.output))
    if board is None:
        raise FileNotFoundError(config.output)
    if not pcbnew.ImportSpecctraSES(board, str(ses_path)):
        raise RuntimeError(f"failed to import SES: {ses_path}")
    # A SES file carries the board text positions from the DSN that created
    # it.  Re-apply the current configuration so label-only layout fixes do
    # not require another autorouter pass.
    configured_silk = {
        text: (x, y, rotation) for text, x, y, rotation in config.silk_text
    }
    for drawing in board.GetDrawings():
        if not isinstance(drawing, pcbnew.PCB_TEXT):
            continue
        values = configured_silk.get(drawing.GetText())
        if values is None:
            continue
        x, y, rotation = values
        drawing.SetPosition(point(x, y))
        drawing.SetTextAngleDegrees(rotation)
    for reference in config.placement_overrides_after_import:
        footprint = board.FindFootprintByReference(reference)
        if footprint is None:
            raise ValueError(f"footprint not found after SES import: {reference}")
        placement = config.placements[reference]
        if placement.side.upper() == "B":
            footprint.SetLayerAndFlip(pcbnew.B_Cu)
        else:
            footprint.SetLayerAndFlip(pcbnew.F_Cu)
        footprint.SetOrientationDegrees(placement.rotation)
        footprint.SetPosition(point(placement.x, placement.y))
    if config.replacement_routes or config.replacement_vias:
        replacement_nets = {
            net_name for net_name, *_ in config.replacement_routes
        } | {net_name for net_name, *_ in config.replacement_vias}
        # Removing imported tracks through pcbnew's SWIG wrapper is unstable.
        # Serialize once, remove the selected net blocks as text, then reload.
        pcbnew.SaveBoard(str(config.output), board)
        _remove_serialized_net_routes(config.output, replacement_nets)
        board = pcbnew.LoadBoard(str(config.output))
        if board is None:
            raise RuntimeError("failed to reload board after route replacement")
        for net_name, layer, width, vertices in config.replacement_routes:
            net = board.FindNet(net_name)
            if net is None:
                raise ValueError(f"net not found for replacement route: {net_name}")
            _add_track_polyline(board, net, layer, width, vertices)
        for net_name, x, y in config.replacement_vias:
            net = board.FindNet(net_name)
            if net is None:
                raise ValueError(f"net not found for replacement via: {net_name}")
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(point(x, y))
            via.SetWidth(mm(0.6))
            via.SetDrill(mm(0.3))
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetNet(net)
            board.Add(via)
    for net_name, layer, width, vertices in config.post_routes:
        net = board.FindNet(net_name)
        if net is None:
            raise ValueError(f"net not found for post-route: {net_name}")
        _add_track_polyline(board, net, layer, width, vertices)
    for net_name, x, y in config.post_vias:
        net = board.FindNet(net_name)
        if net is None:
            raise ValueError(f"net not found for post-via: {net_name}")
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(point(x, y))
        via.SetWidth(mm(config.stitch_via[0]))
        via.SetDrill(mm(config.stitch_via[1]))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNet(net)
        board.Add(via)
    if config.avoid_reference_routing:
        moved = _reposition_references_away_from_routing(board, config)
        if moved:
            print(
                f"{config.name}: placed {len(moved)} references near their footprints"
            )
    if config.route_removals:
        pcbnew.SaveBoard(str(config.output), board)
        serialized_removals = [
            (
                net_name,
                "F.Cu" if layer == "F" else "B.Cu",
                start,
                end,
            )
            for net_name, layer, start, end in config.route_removals
        ]
        _remove_serialized_routes(config.output, serialized_removals)
        board = pcbnew.LoadBoard(str(config.output))
        if board is None:
            raise RuntimeError("failed to reload board after exact route removal")
    _remove_existing_zones(board)
    # KiCad 10's SWIG wrapper can retain a stale SHAPE_POLY_SET after removing
    # imported copper zones.  Serialize and reload before creating replacements.
    pcbnew.SaveBoard(str(config.output), board)
    board = pcbnew.LoadBoard(str(config.output))
    if board is None:
        raise RuntimeError("failed to reload board after zone removal")
    for reference, pad_number in config.zone_disconnected_pads:
        footprint = board.FindFootprintByReference(reference)
        if footprint is None:
            raise ValueError(f"zone-disconnected footprint not found: {reference}")
        pad = footprint.FindPadByNumber(pad_number)
        if pad is None:
            raise ValueError(f"zone-disconnected pad not found: {reference}.{pad_number}")
        pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_NONE)
    gnd = board.FindNet("GND")
    if gnd is None:
        raise ValueError("GND net not found")
    _add_ground_zone(
        board, gnd, pcbnew.F_Cu, config.origin, config.size, config.clearance
    )
    _add_ground_zone(
        board, gnd, pcbnew.B_Cu, config.origin, config.size, config.clearance
    )
    if config.copper_layers == 4:
        for inner in (pcbnew.In1_Cu, pcbnew.In2_Cu):
            _add_ground_zone(board, gnd, inner, config.origin, config.size, config.clearance)
    for net_name, layer_name, rect in config.copper_zones:
        net = board.FindNet(net_name)
        if net is None:
            raise ValueError(f"copper-zone net not found: {net_name}")
        _add_rect_copper_zone(
            board, net, layer_name, rect, config.clearance
        )
    for net_name, layer_name, points, priority in config.power_zones:
        net = board.FindNet(net_name)
        if net is None:
            raise ValueError(f"power-zone net not found: {net_name}")
        _add_power_zone(board, net, layer_name, points, priority, config.clearance)
    for layer_name, rect in config.zone_keepouts:
        _add_zone_fill_keepout(board, layer_name, rect)
    filler = pcbnew.ZONE_FILLER(board)
    if not filler.Fill(board.Zones()):
        raise RuntimeError("zone fill failed")
    pcbnew.SaveBoard(str(config.output), board)
    _enlarge_undersized_vias(config)
    return board
