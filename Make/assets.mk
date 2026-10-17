ASSET_STARTER_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)
ASSET_TOOLS_DIR = $(ASSET_STARTER_DIR)/Tools

ASSET_PYTHON ?= uv run --project $(ASSET_STARTER_DIR) --no-dev python
TILETOOL ?= tiletool.py
M68KGCC ?= m68k-neogeo-elf-gcc

ASSET_IMAGES_DIR ?= art
ASSET_MAPS_DIR ?= maps
ASSET_BUILD_DIR ?= build
ASSET_FIRST_TILE ?= 0
ASSET_FIRST_PALETTE ?= 16

ASSET_GFX_DIR = $(ASSET_BUILD_DIR)/gfx
ASSET_GENERATED_DIR = $(ASSET_BUILD_DIR)/generated
ASSET_IMAGES = $(wildcard $(ASSET_IMAGES_DIR)/*.png $(ASSET_IMAGES_DIR)/*.gif)
ASSET_MAPS = $(wildcard $(ASSET_MAPS_DIR)/*.tmj $(ASSET_MAPS_DIR)/*.tsx)

-include $(ASSET_GFX_DIR)/graphics.mk

GRAPHICS_C1 = $(GRAPHICS_GIFS:%.gif=$(ASSET_GFX_DIR)/%.c1)
GRAPHICS_C2 = $(GRAPHICS_GIFS:%.gif=$(ASSET_GFX_DIR)/%.c2)
ASSET_HEADERS = $(ASSET_GENERATED_DIR)/Graphics.h $(ASSET_GENERATED_DIR)/Maps.h
ASSET_OBJECTS = $(ASSET_GENERATED_DIR)/Graphics.o $(ASSET_GENERATED_DIR)/Maps.o

$(ASSET_GFX_DIR)/graphics.mk: $(ASSET_IMAGES) $(ASSET_TOOLS_DIR)/process_graphics.py $(ASSET_TOOLS_DIR)/codegen.py
	$(ASSET_PYTHON) $(ASSET_TOOLS_DIR)/process_graphics.py $(ASSET_IMAGES_DIR) --out-dir $(ASSET_BUILD_DIR) \
		--first-tile $(ASSET_FIRST_TILE) --first-palette $(ASSET_FIRST_PALETTE)

$(ASSET_GFX_DIR)/%.gif: $(ASSET_GFX_DIR)/graphics.mk ;

$(ASSET_GENERATED_DIR)/Graphics.h $(ASSET_GENERATED_DIR)/Graphics.c: $(ASSET_GFX_DIR)/graphics.mk ;

$(ASSET_GENERATED_DIR)/Maps.c: $(ASSET_MAPS) $(ASSET_IMAGES) $(ASSET_TOOLS_DIR)/process_maps.py $(ASSET_TOOLS_DIR)/tiled.py $(ASSET_TOOLS_DIR)/codegen.py
	$(ASSET_PYTHON) $(ASSET_TOOLS_DIR)/process_maps.py $(ASSET_MAPS_DIR) --images-dir $(ASSET_IMAGES_DIR) \
		--out-dir $(ASSET_BUILD_DIR)

$(ASSET_GENERATED_DIR)/Maps.h: $(ASSET_GENERATED_DIR)/Maps.c ;

$(ASSET_GFX_DIR)/%.c1 $(ASSET_GFX_DIR)/%.c2: $(ASSET_GFX_DIR)/%.gif
	$(TILETOOL) --sprite -c $< -o $(ASSET_GFX_DIR)/$*.c1 $(ASSET_GFX_DIR)/$*.c2

$(ASSET_OBJECTS): $(ASSET_HEADERS)

$(ASSET_GENERATED_DIR)/%.o: $(ASSET_GENERATED_DIR)/%.c
	$(M68KGCC) $(NGCFLAGS) $(CFLAGS) -c $< -o $@
