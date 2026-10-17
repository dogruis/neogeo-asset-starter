#include <ngdevkit/neogeo.h>
#include <ngdevkit/ng-fix.h>

#include "Graphics.h"
#include "Maps.h"

#define ADDR_SCB1 0
#define ADDR_SCB2 0x8000
#define SCREEN_TOP 496
#define BACKDROP 4095
#define STICKY (1 << 6)
#define FULL_SIZE 0xFFF

static void load_palettes(void)
{
    volatile u16 *target = MMAP_PALBANK1 + (GRAPHICS_FIRST_PALETTE * 16);
    const u16 *source = &palettes[0][0];
    for (u16 index = 0; index < GRAPHICS_PALETTE_COUNT * 16; index++) {
        target[index] = source[index];
    }
    MMAP_PALBANK1[BACKDROP] = 0x79CF;
}

static void place_chain(u16 firstSprite, u16 count, u16 screenX, u16 screenY, u16 tilesTall)
{
    *REG_VRAMMOD = 0x200;
    for (u16 sprite = 0; sprite < count; sprite++) {
        *REG_VRAMADDR = ADDR_SCB2 + firstSprite + sprite;
        *REG_VRAMRW = FULL_SIZE;
        if (sprite == 0) {
            *REG_VRAMRW = (u16)((((SCREEN_TOP - screenY) & 0x1FF) << 7) | tilesTall);
            *REG_VRAMRW = (u16)(screenX << 7);
        } else {
            *REG_VRAMRW = STICKY;
        }
    }
}

static void draw_map_layer(u16 firstSprite, const Map *map, u8 layer)
{
    const Graphic *tileset = &graphics[map->tileset];
    const u16 *cell = map->layers[layer];
    *REG_VRAMMOD = 1;
    for (u16 column = 0; column < map->widthInTiles; column++) {
        *REG_VRAMADDR = ADDR_SCB1 + ((firstSprite + column) * 64);
        for (u16 row = 0; row < map->heightInTiles; row++) {
            u16 value = *cell++;
            u16 tile = value & MAP_CELL_TILE_MASK;
            if (tile == 0) {
                *REG_VRAMRW = GRAPHICS_BLANK_TILE;
                *REG_VRAMRW = 0;
                continue;
            }
            u16 flips = ((value & MAP_CELL_FLIP_X) ? 1 : 0) | ((value & MAP_CELL_FLIP_Y) ? 2 : 0);
            *REG_VRAMRW = tileset->firstTile + tile - 1;
            *REG_VRAMRW = (u16)((tileset->tilePalettes[tile - 1] << 8) | flips);
        }
    }
    place_chain(firstSprite, map->widthInTiles, 0, 0, map->heightInTiles);
}

static void draw_graphic(u16 firstSprite, const Graphic *graphic, u8 frame, u16 screenX, u16 screenY)
{
    u16 tilesPerFrame = graphic->tilesAcross * graphic->tilesDown;
    u16 frameTile = frame * tilesPerFrame;
    *REG_VRAMMOD = 1;
    for (u16 column = 0; column < graphic->tilesAcross; column++) {
        *REG_VRAMADDR = ADDR_SCB1 + ((firstSprite + column) * 64);
        for (u16 row = 0; row < graphic->tilesDown; row++) {
            u16 index = frameTile + (row * graphic->tilesAcross) + column;
            *REG_VRAMRW = graphic->firstTile + index;
            *REG_VRAMRW = (u16)(graphic->tilePalettes[index] << 8);
        }
    }
    place_chain(firstSprite, graphic->tilesAcross, screenX, screenY, graphic->tilesDown);
}

volatile u8 vblank = 0;

void rom_callback_VBlank(void)
{
    vblank = 1;
}

int main(void)
{
    const Map *level = &maps[MAP_LEVEL1];
    const Graphic *hero = &graphics[GFX_HERO];
    u16 heroHeight = hero->tilesDown * 16;
    u8 frame = 0;
    u8 ticks = 0;

    ng_cls();
    load_palettes();
    draw_map_layer(1, level, MAP_LEVEL1_LAYER_GROUND);
    draw_map_layer(1 + level->widthInTiles, level, MAP_LEVEL1_LAYER_DECOR);

    for (;;) {
        draw_graphic(1 + (2 * level->widthInTiles), hero, frame,
                     MAP_LEVEL1_PLAYER_START_X, MAP_LEVEL1_PLAYER_START_Y - heroHeight);
        if (++ticks == 15) {
            ticks = 0;
            frame = (u8)((frame + 1) == hero->frameCount ? 0 : frame + 1);
        }
        while (!vblank) {
        }
        vblank = 0;
    }
    return 0;
}
