import json
import math
import xml.etree.ElementTree as ElementTree
from pathlib import Path

GID_FLIP_HORIZONTAL = 0x80000000
GID_FLIP_VERTICAL = 0x40000000
GID_FLAGS = 0xF0000000
GID_MAX = 0xFFFFFFFF


def is_whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require_list(where: str, container: dict, key: str) -> list:
    value = container.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{where}: {key} must be a list")
    return value


def require_positive(where: str, container: dict, key: str) -> int:
    value = container.get(key)
    if not is_whole(value) or value <= 0:
        raise ValueError(f"{where}: {key} must be a whole number above 0")
    return value


def parse_tsx(tsx_path: Path) -> dict:
    try:
        root = ElementTree.parse(tsx_path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise ValueError(f"{tsx_path.name}: not a readable tileset ({error})") from error

    image = root.find("image")
    if image is None or "source" not in image.attrib:
        raise ValueError(
            f"{tsx_path.name}: no image; use a tileset made from one image, "
            "not a collection of images"
        )

    try:
        tile_width = int(root.attrib["tilewidth"])
        tile_height = int(root.attrib["tileheight"])
        tile_count = int(root.attrib["tilecount"])
        columns = int(root.attrib["columns"])
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"{tsx_path.name}: missing or invalid tilewidth, tileheight, tilecount "
            f"or columns ({error})"
        ) from error

    for gap in ("spacing", "margin"):
        if root.attrib.get(gap, "0") != "0":
            raise ValueError(
                f"{tsx_path.name}: {gap} {root.attrib[gap]} is not supported; "
                "tiles must sit edge to edge in the image"
            )

    return {
        "image_path": (tsx_path.parent / image.attrib["source"]).resolve(),
        "tile_width": tile_width,
        "tile_height": tile_height,
        "tile_count": tile_count,
        "columns": columns,
    }


def read_map(tmj_path: Path) -> dict:
    try:
        data = json.loads(tmj_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{tmj_path.name}: not a readable Tiled JSON map ({error})") from error
    if not isinstance(data, dict):
        raise ValueError(f"{tmj_path.name}: not a Tiled map")
    return data


def map_size(tmj_path: Path, tmj_data: dict) -> tuple[int, int]:
    return (
        require_positive(tmj_path.name, tmj_data, "width"),
        require_positive(tmj_path.name, tmj_data, "height"),
    )


def map_tileset(tmj_path: Path, tmj_data: dict) -> tuple[int, Path]:
    tilesets = require_list(tmj_path.name, tmj_data, "tilesets")
    if len(tilesets) != 1:
        raise ValueError(
            f"{tmj_path.name}: uses {len(tilesets)} tilesets; a map draws from exactly one"
        )
    tileset = tilesets[0]
    if not isinstance(tileset, dict):
        raise ValueError(f"{tmj_path.name}: the tileset entry is not a Tiled tileset")
    if "source" not in tileset:
        raise ValueError(
            f"{tmj_path.name}: the tileset is embedded in the map; "
            "save it as its own .tsx file with Export Tileset in Tiled"
        )
    if not isinstance(tileset["source"], str):
        raise ValueError(f"{tmj_path.name}: the tileset source must be a file name")
    first_gid = require_positive(f"{tmj_path.name} tileset", tileset, "firstgid")
    return first_gid, (tmj_path.parent / tileset["source"]).resolve()


def map_layers(tmj_path: Path, tmj_data: dict) -> list[dict]:
    layers = require_list(tmj_path.name, tmj_data, "layers")
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("name"), str):
            raise ValueError(f"{tmj_path.name}: a layer has no name")
        if layer.get("type") == "group":
            raise ValueError(
                f"{tmj_path.name}: layer group {layer['name']!r} is not supported; "
                "keep every layer at the top level"
            )
    return layers


def check_no_offset(tmj_path: Path, layer: dict) -> None:
    if layer.get("offsetx", 0) != 0 or layer.get("offsety", 0) != 0:
        raise ValueError(
            f"{tmj_path.name}: layer {layer['name']!r} has an offset; "
            "set its Offset to 0, 0 in the layer properties"
        )


def tile_layers(tmj_path: Path, tmj_data: dict) -> list[dict]:
    layers = []
    for layer in map_layers(tmj_path, tmj_data):
        if layer.get("type") != "tilelayer":
            continue
        where = f"{tmj_path.name}: layer {layer['name']!r}"
        check_no_offset(tmj_path, layer)
        if layer.get("encoding", "csv") != "csv" or layer.get("compression"):
            raise ValueError(f"{where} is compressed; set Tile Layer Format to CSV")
        cells = require_list(where, layer, "data")
        if not all(is_whole(gid) and 0 <= gid <= GID_MAX for gid in cells):
            raise ValueError(f"{where} has a cell that is not a tile number")
        layers.append(layer)
    return layers


def point_objects(tmj_path: Path, tmj_data: dict) -> list[tuple[str, int, int]]:
    points = []
    for layer in map_layers(tmj_path, tmj_data):
        if layer.get("type") != "objectgroup":
            continue
        where = f"{tmj_path.name}: layer {layer['name']!r}"
        check_no_offset(tmj_path, layer)
        for tiled_object in require_list(where, layer, "objects"):
            if not isinstance(tiled_object, dict):
                raise ValueError(f"{where} holds an object that is not a Tiled object")
            name = tiled_object.get("name", "")
            if not isinstance(name, str):
                raise ValueError(f"{where} holds an object whose name is not text")
            if not name:
                continue
            if not tiled_object.get("point"):
                raise ValueError(
                    f"{tmj_path.name}: object {name!r} is not a point; "
                    "change it to Point in Tiled, or clear its name"
                )
            point_x = tiled_object.get("x")
            point_y = tiled_object.get("y")
            if not (is_number(point_x) and is_number(point_y)):
                raise ValueError(f"{tmj_path.name}: point {name!r} has no position")
            points.append((name, round(point_x), round(point_y)))
    return points
