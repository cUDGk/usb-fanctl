"""Validate F.SilkS reference routing clearance and footprint proximity."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pcbnew


def to_mm(value: int) -> float:
    return pcbnew.ToMM(value)


def segment_hits_box(
    start: tuple[float, float],
    end: tuple[float, float],
    box: tuple[float, float, float, float],
    radius: float,
) -> bool:
    """Liang-Barsky test against the text box expanded by track radius."""
    xmin, ymin, xmax, ymax = box
    xmin -= radius
    ymin -= radius
    xmax += radius
    ymax += radius
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    lower, upper = 0.0, 1.0
    for p, q in (
        (-dx, x1 - xmin),
        (dx, xmax - x1),
        (-dy, y1 - ymin),
        (dy, ymax - y1),
    ):
        if p == 0:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return True


def circle_hits_box(
    center: tuple[float, float],
    radius: float,
    box: tuple[float, float, float, float],
) -> bool:
    xmin, ymin, xmax, ymax = box
    x, y = center
    nearest_x = min(max(x, xmin), xmax)
    nearest_y = min(max(y, ymin), ymax)
    return (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= radius**2


def item_box(item) -> tuple[float, float, float, float]:
    bbox = item.GetBoundingBox()
    return (
        to_mm(bbox.GetX()),
        to_mm(bbox.GetY()),
        to_mm(bbox.GetRight()),
        to_mm(bbox.GetBottom()),
    )


def footprint_body_box(
    footprint: pcbnew.FOOTPRINT,
) -> tuple[float, float, float, float]:
    """Return a physical-body box that excludes reference/value fields."""
    boxes = [item_box(pad) for pad in footprint.Pads()]
    physical_layers = {
        pcbnew.F_SilkS,
        pcbnew.F_Fab,
        pcbnew.F_CrtYd,
        pcbnew.B_SilkS,
        pcbnew.B_Fab,
        pcbnew.B_CrtYd,
    }
    for graphic in footprint.GraphicalItems():
        if graphic.GetLayer() in physical_layers:
            boxes.append(item_box(graphic))
    if not boxes:
        position = footprint.GetPosition()
        x, y = to_mm(position.x), to_mm(position.y)
        return (x, y, x, y)
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def footprint_component_box(
    footprint: pcbnew.FOOTPRINT,
) -> tuple[float, float, float, float]:
    """Return the assembled component body, preferring fabrication outlines."""
    boxes = [
        item_box(graphic)
        for graphic in footprint.GraphicalItems()
        if graphic.GetLayer() in {pcbnew.F_Fab, pcbnew.B_Fab}
        and isinstance(graphic, pcbnew.PCB_SHAPE)
    ]
    if not boxes:
        boxes = [
            item_box(graphic)
            for graphic in footprint.GraphicalItems()
            if graphic.GetLayer() in {pcbnew.F_SilkS, pcbnew.B_SilkS}
            and isinstance(graphic, pcbnew.PCB_SHAPE)
        ]
    if not boxes:
        boxes = [item_box(pad) for pad in footprint.Pads()]
    if not boxes:
        position = footprint.GetPosition()
        x, y = to_mm(position.x), to_mm(position.y)
        return (x, y, x, y)
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def point_box_distance(
    point: tuple[float, float], box: tuple[float, float, float, float]
) -> float:
    x, y = point
    dx = max(box[0] - x, 0.0, x - box[2])
    dy = max(box[1] - y, 0.0, y - box[3])
    return math.hypot(dx, dy)


def reference_distances(
    board: pcbnew.BOARD,
) -> list[tuple[str, float, tuple[float, float]]]:
    distances = []
    for footprint in board.GetFootprints():
        reference = footprint.Reference()
        if not reference.IsVisible() or reference.GetLayer() != pcbnew.F_SilkS:
            continue
        position = reference.GetPosition()
        center = (to_mm(position.x), to_mm(position.y))
        distances.append(
            (
                footprint.GetReference(),
                point_box_distance(center, footprint_body_box(footprint)),
                center,
            )
        )
    return distances


def find_intersections(board: pcbnew.BOARD) -> list[tuple[str, str]]:
    routing = []
    for item in board.Tracks():
        if isinstance(item, pcbnew.PCB_VIA):
            position = item.GetPosition()
            routing.append(
                (
                    "via",
                    (to_mm(position.x), to_mm(position.y)),
                    to_mm(item.GetWidth(pcbnew.F_Cu)) / 2,
                    item.GetNetname(),
                )
            )
        elif item.GetLayer() == pcbnew.F_Cu:
            start, end = item.GetStart(), item.GetEnd()
            routing.append(
                (
                    "track",
                    (to_mm(start.x), to_mm(start.y)),
                    (to_mm(end.x), to_mm(end.y)),
                    to_mm(item.GetWidth()) / 2,
                    item.GetNetname(),
                )
            )

    hits: list[tuple[str, str]] = []
    for footprint in board.GetFootprints():
        reference = footprint.Reference()
        if not reference.IsVisible() or reference.GetLayer() != pcbnew.F_SilkS:
            continue
        bbox = reference.GetBoundingBox()
        box = (
            to_mm(bbox.GetX()),
            to_mm(bbox.GetY()),
            to_mm(bbox.GetRight()),
            to_mm(bbox.GetBottom()),
        )
        for item in routing:
            if item[0] == "via":
                _, center, radius, net = item
                crossed = circle_hits_box(center, radius, box)
                description = f"via:{net}@{center[0]:.3f},{center[1]:.3f}"
            else:
                _, start, end, radius, net = item
                crossed = segment_hits_box(start, end, box, radius)
                description = (
                    f"track:{net}@{start[0]:.3f},{start[1]:.3f}"
                    f"->{end[0]:.3f},{end[1]:.3f}"
                )
            if crossed:
                hits.append((footprint.GetReference(), description))
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("boards", nargs="+", type=Path)
    parser.add_argument("--preferred-distance", type=float, default=3.0)
    parser.add_argument("--maximum-distance", type=float, default=5.0)
    args = parser.parse_args()
    exit_code = 0
    for path in args.boards:
        board = pcbnew.LoadBoard(str(path))
        if board is None:
            raise FileNotFoundError(path)
        hits = find_intersections(board)
        references = sorted({reference for reference, _ in hits})
        distances = reference_distances(board)
        fallback = sorted(
            (reference, distance, center)
            for reference, distance, center in distances
            if distance > args.preferred_distance + 1e-6
            and distance <= args.maximum_distance + 1e-6
        )
        exceptions = sorted(
            (reference, distance, center)
            for reference, distance, center in distances
            if distance > args.maximum_distance + 1e-6
        )
        maximum = max((distance for _, distance, _ in distances), default=0.0)
        print(
            f"{path}: intersections={len(hits)} "
            f"references={len(references)} {references}; "
            f"max_distance={maximum:.3f} mm "
            f"fallbacks={len(fallback)} exceptions={len(exceptions)}"
        )
        for reference, description in hits:
            print(f"  {reference}: {description}")
        for reference, distance, center in fallback:
            print(
                f"  fallback {reference}: {distance:.3f} mm "
                f"at {center[0]:.3f},{center[1]:.3f}"
            )
        for reference, distance, center in exceptions:
            print(
                f"  exception {reference}: {distance:.3f} mm "
                f"at {center[0]:.3f},{center[1]:.3f}"
            )
        if hits or exceptions:
            exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
