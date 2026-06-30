# Dial-up

Generates an authentic 1990s dial-up modem call as a WAV file: the dial tone, the touch-tone dialing, the ringback, the answer tone, the negotiation warble, and the connection itself.

Built to produce authentic modem sounds for the intro music of [The Lockdown podcast](https://psysecure.com/podcast/).

The trick is that the part after the modems connect is **not** synthesized. A trained modem carrier is a scrambled, pulse-shaped, QAM-modulated signal, and any attempt to fake it with shaped noise sounds wrong immediately. So instead, two real modems are run in a software loopback ("dialing into ourself") and the result is recorded. Everything up to the connection is synthesized from the real signaling frequencies; the connection is a genuine captured carrier.

## How it works

Two programs, each doing the part it is good at:

- **`modemgen.c`** uses [spandsp](https://www.soft-switch.org/) (the reference telephony DSP library) to produce genuine modem audio:
  - `v22` runs a calling modem and an answering modem cross-connected so they actually perform the V.22bis handshake and exchange a scrambled bit stream. The recorded line is the sum of both transmitters: two QAM carriers (1200 Hz calling, 2400 Hz answering) overlapping in full duplex.
  - `v17` runs a single V.17 transmitter at 14400 bps. Its long training sequence is the loud, broadband "high-speed" hash, resolving to a steady carrier.

- **`dialup.py`** synthesizes the front half of the call from the real signaling tones, applies a telephone-line channel, splices in the captured connection, and writes the WAV. The synthesized stages are:
  - Central-office dial tone (350 + 440 Hz)
  - DTMF dialing of the phone number
  - Ringback (440 + 480 Hz)
  - ANSam answer tone (2100 Hz with periodic phase reversals and a 15 Hz amplitude wobble)
  - V.21 capability exchange: calling modem on the originate channel (980 / 1180 Hz FSK), answering modem on the answer channel (1650 / 1850 Hz), overlapping the way a real handshake does
  - V.34-style line probing (the descending glide plus a wideband probe chord)

The whole thing then runs through a telephone channel: 300–3400 Hz band-pass, hybrid echo, line hiss, mains hum, and gentle companding. Output is 8 kHz mono 16-bit PCM, the authentic phone rate.

## Platforms

Rendering the WAV runs on Linux, macOS, and Windows. `dialup.py` is pure Python standard library, and the captured connection files (`connect_*.raw`) are committed, so no compiler or external library is needed to produce `dialup.wav`.

Regenerating the captures needs a C compiler and spandsp. That works on macOS and Linux natively; on Windows it works under [WSL](https://learn.microsoft.com/windows/wsl/). spandsp has no practical native Windows build, but you never need it just to render — the captures already ship with the repo.

## Render the call

Needs only Python 3:

```
python3 dialup.py        # macOS / Linux
py dialup.py             # Windows
```

On macOS and Linux you can also run `make`.

Play it:

| Platform | Command                                |
| -------- | -------------------------------------- |
| macOS    | `afplay dialup.wav`                    |
| Linux    | `aplay dialup.wav` (or `ffplay`)        |
| Windows  | `start dialup.wav` (or double-click it) |

## Regenerating the captures (optional)

Only needed if you change `modemgen.c` or want fresh captures. Install spandsp and a C compiler:

| Platform        | Install                                              |
| --------------- | --------------------------------------------------- |
| macOS           | `brew install spandsp` (and `xcode-select --install`) |
| Debian / Ubuntu | `sudo apt install libspandsp-dev build-essential`    |
| Fedora          | `sudo dnf install spandsp-devel gcc make`            |
| Windows         | Use WSL, then follow the Linux steps                 |

Then:

```
make capture     # rebuild modemgen and re-record connect_v22.raw / connect_v17.raw
make             # re-render dialup.wav
```

Or by hand on Linux (spandsp headers and libs are in standard paths):

```
cc modemgen.c -o modemgen -lspandsp -lm
./modemgen v22 9 connect_v22.raw
./modemgen v17 6 connect_v17.raw
python3 dialup.py
```

## Configuration

Edit the constants at the top of `dialup.py`:

| Constant        | Default          | Meaning                                            |
| --------------- | ---------------- | -------------------------------------------------- |
| `CONNECT_STYLE` | `"hybrid"`       | `"hybrid"`, `"v17"`, or `"v22"` (see below)        |
| `PHONE_NUMBER`  | `"18005551212"`  | Digits dialed with DTMF                            |
| `SEED`          | `1990`           | Deterministic re-runs; change for variation        |
| `CONNECT_AT`    | `13.0`           | Seconds: when the carrier comes in, over the probe |

Connect styles:

- `hybrid` — the V.22bis dual-carrier lock crossfading into the V.17 high-speed hash. The most complete-sounding arc.
- `v17` — straight to the loud 14400 hash.
- `v22` — the genuine full-duplex two-modem capture; gentler, more early-90s.

## Limitations

spandsp implements V.22bis (2400 bps, full duplex) and the V.17 / V.29 fax carriers (up to 14400 bps, half duplex), but not V.34 or V.90. The true 33.6k / 56k handshake therefore does not exist as a real signal to capture. The loud hash is real V.17 at 14400, which is the same TCM-QAM family and sounds like the iconic connection; the full-duplex texture is real V.22bis. The hybrid style splices these genuine signals into the most authentic-sounding sequence available.

## Files

| File               | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| `dialup.py`        | Synthesizes the front half, splices the capture, renders the WAV |
| `modemgen.c`       | Captures real modem audio via spandsp loopback        |
| `Makefile`         | Builds and renders everything                         |
| `connect_v22.raw`  | Committed capture: full-duplex V.22bis (8 kHz PCM)    |
| `connect_v17.raw`  | Committed capture: V.17 14400 high-speed (8 kHz PCM)  |
| `dialup.wav`       | The finished call (regenerate with `make`)            |
