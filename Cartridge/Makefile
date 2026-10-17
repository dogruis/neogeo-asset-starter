all: cart bios

BUILDDIR = build
ROM = $(BUILDDIR)/rom
GAMEROM = puzzledp

PROMSIZE = 524288
CROMSIZE = 1048576
SROMSIZE = 131072
MROMSIZE = 131072
VROMSIZE = 524288

PROM1 = $(ROM)/202-p1.p1
CROM1 = $(ROM)/202-c1.c1
CROM2 = $(ROM)/202-c2.c2
SROM1 = $(ROM)/202-s1.s1
MROM1 = $(ROM)/202-m1.m1
VROM1 = $(ROM)/202-v1.v1
CART = $(ROM)/$(GAMEROM).zip
BIOS = $(ROM)/neogeo.zip

PKGCONFIG ?= pkg-config
M68KOBJCOPY ?= m68k-neogeo-elf-objcopy
Z80SDOBJCOPY ?= z80-neogeo-ihx-sdobjcopy
MAME ?= mame
NGCFLAGS := $(shell $(PKGCONFIG) --cflags ngdevkit)
NGLDFLAGS := $(shell $(PKGCONFIG) --libs ngdevkit)
NGSHAREDIR := $(shell $(PKGCONFIG) --variable=sharedir ngdevkit)

ASSET_BUILD_DIR = $(BUILDDIR)
include ../Make/assets.mk

CFLAGS = -std=c99 -Wall -Wextra -O2 -fomit-frame-pointer -I$(ASSET_GENERATED_DIR)

define pad_to
	@size=`wc -c < $@`; if [ $$size -gt $(1) ]; then \
		echo "$@ holds $$size bytes, more than its $(1)"; exit 1; fi
	dd if=/dev/null of=$@ bs=1 seek=$(1) status=none
endef

cart: $(CART)

bios: $(BIOS)

mame: cart bios
	$(MAME) -w -noautosave -skip_gameinfo -rp $(ROM) \
		-cfg_directory $(BUILDDIR)/mame -nvram_directory $(BUILDDIR)/mame $(GAMEROM)

$(BUILDDIR)/main.o: main.c $(ASSET_HEADERS)
	$(M68KGCC) $(NGCFLAGS) $(CFLAGS) -c $< -o $@

$(BUILDDIR)/rom.elf: $(BUILDDIR)/main.o $(ASSET_OBJECTS)
	$(M68KGCC) -o $@ $^ $(NGLDFLAGS) -Wl,--defsym,rom_eye_catcher_mode=2

$(PROM1): $(BUILDDIR)/rom.elf | $(ROM)
	$(M68KOBJCOPY) -O binary -S -R .text2 --gap-fill 0xff --pad-to $(PROMSIZE) $< $@
	dd if=$@ of=$@ conv=notrunc,swab status=none

$(CROM1): $(GRAPHICS_C1) | $(ROM)
	cat $^ > $@
	$(call pad_to,$(CROMSIZE))

$(CROM2): $(GRAPHICS_C2) | $(ROM)
	cat $^ > $@
	$(call pad_to,$(CROMSIZE))

$(SROM1): | $(ROM)
	: > $@
	$(call pad_to,$(SROMSIZE))

$(MROM1): | $(ROM)
	$(Z80SDOBJCOPY) -I ihex -O binary $(NGSHAREDIR)/nullsound_driver.ihx $@ --pad-to $(MROMSIZE)

$(VROM1): | $(ROM)
	: > $@
	$(call pad_to,$(VROMSIZE))

$(CART): $(PROM1) $(CROM1) $(CROM2) $(SROM1) $(MROM1) $(VROM1)
	rm -f $@
	cd $(ROM) && zip -q $(GAMEROM).zip $(notdir $^)

$(BIOS): | $(ROM)
	cp $(NGSHAREDIR)/neogeo.zip $@

$(ROM):
	mkdir -p $@

clean:
	rm -rf $(BUILDDIR)

.PHONY: all cart bios mame clean
