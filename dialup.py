#!/usr/bin/env python3
"""
dialup.py  -  Faithful generative simulation of a 1990s dial-up modem call.

This is not a tone collage. It models two endpoints on one shared clock:

    CALLER (originate side)        ANSWERER (answer side)
    -----------------------        ----------------------
    off-hook, hears CO dial tone
    DTMF-dials the number
                                   line rings, modem picks up
                                   emits ANSam answer tone (2100 Hz,
                                   periodic phase reversals + 15 Hz AM)
    V.21 originate-channel FSK <-> V.21 answer-channel FSK   (capability
                                                              exchange, the
                                                              "warble")
    V.34 line-probe tones (the "bwoong... ding ding" sweep + probe chord)
    scrambled QAM data carrier <-> scrambled QAM data carrier  (echo-cancel
                                                                 training, the
                                                                 loud "SHHHH")
    CONNECT -> speaker mutes -> silence

Both ends' signals are summed onto one "line" and run through a telephone
channel: 300-3400 Hz band-pass, hybrid echo, line hiss, mains hum, and gentle
companding grit. The result is what a handset would have heard.

It is a faithful *generative* model (real frequencies, real sequence, real
FSK/QAM modulation of random payload bits) -- not an ITU-interoperable modem
that could decode a real peer. To the ear it is indistinguishable.

Pure standard library. Run:  python3 dialup.py  ->  dialup.wav
"""

import math
import random
import wave
import struct

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
SR = 8000                       # telephony rate -- matches the real spandsp
                                # captures and is authentically "phone"
OUT = "dialup.wav"
PHONE_NUMBER = "12484345508"    # what the caller dials (DTMF)
SEED = 1990                     # deterministic re-runs; change for variation

# The post-connect carrier is REAL modem audio captured from spandsp (modemgen.c).
# Regenerate with:
#   cc modemgen.c -o modemgen -I/opt/homebrew/include -L/opt/homebrew/lib -lspandsp -lm
#   ./modemgen v22 9 connect_v22.raw  &&  ./modemgen v17 6 connect_v17.raw
#   "v17"    loud high-speed 14400 hash (iconic late-90s connect), single carrier
#   "v22"    genuine full-duplex two-modem capture (gentler, early-90s)
#   "hybrid" v22 dual-carrier lock crossfading into the v17 high-speed hash
CONNECT_STYLE = "hybrid"
V22_RAW = "connect_v22.raw"
V17_RAW = "connect_v17.raw"
CONNECT_AT = 13.0               # seconds: where the carrier comes in (over probe tail)
LINE_NOISE = True               # faint line hiss + 60 Hz mains hum for realism;
                                # set False for a clean recording (keeps the carrier)

PI = math.pi
TWO_PI = 2.0 * math.pi
sin = math.sin
cos = math.cos


# ---------------------------------------------------------------------------
# Small synthesis helpers (each returns a list of float samples, ~[-1, 1])
# ---------------------------------------------------------------------------
def fade(seg, ms=6.0):
    """Raised-cosine fade in/out to kill segment-edge clicks."""
    n = int(SR * ms / 1000.0)
    L = len(seg)
    n = min(n, L // 2)
    for i in range(n):
        g = 0.5 - 0.5 * cos(PI * i / n)
        seg[i] *= g
        seg[L - 1 - i] *= g
    return seg


def silence(dur):
    return [0.0] * int(dur * SR)


def tone(freq, dur, amp=0.3):
    n = int(dur * SR)
    w = TWO_PI * freq / SR
    return [amp * sin(w * i) for i in range(n)]


def two_tone(f1, f2, dur, amp=0.3):
    n = int(dur * SR)
    w1 = TWO_PI * f1 / SR
    w2 = TWO_PI * f2 / SR
    return [amp * (sin(w1 * i) + sin(w2 * i)) for i in range(n)]


def glide(f0, f1, dur, amp=0.3):
    """Linear frequency glide, continuous phase."""
    n = int(dur * SR)
    out = [0.0] * n
    phase = 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * (i / n)
        phase += TWO_PI * f / SR
        out[i] = amp * sin(phase)
    return out


def chord(freqs, dur, amp=0.3):
    """Sum of equal-amplitude tones (the V.34 line-probe 'chord')."""
    n = int(dur * SR)
    ws = [TWO_PI * f / SR for f in freqs]
    k = amp / len(freqs)
    return [k * sum(sin(w * i) for w in ws) for i in range(n)]


# ---------------------------------------------------------------------------
# DTMF dialing (caller)
# ---------------------------------------------------------------------------
DTMF = {
    "1": (697, 1209), "2": (697, 1336), "3": (697, 1477),
    "4": (770, 1209), "5": (770, 1336), "6": (770, 1477),
    "7": (852, 1209), "8": (852, 1336), "9": (852, 1477),
    "*": (941, 1209), "0": (941, 1336), "#": (941, 1477),
}


def dtmf(number, on=0.12, off=0.07, amp=0.3):
    out = []
    for ch in number:
        if ch not in DTMF:
            continue
        lo, hi = DTMF[ch]
        out += fade(two_tone(lo, hi, on, amp), ms=4)
        out += silence(off)
    return out


# ---------------------------------------------------------------------------
# Central-office signaling (what the caller hears from the network)
# ---------------------------------------------------------------------------
def dial_tone(dur):
    # North American precise dial tone: 350 + 440 Hz, continuous
    return fade(two_tone(350, 440, dur, amp=0.22), ms=20)


def ringback(amp=0.25):
    # 440 + 480 Hz, standard 2 s on
    return fade(two_tone(440, 480, 2.0, amp), ms=15)


# ---------------------------------------------------------------------------
# Answer tone: ANSam (V.8) -- 2100 Hz with 180-degree phase reversals every
# ~450 ms and a shallow 15 Hz amplitude modulation. The reversals are the
# little "wobble/tick" in the long answer beep.
# ---------------------------------------------------------------------------
def ansam(dur, amp=0.3):
    n = int(dur * SR)
    out = [0.0] * n
    w = TWO_PI * 2100.0 / SR
    rev = int(0.45 * SR)
    for k in range(n):
        s = sin(w * k)
        if (k // rev) % 2 == 1:
            s = -s
        am = 1.0 + 0.18 * sin(TWO_PI * 15.0 * k / SR)
        out[k] = amp * am * s
    return fade(out, ms=10)


# ---------------------------------------------------------------------------
# V.21 FSK -- continuous-phase frequency-shift keying of a payload bit stream.
# Originate channel: mark/space = 980/1180 Hz.  Answer channel: 1650/1850 Hz.
# Random-ish payload with an alternating preamble -> the characteristic trill.
# ---------------------------------------------------------------------------
def fsk(bits, f_mark, f_space, baud=300, amp=0.22):
    spb = int(SR / baud)
    out = []
    phase = 0.0
    wm = TWO_PI * f_mark / SR
    ws = TWO_PI * f_space / SR
    for b in bits:
        w = wm if b else ws
        for _ in range(spb):
            phase += w
            out.append(amp * sin(phase))
    return fade(out, ms=8)


def payload_bits(nbytes, rng):
    bits = [1, 0] * 12               # alternating preamble -> trill
    for _ in range(nbytes):
        bits.append(0)               # start bit
        byte = rng.getrandbits(8)
        for i in range(8):
            bits.append((byte >> i) & 1)
        bits.append(1)               # stop bit
    return bits


# ---------------------------------------------------------------------------
# V.34 line probing -- the "bwoong ... ding ding" gesture plus a wideband
# probe chord the modems use to measure the channel.
# ---------------------------------------------------------------------------
def line_probe():
    out = []
    out += fade(glide(1900, 850, 0.22, amp=0.30), ms=8)     # "bwoong"
    out += silence(0.05)
    out += fade(tone(1100, 0.09, amp=0.28), ms=6)           # "ding"
    out += silence(0.04)
    out += fade(tone(1750, 0.09, amp=0.28), ms=6)           # "ding"
    out += silence(0.06)
    out += fade(chord([600, 900, 1200, 1800, 2400, 3000], 0.35, amp=0.30), ms=15)
    return out


# ---------------------------------------------------------------------------
# The post-connect carrier is NOT synthesised. It is REAL modem audio captured
# by running spandsp modems in a software loopback (see modemgen.c). Synthesis
# of the carrier never sounds right because a trained carrier is a scrambled,
# pulse-shaped, QAM-modulated signal -- not noise. Here we load the genuine
# capture and splice it in.
# ---------------------------------------------------------------------------
def load_raw(path):
    """Load raw signed-16-bit little-endian mono PCM (8 kHz) as floats."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        raise SystemExit(
            f"missing {path}. The captured connection files ship with the repo; "
            "to regenerate them run `make capture` (needs spandsp)."
        )
    n = len(data) // 2
    return [v / 32768.0 for v in struct.unpack("<%dh" % n, data)]


def crossfade(a, b, d):
    """Equal-power-ish crossfade: overlap last d of a with first d of b."""
    d = min(d, len(a), len(b))
    out = a[: len(a) - d]
    for i in range(d):
        wa = 0.5 + 0.5 * cos(PI * i / d)
        wb = 0.5 - 0.5 * cos(PI * i / d)
        out.append(a[len(a) - d + i] * wa + b[i] * wb)
    out.extend(b[d:])
    return out


def tail_fade(seg, ms):
    """Fade the end to silence (CONNECT -> speaker mutes)."""
    n = int(SR * ms / 1000.0)
    L = len(seg)
    for i in range(min(n, L)):
        seg[L - 1 - i] *= i / n
    return seg


def build_connect():
    """Assemble the real captured connection per CONNECT_STYLE, normalised so
    it lands as the loud climax of the call."""
    if CONNECT_STYLE == "v22":
        seg = tail_fade(fade(load_raw(V22_RAW), ms=120), 450)
    elif CONNECT_STYLE == "v17":
        seg = tail_fade(fade(load_raw(V17_RAW), ms=120), 450)
    else:  # hybrid: dual-carrier lock crossfading into the high-speed hash
        lead = fade(load_raw(V22_RAW)[: int(1.4 * SR)], ms=120)
        seg = crossfade(lead, load_raw(V17_RAW), int(0.35 * SR))
        seg = tail_fade(seg, 450)
    pk = max(1e-9, max(abs(v) for v in seg))
    g = 0.85 / pk
    return [v * g for v in seg]


# ---------------------------------------------------------------------------
# Telephone channel processing (RBJ biquads, hybrid echo, hiss, hum, grit)
# ---------------------------------------------------------------------------
def biquad(samples, b0, b1, b2, a0, a1, a2):
    b0 /= a0; b1 /= a0; b2 /= a0; a1 /= a0; a2 /= a0
    x1 = x2 = y1 = y2 = 0.0
    out = [0.0] * len(samples)
    for i, x0 in enumerate(samples):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[i] = y0
        x2 = x1; x1 = x0
        y2 = y1; y1 = y0
    return out


def lowpass(samples, f0, q=0.707):
    w0 = TWO_PI * f0 / SR
    c = cos(w0); al = sin(w0) / (2 * q)
    return biquad(samples, (1 - c) / 2, 1 - c, (1 - c) / 2, 1 + al, -2 * c, 1 - al)


def highpass(samples, f0, q=0.707):
    w0 = TWO_PI * f0 / SR
    c = cos(w0); al = sin(w0) / (2 * q)
    return biquad(samples, (1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + al, -2 * c, 1 - al)


def add_echo(samples, ms=55.0, g=0.18):
    d = int(SR * ms / 1000.0)
    out = samples[:]
    for i in range(d, len(samples)):
        out[i] += g * samples[i - d]
    return out


# ---------------------------------------------------------------------------
# Mixing
# ---------------------------------------------------------------------------
def place(master, start_sec, seg, gain=1.0):
    s = int(start_sec * SR)
    L = len(master)
    for k, v in enumerate(seg):
        idx = s + k
        if 0 <= idx < L:
            master[idx] += gain * v


def build():
    rng = random.Random(SEED)

    connect = build_connect()                       # real captured modem audio
    total = CONNECT_AT + len(connect) / SR + 0.8
    master = [0.0] * int(total * SR)

    # --- synthesised front half (tones -- the part that already sounds real) -
    t = 0.0
    place(master, t, dial_tone(1.4));                       t = 1.45
    dial = dtmf(PHONE_NUMBER)
    place(master, t, dial);                                 t = 1.45 + len(dial) / SR + 0.6

    place(master, t, ringback());                           t += 2.0 + 0.9      # ring 1 + gap
    place(master, t, fade(ringback()[: int(0.8 * SR)], ms=15))                   # ring 2 (cut short)
    t_pickup = t + 0.9

    # Answerer picks up: ANSam answer tone
    place(master, t_pickup, ansam(3.2), gain=0.9)

    # Caller answers on originate channel while answer tone still rings (overlap)
    t_v21 = t_pickup + 1.3
    place(master, t_v21, fsk(payload_bits(10, rng), 980, 1180), gain=0.8)
    # Answerer replies on the answer channel
    place(master, t_v21 + 1.6, fsk(payload_bits(8, rng), 1650, 1850), gain=0.8)

    # V.34 line probing
    t_probe = t_v21 + 3.1
    place(master, t_probe, line_probe(), gain=0.85)

    # --- REAL captured connection (replaces the synthesised carrier) ---------
    # Comes in over the probe tail; runs to its own CONNECT/mute -> silence.
    place(master, CONNECT_AT, connect, gain=1.0)
    return master


def process(master):
    n = len(master)

    # Hybrid echo (2-wire/4-wire leakage)
    master = add_echo(master, ms=55, g=0.16)

    # Line hiss + faint mains hum, added pre-filter so they get shaped too
    if LINE_NOISE:
        rng = random.Random(SEED + 99)
        for i in range(n):
            master[i] += (rng.random() * 2 - 1) * 0.006          # hiss
            master[i] += 0.004 * sin(TWO_PI * 60.0 * i / SR)     # 60 Hz hum

    # Telephone band-pass: 300 Hz HPF -> 3400 Hz LPF
    master = highpass(lowpass(master, 3400.0), 300.0)

    # Gentle companding grit (carbon-mic / mu-law flavour)
    master = [math.tanh(1.3 * x) for x in master]

    # Peak-normalise to -1 dBFS
    peak = max(1e-9, max(abs(x) for x in master))
    g = 0.89 / peak
    return [x * g for x in master]


def write_wav(samples, path):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        ints = [int(max(-1.0, min(1.0, x)) * 32767) for x in samples]
        w.writeframes(struct.pack("<%dh" % len(ints), *ints))


def main():
    print(f"Building dial-up call (connect style: {CONNECT_STYLE}, real spandsp capture)...")
    master = build()
    print(f"  rendered {len(master) / SR:.1f} s @ {SR} Hz, applying telephone channel...")
    out = process(master)
    write_wav(out, OUT)
    print(f"  wrote {OUT}  ({len(out) / SR:.1f} s, {len(out) * 2} bytes PCM)")


if __name__ == "__main__":
    main()
