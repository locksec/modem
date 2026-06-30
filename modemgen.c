/*
 * modemgen.c - Capture REAL modem audio with spandsp (the reference telephony
 *              DSP library), so the connection is a genuine modulated signal
 *              rather than synthesis.
 *
 * Modes:
 *   v22  Two V.22bis modems in a software loopback ("dialing into ourself").
 *        A calling modem and an answering modem are cross-connected -- each
 *        one's transmitted audio feeds the other's receiver -- so they really
 *        perform the V.22bis startup handshake and exchange a scrambled bit
 *        stream. We record the SUM of both transmitters: the full-duplex line
 *        a handset hears, with two QAM carriers (1200 Hz calling, 2400 Hz
 *        answering) overlapping. Authentic, but the gentler 2400 bps sound.
 *
 *   v17  One V.17 transmitter at 14400 bps (the same TCM-QAM family as the
 *        high-speed data modems). Its long training sequence is the loud,
 *        aggressive "KSHHHH" hash everyone remembers, resolving to a steady
 *        high-speed carrier. Half-duplex (single carrier).
 *
 *   v29  One V.29 transmitter at 9600 bps. Alternative high-speed carrier.
 *
 * Output: raw signed 16-bit little-endian PCM, mono, 8000 Hz.
 *
 * Build: cc modemgen.c -o modemgen -I/opt/homebrew/include -L/opt/homebrew/lib -lspandsp -lm
 * Run:   ./modemgen <v22|v17|v29> [seconds] [outfile]
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include "spandsp.h"

/* Deterministic pseudo-random payload. The modem scrambler turns this into the
   broadband hash regardless; a fixed seed just keeps runs reproducible. */
static uint32_t lcg_state = 1990u;
static int get_bit(void *user_data)
{
    (void) user_data;
    lcg_state = lcg_state * 1664525u + 1013904223u;
    return (lcg_state >> 31) & 1;
}
static void put_bit(void *user_data, int bit) { (void) user_data; (void) bit; }

static FILE *out;
static void emit(const int16_t *buf, int n) { fwrite(buf, sizeof(int16_t), n, out); }

/* --- V.22bis full-duplex loopback ------------------------------------------ */
static int run_v22(int total)
{
    v22bis_state_t *caller = v22bis_init(NULL, 2400, 0, 1, get_bit, NULL, put_bit, NULL);
    v22bis_state_t *answer = v22bis_init(NULL, 2400, 0, 0, get_bit, NULL, put_bit, NULL);
    if (!caller || !answer) return -1;
    int16_t cbuf[160], abuf[160], line[160];
    int done = 0;
    while (done < total) {
        int n = (total - done < 160) ? total - done : 160;
        memset(cbuf, 0, sizeof(cbuf));
        memset(abuf, 0, sizeof(abuf));
        v22bis_tx(caller, cbuf, n);
        v22bis_tx(answer, abuf, n);
        for (int i = 0; i < n; i++) {
            int v = (int)cbuf[i] + (int)abuf[i];
            if (v > 32767) v = 32767;
            if (v < -32768) v = -32768;
            line[i] = (int16_t)v;
        }
        v22bis_rx(caller, abuf, n);   /* each modem hears the other -> trains */
        v22bis_rx(answer, cbuf, n);
        emit(line, n);
        done += n;
    }
    return 0;
}

/* --- V.17 / V.29 single high-speed carrier --------------------------------- */
static int run_v17(int total, int bit_rate)
{
    v17_tx_state_t *tx = v17_tx_init(NULL, bit_rate, 0, get_bit, NULL);
    if (!tx) return -1;
    int16_t buf[160];
    int done = 0;
    while (done < total) {
        int n = (total - done < 160) ? total - done : 160;
        memset(buf, 0, sizeof(buf));
        v17_tx(tx, buf, n);
        emit(buf, n);
        done += n;
    }
    return 0;
}

static int run_v29(int total, int bit_rate)
{
    v29_tx_state_t *tx = v29_tx_init(NULL, bit_rate, 0, get_bit, NULL);
    if (!tx) return -1;
    int16_t buf[160];
    int done = 0;
    while (done < total) {
        int n = (total - done < 160) ? total - done : 160;
        memset(buf, 0, sizeof(buf));
        v29_tx(tx, buf, n);
        emit(buf, n);
        done += n;
    }
    return 0;
}

int main(int argc, char **argv)
{
    const char *mode = (argc > 1) ? argv[1] : "v22";
    double seconds   = (argc > 2) ? atof(argv[2]) : 9.0;
    const char *path = (argc > 3) ? argv[3] : "connect.raw";
    int total = (int)(seconds * 8000.0);

    out = fopen(path, "wb");
    if (!out) { perror("fopen"); return 1; }

    int rc;
    if      (strcmp(mode, "v22") == 0) rc = run_v22(total);
    else if (strcmp(mode, "v17") == 0) rc = run_v17(total, 14400);
    else if (strcmp(mode, "v29") == 0) rc = run_v29(total, 9600);
    else { fprintf(stderr, "unknown mode '%s' (use v22|v17|v29)\n", mode); fclose(out); return 1; }

    fclose(out);
    if (rc) { fprintf(stderr, "modem init failed for mode %s\n", mode); return 1; }
    fprintf(stderr, "mode=%s wrote %d samples (%.1f s @ 8000 Hz) -> %s\n", mode, total, seconds, path);
    return 0;
}
