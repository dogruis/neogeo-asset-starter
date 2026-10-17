# neogeo-asset-starter

A small build-time asset pipeline for Neo Geo homebrew made with
[ngdevkit](https://github.com/dciabrin/ngdevkit). Two Python scripts turn
images and [Tiled](https://www.mapeditor.org/) maps into sprite tiles for the
C-ROM and C tables for your game.

- Game code names its graphics (`GFX_HERO`, `MAP_LEVEL1`) and never uses raw
  tile numbers, so art and code cannot drift apart.
- Artists paint with ordinary images. The 16-colour palette limit is handled
  per 16×16 tile at build time.
- When an asset cannot work on the hardware, the build stops and names the
  file, the tile and the fix.

![The example map and hero running in MAME](Example/screenshot.png)

## What is inside

| Path | What it does |
| --- | --- |
| `Tools/process_graphics.py` | Images → indexed GIFs for `tiletool.py`, `Graphics.h/.c` (tile numbers, a palette per tile, the palettes). |
| `Tools/process_maps.py` | Tiled `.tmj` maps → `Maps.h/.c` (tile cells per layer, named points). |
| `Tools/codegen.py` | File name → C name: `hero_run.gif` becomes `GFX_HERO_RUN`. |
| `Tools/tiled.py` | Reads Tiled tilesets, maps, layers and point objects. |
| `Make/assets.mk` | Make rules that run the scripts, `tiletool.py` and the compiler. |
| `Example/` | Two images, a tileset, a map, and a `main.c` that draws them. |

## Quick start

You need [uv](https://docs.astral.sh/uv/) and ngdevkit installed
(`tiletool.py` and `m68k-neogeo-elf-gcc` on your `PATH`). The Make rules run
the scripts with `uv run`, which installs Python and Pillow into this repo's
`.venv/` on the first build. ngdevkit's own Python setup is left alone.

```bash
make -C Example
```

`Example/build/` then holds:

```
gfx/hero.gif  gfx/tiles.gif  gfx/blank-tile.gif   tile indices, ready for tiletool
gfx/*.c1  gfx/*.c2                                C-ROM data for each graphic
gfx/graphics.mk                                   the GIF list, in C-ROM order
generated/Graphics.h  generated/Graphics.c        graphics and palettes
generated/Maps.h  generated/Maps.c                maps
```

Works with the GNU Make 3.81 that ships with macOS.

## Graphics

`process_graphics.py` reads every `.png` and `.gif` in a folder (sorted by
name) and gives each one a name from its file name.

**Tiles.** Each image is cut into 16×16 tiles: left to right, top to bottom,
then the next frame of a GIF. `tiletool.py` writes the C-ROM in this same
order, so tile `index` of a graphic is C-ROM tile `firstTile + index`. One
blank tile follows the last graphic (`GRAPHICS_BLANK_TILE`), so empty map
cells have something to point at.

**A palette per tile.** A Neo Geo pixel is 4 bits: index 0 is transparent and
15 colours are left. The limit applies per tile, not per image, so each 16×16
tile gets its own palette. Tiles share a palette whenever their colours fit,
which keeps the palette count low. The artist paints one normal image and
never thinks about palettes. The only rule is at most 15 colours in any
16×16 square.

**Transparency** is alpha 0. A half-transparent pixel stops the build: the
hardware has no blending.

**Colours** are packed into the Neo Geo colour word the same way as
ngdevkit's `paltool.py`, including its dark-bit rule.

The generated header:

```c
#define GRAPHICS_FIRST_PALETTE 16
#define GRAPHICS_PALETTE_COUNT 2
#define GRAPHICS_BLANK_TILE 16
#define GRAPHICS_TILE_END 17

typedef struct {
    uint16_t firstTile;
    uint8_t tilesAcross;
    uint8_t tilesDown;
    uint8_t frameCount;
    const uint8_t *tilePalettes;
} Graphic;

typedef enum {
    GFX_HERO,
    GFX_TILES,
    GFX_COUNT
} GraphicId;

extern const Graphic graphics[GFX_COUNT];
extern const uint16_t palettes[GRAPHICS_PALETTE_COUNT][16];
```

Loading the palettes into palette RAM:

```c
volatile u16 *target = MMAP_PALBANK1 + (GRAPHICS_FIRST_PALETTE * 16);
const u16 *source = &palettes[0][0];
for (u16 index = 0; index < GRAPHICS_PALETTE_COUNT * 16; index++) {
    target[index] = source[index];
}
```

Writing one tile of a graphic into a sprite's SCB1 entry. The palette goes
in the high byte of the second word:

```c
const Graphic *hero = &graphics[GFX_HERO];
u16 index = (frame * hero->tilesAcross * hero->tilesDown) + (row * hero->tilesAcross) + column;
*REG_VRAMRW = hero->firstTile + index;
*REG_VRAMRW = hero->tilePalettes[index] << 8;
```

`Example/main.c` has the whole thing: palettes, a map drawn as one sprite per
column, and the hero animating.

## Maps

`process_maps.py` reads every `.tmj` map in a folder. Set Tiled up like this:

- Save maps as JSON (`.tmj`). JSON keeps the layers, the tileset link and the
  objects in one file.
- Set **Tile Layer Format** to **CSV** in the map properties. The JSON stays
  human-readable.
- Keep the tileset in its own `.tsx` file (**Export Tileset** if it is
  embedded). One tileset per map, 16×16 tiles, no spacing or margin.
- The tileset image must be one of the images `process_graphics.py` reads.
  The map refers to it as `GFX_<image name>`.
- Name a point object (`player_start`) and it becomes
  `MAP_LEVEL1_PLAYER_START_X` and `_Y`.

Each layer becomes an array of `uint16_t` cells:

| Cell bits | Meaning |
| --- | --- |
| `MAP_CELL_TILE_MASK` (0–13) | 0 = empty, otherwise tile + 1 of the tileset graphic |
| `MAP_CELL_FLIP_X` (14) | Flipped horizontally: SCB1 second word, bit 0 |
| `MAP_CELL_FLIP_Y` (15) | Flipped vertically: SCB1 second word, bit 1 |

**Cells are stored column by column**, `layer[column * heightInTiles + row]`.
A Neo Geo sprite is a column one tile wide, so filling one sprite's SCB1 reads
one run of the array with no multiply per cell.

## The checks, and why each one exists

| The build stops when | Because |
| --- | --- |
| An image is not a multiple of 16 pixels | Sprite tiles are 16×16 in hardware. |
| A tile has more than 15 colours | 4 bits per pixel, and index 0 is transparent. |
| A pixel is half transparent | The Neo Geo has no blending; a pixel shows or it does not. |
| An image is fully transparent | Almost always a wrong export. |
| Two files give the same name (`hero.png`, `hero.gif`) | Two `GFX_HERO` constants would not compile. |
| The palettes reach palette 255 | Its last colour is the backdrop colour behind everything. |
| Tile numbers pass 65535 | `firstTile` is `uint16_t`. The hardware takes 20 bits; the top 4 go in bits 4–7 of SCB1's second word. |
| A saved GIF reads back different indices | `tiletool.py` reads indices, so a drift means wrong colours on the cart. |
| A map uses more than one tileset, or an embedded one | Each cell must map to exactly one tile of one graphic. |
| A map is infinite, compressed, or not 16×16 | The script reads plain CSV cells of one fixed size. |
| A cell is rotated | The hardware flips tiles but cannot rotate them. |
| A cell uses a tile the tileset does not have | It would draw whatever comes next in C-ROM. |
| A named object is not a point, or sits outside the map | A spawn in the wrong place is easier to fix at build time. |

`--first-palette` defaults to 16 because fix-layer text can only use palettes
0–15.

## Using it in your own ngdevkit project

Clone this repo next to a copy of `00-template` from
[ngdevkit-examples](https://github.com/dciabrin/ngdevkit-examples). Put your
images in `art/` and your maps and tilesets in `maps/`, then add these lines
to the template's `Makefile`, after `include emu.mk`:

```make
STARTER = ../neogeo-asset-starter
ASSET_FIRST_TILE = 256
include $(STARTER)/Make/assets.mk
CFLAGS += -I$(ASSET_GENERATED_DIR)
```

Change the program ROM line to link the generated tables:

```make
$(ELF):	$(BUILDDIR)/main.o $(ASSET_OBJECTS)
$(BUILDDIR)/main.o: $(ASSET_HEADERS)
```

And add your tiles after the template's own C-ROM lines:

```make
$(CROM1): $(GRAPHICS_C1)
$(CROM2): $(GRAPHICS_C2)
```

`ASSET_FIRST_TILE = 256` because the template puts its 256 BIOS logo tiles
at the start of C-ROM, so yours begin after them.

To see the example on a cart, copy `Example/main.c` over the template's
`main.c`, point the folders at the example, then run `make cart bios mame`:

```make
ASSET_IMAGES_DIR = $(STARTER)/Example/art
ASSET_MAPS_DIR = $(STARTER)/Example/maps
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `ASSET_IMAGES_DIR` | `art` | Folder of `.png` and `.gif` images |
| `ASSET_MAPS_DIR` | `maps` | Folder of `.tmj` maps and their `.tsx` tilesets |
| `ASSET_BUILD_DIR` | `build` | Where `gfx/` and `generated/` go |
| `ASSET_FIRST_TILE` | `0` | C-ROM tile number of your first tile |
| `ASSET_FIRST_PALETTE` | `16` | Palette number of your first palette |
| `ASSET_PYTHON` | `uv run ... python` | How the scripts are run |

## Lint and format

```bash
uv run ruff check
```

```bash
uv run ruff format
```

## Licence

MIT, see `LICENSE`. The example art is simple placeholder art made for this
repo.
