# Build the modem-capture tool and render the dial-up WAV.
#
#   make            build everything and render dialup.wav
#   make clean      remove generated files
#
# Requires Homebrew spandsp:  brew install spandsp

PREFIX  := $(shell brew --prefix)
CC      ?= cc
CFLAGS  := -O2 -I$(PREFIX)/include
LDFLAGS := -L$(PREFIX)/lib -lspandsp -lm

all: dialup.wav

modemgen: modemgen.c
	$(CC) $(CFLAGS) modemgen.c -o modemgen $(LDFLAGS)

connect_v22.raw: modemgen
	./modemgen v22 9 connect_v22.raw

connect_v17.raw: modemgen
	./modemgen v17 6 connect_v17.raw

dialup.wav: dialup.py connect_v22.raw connect_v17.raw
	python3 dialup.py

clean:
	rm -f modemgen connect_v22.raw connect_v17.raw dialup.wav

.PHONY: all clean
