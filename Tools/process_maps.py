import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from codegen import Symbols, c_array_rows, enum_name
from tiled import (
    GID_FLAGS,
    GID_FLIP_HORIZONTAL,
    GID_FLIP_VERTICAL,
    map_size,
    map_tileset,
    parse_tsx,
    point_objects,
    read_map,
    tile_layers,
)

TILE_SIZE = 16
CELL_TILE_MASK = 0x3FFF
CELL_FLIP_X = 0x4000
CELL_FLIP_Y = 0x8000
SIZE_MAX = 0xFFFF
LAYER_COUNT_MAX = 0xFF
IMAGE_EXTENSIONS = (".png", ".gif")
COUNT_NAME = "MAP_COUNT"
RESERVED_NAMES = {
    COUNT_NAME: "the map count",
    "MAP_CELL_TILE_MASK": "the cell tile mask",
    "MAP_CELL_FLIP_X": "the cell flip bit",
    "MAP_CELL_FLIP_Y": "the cell flip bit",
}


@dataclass
class TiledMap:
    path: Path
    enum: str
    width: int
    height: int
    tileset: str
    layers: list
    points: list


def cell_value(where: str, gid: int, first_gid: int, tile_count: int) -> int:
    if gid == 0:
        return 0
    if gid & GID_FLAGS & ~(GID_FLIP_HORIZONTAL | GID_FLIP_VERTICAL):
        raise ValueError(f"{where} is rotated; the Neo Geo flips tiles but cannot rotate them")
    tile = (gid & ~GID_FLAGS) - first_gid
    if not 0 <= tile < tile_count:
        raise ValueError(f"{where} uses tile {tile}, outside the {tile_count} tiles of the tileset")
    value = tile + 1
    if gid & GID_FLIP_HORIZONTAL:
        value |= CELL_FLIP_X
    if gid & GID_FLIP_VERTICAL:
        value |= CELL_FLIP_Y
    return value


def column_major_cells(
    tmj_path: Path, layer: dict, width: int, height: int, first_gid: int, tile_count: int
) -> list:
    gids = layer["data"]
    if len(gids) != width * height:
        raise ValueError(
            f"{tmj_path.name}: layer {layer['name']!r} holds {len(gids)} cells, "
            f"not {width}x{height}"
        )
    cells = []
    for column in range(width):
        for row in range(height):
            where = f"{tmj_path.name}: layer {layer['name']!r} cell ({column}, {row})"
            cells.append(cell_value(where, gids[(row * width) + column], first_gid, tile_count))
    return cells


def check_tileset(tsx_path: Path, tileset: dict, images_dir: Path) -> str:
    if (tileset["tile_width"], tileset["tile_height"]) != (TILE_SIZE, TILE_SIZE):
        raise ValueError(f"{tsx_path.name}: tiles must be {TILE_SIZE}x{TILE_SIZE}")

    image_path = tileset["image_path"]
    if (
        image_path.parent != images_dir.resolve()
        or image_path.suffix.lower() not in IMAGE_EXTENSIONS
    ):
        raise ValueError(
            f"{tsx_path.name}: image {image_path} is not a .png or .gif "
            f"in the graphics folder {images_dir}"
        )
    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError(
            f"{tsx_path.name}: image {image_path.name} is not readable ({error})"
        ) from error

    across = width // TILE_SIZE
    count = across * (height // TILE_SIZE)
    if (tileset["columns"], tileset["tile_count"]) != (across, count):
        raise ValueError(
            f"{tsx_path.name}: says {tileset['columns']} columns and {tileset['tile_count']} "
            f"tiles, but {image_path.name} is {width}x{height}, which is {across} columns and "
            f"{count} tiles; open the tileset in Tiled and save it again"
        )
    if count > CELL_TILE_MASK:
        raise ValueError(
            f"{tsx_path.name}: {count} tiles; a map cell holds tile numbers up to {CELL_TILE_MASK}"
        )
    return enum_name("GFX", image_path.stem)


def read_tiled_map(tmj_path: Path, images_dir: Path, symbols: Symbols) -> TiledMap:
    data = read_map(tmj_path)
    if data.get("orientation") != "orthogonal":
        raise ValueError(f"{tmj_path.name}: orientation must be orthogonal")
    if data.get("infinite"):
        raise ValueError(f"{tmj_path.name}: turn off Infinite in the map properties")
    if (data.get("tilewidth"), data.get("tileheight")) != (TILE_SIZE, TILE_SIZE):
        raise ValueError(f"{tmj_path.name}: map tiles must be {TILE_SIZE}x{TILE_SIZE}")
    width, height = map_size(tmj_path, data)
    if width > SIZE_MAX or height > SIZE_MAX:
        raise ValueError(f"{tmj_path.name}: {width}x{height} tiles does not fit uint16_t")

    first_gid, tsx_path = map_tileset(tmj_path, data)
    tileset = parse_tsx(tsx_path)
    tileset_enum = check_tileset(tsx_path, tileset, images_dir)
    tile_count = tileset["tile_count"]
    map_enum = enum_name("MAP", tmj_path.stem)

    layers = []
    for layer in tile_layers(tmj_path, data):
        macro = symbols.add(
            enum_name(f"{map_enum}_LAYER", layer["name"]),
            f"{tmj_path.name} layer {layer['name']!r}",
        )
        layers.append(
            (macro, column_major_cells(tmj_path, layer, width, height, first_gid, tile_count))
        )
    if not layers:
        raise ValueError(f"{tmj_path.name}: no tile layer")
    if len(layers) > LAYER_COUNT_MAX:
        raise ValueError(f"{tmj_path.name}: {len(layers)} layers does not fit uint8_t")

    points = []
    for name, point_x, point_y in point_objects(tmj_path, data):
        if not (0 <= point_x <= width * TILE_SIZE and 0 <= point_y <= height * TILE_SIZE):
            raise ValueError(
                f"{tmj_path.name}: point {name!r} at ({point_x}, {point_y}) is outside the map"
            )
        owner = f"{tmj_path.name} point {name!r}"
        base = enum_name(map_enum, name)
        points.append(
            (symbols.add(f"{base}_X", owner), symbols.add(f"{base}_Y", owner), point_x, point_y)
        )

    return TiledMap(tmj_path, map_enum, width, height, tileset_enum, layers, points)


def header_text(tiled_maps: list) -> str:
    lines = [
        "#ifndef MAPS_H",
        "#define MAPS_H",
        "",
        "#include <stdint.h>",
        "",
        '#include "Graphics.h"',
        "",
        f"#define MAP_CELL_TILE_MASK 0x{CELL_TILE_MASK:04X}",
        f"#define MAP_CELL_FLIP_X 0x{CELL_FLIP_X:04X}",
        f"#define MAP_CELL_FLIP_Y 0x{CELL_FLIP_Y:04X}",
        "",
        "typedef struct {",
        "    uint16_t widthInTiles;",
        "    uint16_t heightInTiles;",
        "    GraphicId tileset;",
        "    uint8_t layerCount;",
        "    const uint16_t *const *layers;",
        "} Map;",
        "",
        "typedef enum {",
        *(f"    {tiled_map.enum}," for tiled_map in tiled_maps),
        f"    {COUNT_NAME}",
        "} MapId;",
        "",
    ]
    for tiled_map in tiled_maps:
        for index, (macro, _cells) in enumerate(tiled_map.layers):
            lines.append(f"#define {macro} {index}")
        for macro_x, macro_y, point_x, point_y in tiled_map.points:
            lines.append(f"#define {macro_x} {point_x}")
            lines.append(f"#define {macro_y} {point_y}")
        lines.append("")
    lines.extend([f"extern const Map maps[{COUNT_NAME}];", "", "#endif", ""])
    return "\n".join(lines)


def source_text(tiled_maps: list) -> str:
    lines = ['#include "Maps.h"', ""]
    for map_index, tiled_map in enumerate(tiled_maps):
        layer_names = []
        for layer_index, (_macro, cells) in enumerate(tiled_map.layers):
            layer_name = f"map{map_index}_layer{layer_index}"
            layer_names.append(layer_name)
            lines.append(f"static const uint16_t {layer_name}[{len(cells)}] = {{")
            lines.extend(c_array_rows([str(cell) for cell in cells], tiled_map.height))
            lines.extend(["};", ""])
        lines.append(
            f"static const uint16_t *const map{map_index}_layers"
            f"[{len(layer_names)}] = {{{', '.join(layer_names)}}};"
        )
        lines.append("")

    lines.append(f"const Map maps[{COUNT_NAME}] = {{")
    for map_index, tiled_map in enumerate(tiled_maps):
        lines.append(
            f"    [{tiled_map.enum}] = {{{tiled_map.width}, {tiled_map.height}, "
            f"{tiled_map.tileset}, {len(tiled_map.layers)}, map{map_index}_layers}},"
        )
    lines.extend(["};", ""])
    return "\n".join(lines)


def run(map_dir: Path, images_dir: Path, out_dir: Path) -> None:
    if not map_dir.is_dir():
        raise ValueError(f"{map_dir}: no such folder")
    paths = sorted(map_dir.glob("*.tmj"))
    if not paths:
        raise ValueError(f"{map_dir}: no .tmj maps")

    symbols = Symbols(RESERVED_NAMES)
    for path in paths:
        symbols.add(enum_name("MAP", path.stem), path.name)
    tiled_maps = [read_tiled_map(path, images_dir, symbols) for path in paths]

    generated_dir = out_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "Maps.h").write_text(header_text(tiled_maps))
    (generated_dir / "Maps.c").write_text(source_text(tiled_maps))
    print(f"process_maps.py: {len(tiled_maps)} maps")


def parse_args(argv: list | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Turn Tiled .tmj maps into column-major C tables of tile cells."
    )
    parser.add_argument("map_dir", type=Path, help="folder of .tmj maps")
    parser.add_argument(
        "--images-dir",
        type=Path,
        required=True,
        help="folder of the images process_graphics.py reads",
    )
    parser.add_argument("--out-dir", type=Path, required=True, help="build folder; gets generated/")
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    arguments = parse_args(argv)
    try:
        run(arguments.map_dir, arguments.images_dir, arguments.out_dir)
    except (ValueError, OSError) as error:
        print(f"process_maps.py: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
