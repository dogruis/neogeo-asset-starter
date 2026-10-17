import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageSequence, UnidentifiedImageError

from codegen import Symbols, c_array_rows, enum_name

TILE_SIZE = 16
PALETTE_SIZE = 16
VISIBLE_COLOURS = PALETTE_SIZE - 1
FIX_LAYER_PALETTES = 16
BACKDROP_PALETTE = 255
LAST_TILE = 0xFFFF
BYTE_MAX = 0xFF
IMAGE_EXTENSIONS = (".png", ".gif")
BLANK_GIF = "blank-tile.gif"
COUNT_NAME = "GFX_COUNT"
GREY_RAMP = [level for index in range(PALETTE_SIZE) for level in (index * 17,) * 3]


@dataclass
class Tile:
    frame: int
    left: int
    top: int
    pixels: list
    colours: set

    def where(self) -> str:
        return f"tile at x={self.left} y={self.top} of frame {self.frame}"


@dataclass
class Graphic:
    path: Path
    enum: str
    width: int
    height: int
    frame_count: int
    tiles: list
    first_tile: int = 0
    tile_palettes: list = field(default_factory=list)

    @property
    def palettes_array(self) -> str:
        return f"{self.enum.lower()}_tile_palettes"

    @property
    def gif_name(self) -> str:
        return f"{self.enum[len('GFX_') :].lower()}.gif"


class Palette:
    def __init__(self) -> None:
        self.colours = []

    def added_cost(self, colours: set) -> int:
        return len(colours.difference(self.colours))

    def fits(self, colours: set) -> bool:
        return len(self.colours) + self.added_cost(colours) <= VISIBLE_COLOURS

    def merge(self, colours: set) -> None:
        self.colours.extend(sorted(colours.difference(self.colours)))

    def index_of(self, colour: tuple) -> int:
        return self.colours.index(colour) + 1


def neogeo_colour(colour: tuple) -> int:
    red, green, blue = (channel >> 2 for channel in colour)
    dark = int(not (red & 1 or green & 1 or blue & 1))
    low_bits = (((red >> 1) & 1) << 2) | (((green >> 1) & 1) << 1) | ((blue >> 1) & 1)
    return (dark << 15) | (low_bits << 12) | ((red >> 2) << 8) | ((green >> 2) << 4) | (blue >> 2)


def rgba_pixels(image: Image.Image) -> list:
    raw = image.tobytes()
    return [tuple(raw[offset : offset + 4]) for offset in range(0, len(raw), 4)]


def read_frames(path: Path) -> list:
    try:
        with Image.open(path) as image:
            return [frame.convert("RGBA") for frame in ImageSequence.Iterator(image)]
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError(f"{path.name}: not a readable image ({error})") from error


def tile_origins(width: int, height: int):
    return (
        (left, top) for top in range(0, height, TILE_SIZE) for left in range(0, width, TILE_SIZE)
    )


def read_tile(path: Path, frame_number: int, frame: Image.Image, left: int, top: int) -> Tile:
    pixels = rgba_pixels(frame.crop((left, top, left + TILE_SIZE, top + TILE_SIZE)))
    tile = Tile(frame_number, left, top, pixels, set())
    for red, green, blue, alpha in pixels:
        if alpha == 0:
            continue
        if alpha != 255:
            raise ValueError(
                f"{path.name}: {tile.where()} has a half-transparent pixel (alpha {alpha}); "
                "a pixel is either fully visible or fully transparent"
            )
        tile.colours.add((red, green, blue))
    if len(tile.colours) > VISIBLE_COLOURS:
        raise ValueError(
            f"{path.name}: {tile.where()} uses {len(tile.colours)} colours; "
            f"a tile holds at most {VISIBLE_COLOURS} plus transparent"
        )
    return tile


def check_fits_byte(path: Path, label: str, value: int) -> None:
    if value > BYTE_MAX:
        raise ValueError(f"{path.name}: {label} {value} does not fit a uint8_t field in Graphics.h")


def read_graphic(path: Path) -> Graphic:
    frames = read_frames(path)
    width, height = frames[0].size
    if width % TILE_SIZE or height % TILE_SIZE:
        raise ValueError(
            f"{path.name}: {width}x{height} is not a multiple of {TILE_SIZE} pixels "
            "in both directions"
        )
    check_fits_byte(path, "tiles across", width // TILE_SIZE)
    check_fits_byte(path, "tiles down", height // TILE_SIZE)
    check_fits_byte(path, "frame count", len(frames))

    tiles = [
        read_tile(path, frame_number, frame, left, top)
        for frame_number, frame in enumerate(frames)
        for left, top in tile_origins(width, height)
    ]
    if not any(tile.colours for tile in tiles):
        raise ValueError(f"{path.name}: every pixel is transparent")
    return Graphic(path, enum_name("GFX", path.stem), width, height, len(frames), tiles)


def choose_palette(colours: set, palettes: list) -> int:
    fitting = [
        (palette.added_cost(colours), number)
        for number, palette in enumerate(palettes)
        if palette.fits(colours)
    ]
    if fitting:
        number = min(fitting)[1]
    else:
        palettes.append(Palette())
        number = len(palettes) - 1
    palettes[number].merge(colours)
    return number


def assign_palettes(graphic: Graphic, palettes: list) -> None:
    tiles = graphic.tiles
    assigned = [None] * len(tiles)
    for index in sorted(range(len(tiles)), key=lambda index: (-len(tiles[index].colours), index)):
        if tiles[index].colours:
            assigned[index] = choose_palette(tiles[index].colours, palettes)
    own = next(number for number in assigned if number is not None)
    graphic.tile_palettes = [own if number is None else number for number in assigned]


def check_palette_count(palettes: list, first_palette: int) -> None:
    last = first_palette + len(palettes) - 1
    if last >= BACKDROP_PALETTE:
        raise ValueError(
            f"{len(palettes)} palettes from palette {first_palette} end at {last}; "
            f"palette {BACKDROP_PALETTE} holds the backdrop colour, so stop at "
            f"{BACKDROP_PALETTE - 1}"
        )


def lay_out_tiles(graphics: list, first_tile: int) -> int:
    next_tile = first_tile
    for graphic in graphics:
        graphic.first_tile = next_tile
        next_tile += len(graphic.tiles)
    if next_tile > LAST_TILE:
        raise ValueError(
            f"the graphics and the blank tile end at tile {next_tile}; tile numbers past "
            f"{LAST_TILE} do not fit the uint16_t firstTile field"
        )
    return next_tile


def indexed_image(graphic: Graphic, palettes: list) -> Image.Image:
    image = Image.new("P", (graphic.width, graphic.height * graphic.frame_count), 0)
    for tile, number in zip(graphic.tiles, graphic.tile_palettes, strict=True):
        palette = palettes[number]
        indices = bytes(
            0 if alpha == 0 else palette.index_of((red, green, blue))
            for red, green, blue, alpha in tile.pixels
        )
        tile_image = Image.frombytes("P", (TILE_SIZE, TILE_SIZE), indices)
        image.paste(tile_image, (tile.left, (tile.frame * graphic.height) + tile.top))
    image.putpalette(GREY_RAMP)
    return image


def write_gif(image: Image.Image, path: Path) -> None:
    image.save(path, format="GIF", optimize=False)
    with Image.open(path) as saved:
        if saved.tobytes() != image.tobytes():
            raise ValueError(f"{path.name}: pixel indices changed when the GIF was saved")


def header_text(graphics: list, palettes: list, first_palette: int, blank_tile: int) -> str:
    lines = [
        "#ifndef GRAPHICS_H",
        "#define GRAPHICS_H",
        "",
        "#include <stdint.h>",
        "",
        f"#define GRAPHICS_FIRST_PALETTE {first_palette}",
        f"#define GRAPHICS_PALETTE_COUNT {len(palettes)}",
        f"#define GRAPHICS_BLANK_TILE {blank_tile}",
        f"#define GRAPHICS_TILE_END {blank_tile + 1}",
        "",
        "typedef struct {",
        "    uint16_t firstTile;",
        "    uint8_t tilesAcross;",
        "    uint8_t tilesDown;",
        "    uint8_t frameCount;",
        "    const uint8_t *tilePalettes;",
        "} Graphic;",
        "",
        "typedef enum {",
        *(f"    {graphic.enum}," for graphic in graphics),
        f"    {COUNT_NAME}",
        "} GraphicId;",
        "",
        f"extern const Graphic graphics[{COUNT_NAME}];",
        f"extern const uint16_t palettes[GRAPHICS_PALETTE_COUNT][{PALETTE_SIZE}];",
        "",
        "#endif",
        "",
    ]
    return "\n".join(lines)


def source_text(graphics: list, palettes: list, first_palette: int) -> str:
    lines = ['#include "Graphics.h"', ""]
    for graphic in graphics:
        numbers = [str(first_palette + number) for number in graphic.tile_palettes]
        lines.append(f"static const uint8_t {graphic.palettes_array}[{len(numbers)}] = {{")
        lines.extend(c_array_rows(numbers, graphic.width // TILE_SIZE))
        lines.extend(["};", ""])

    lines.append(f"const Graphic graphics[{COUNT_NAME}] = {{")
    for graphic in graphics:
        lines.append(
            f"    [{graphic.enum}] = {{{graphic.first_tile}, {graphic.width // TILE_SIZE}, "
            f"{graphic.height // TILE_SIZE}, {graphic.frame_count}, "
            f"{graphic.palettes_array}}},"
        )
    lines.extend(["};", ""])

    lines.append(f"const uint16_t palettes[GRAPHICS_PALETTE_COUNT][{PALETTE_SIZE}] = {{")
    for palette in palettes:
        words = [0] + [neogeo_colour(colour) for colour in palette.colours]
        words.extend([0] * (PALETTE_SIZE - len(words)))
        lines.append("    {")
        lines.extend("    " + row for row in c_array_rows([f"0x{word:04X}" for word in words], 8))
        lines.append("    },")
    lines.extend(["};", ""])
    return "\n".join(lines)


def run(image_dir: Path, out_dir: Path, first_tile: int, first_palette: int) -> None:
    if not 0 <= first_palette < BACKDROP_PALETTE:
        raise ValueError(f"--first-palette {first_palette} must be 0..{BACKDROP_PALETTE - 1}")
    if not 0 <= first_tile <= LAST_TILE:
        raise ValueError(f"--first-tile {first_tile} must be 0..{LAST_TILE}")
    if not image_dir.is_dir():
        raise ValueError(f"{image_dir}: no such folder")

    paths = sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS)
    if not paths:
        raise ValueError(f"{image_dir}: no .png or .gif images")
    symbols = Symbols({COUNT_NAME: "the graphic count"})
    for path in paths:
        symbols.add(enum_name("GFX", path.stem), path.name)

    graphics = [read_graphic(path) for path in paths]
    palettes = []
    for graphic in graphics:
        assign_palettes(graphic, palettes)
    check_palette_count(palettes, first_palette)
    blank_tile = lay_out_tiles(graphics, first_tile)

    gfx_dir = out_dir / "gfx"
    generated_dir = out_dir / "generated"
    gfx_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    gif_names = []
    for graphic in graphics:
        write_gif(indexed_image(graphic, palettes), gfx_dir / graphic.gif_name)
        gif_names.append(graphic.gif_name)
    blank = Image.new("P", (TILE_SIZE, TILE_SIZE), 0)
    blank.putpalette(GREY_RAMP)
    write_gif(blank, gfx_dir / BLANK_GIF)
    gif_names.append(BLANK_GIF)

    (generated_dir / "Graphics.h").write_text(
        header_text(graphics, palettes, first_palette, blank_tile)
    )
    (generated_dir / "Graphics.c").write_text(source_text(graphics, palettes, first_palette))
    (gfx_dir / "graphics.mk").write_text(f"GRAPHICS_GIFS = {' '.join(gif_names)}\n")
    print(
        f"process_graphics.py: {len(graphics)} graphics, tiles {first_tile}..{blank_tile}, "
        f"palettes {first_palette}..{first_palette + len(palettes) - 1}"
    )


def parse_args(argv: list | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cut .png and .gif images into Neo Geo sprite tiles with a palette per "
        "tile, and write the C tables that name them."
    )
    parser.add_argument("image_dir", type=Path, help="folder of .png and .gif images")
    parser.add_argument(
        "--out-dir", type=Path, required=True, help="build folder; gets gfx/ and generated/"
    )
    parser.add_argument(
        "--first-tile", type=int, default=0, help="C-ROM tile number of the first tile"
    )
    parser.add_argument(
        "--first-palette",
        type=int,
        default=FIX_LAYER_PALETTES,
        help="palette number of the first palette",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    arguments = parse_args(argv)
    try:
        run(arguments.image_dir, arguments.out_dir, arguments.first_tile, arguments.first_palette)
    except (ValueError, OSError) as error:
        print(f"process_graphics.py: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
