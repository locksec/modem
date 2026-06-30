# Render the dial-up WAV, and (optionally) regenerate the real modem captures.
#
#   make            render dialup.wav from the committed captures (needs only Python)
#   make capture    re-record the connect_*.raw captures (needs spandsp + a C compiler)
#   make clean      remove the rendered WAV and the compiled binary
#
# The connect_*.raw captures are committed, so rendering works on any platform
# with Python. spandsp is only needed to regenerate them.

CC ?= cc

ifeq ($(shell uname -s),Darwin)
  # macOS / Homebrew
  PREFIX  := $(shell brew --prefix)
  CFLAGS  := -O2 -I$(PREFIX)/include
  LDFLAGS := -L$(PREFIX)/lib -lspandsp -lm
else
  # Linux: spandsp headers/libs are in standard system paths
  CFLAGS  := -O2
  LDFLAGS := -lspandsp -lm
endif

all: dialup.wav

dialup.wav: dialup.py connect_v22.raw connect_v17.raw
	python3 dialup.py

capture: modemgen
	./modemgen v22 9 connect_v22.raw
	./modemgen v17 6 connect_v17.raw

modemgen: modemgen.c
	$(CC) $(CFLAGS) modemgen.c -o modemgen $(LDFLAGS)

clean:
	rm -f modemgen dialup.wav

.PHONY: all capture clean
