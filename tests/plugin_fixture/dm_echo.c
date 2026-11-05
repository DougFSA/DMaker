/* Plugin de teste do DMK-68 (codigo proprio, sem copiar nada de terceiros): um eco com realimentacao.
 * Compila como LADSPA (-DKIND_LADSPA) ou LV2 (-DKIND_LV2). Os tipos abaixo seguem a especificacao publica
 * das duas interfaces.
 *
 * O teste tests/test_plugins_integration.py usa o resultado e pula sem ele. Para montar a pasta que ele pede
 * (DMAKER_TEST_PLUGINS), com o compilador do Visual Studio (x64) ou gcc:
 *   <pasta>/ladspa/dm_echo.dll          cl /LD /O2 /DKIND_LADSPA dm_echo.c /Fe:<pasta>/ladspa/dm_echo.dll
 *   <pasta>/lv2/dm_echo.lv2/dm_echo.dll cl /LD /O2 /DKIND_LV2 dm_echo.c /Fe:<pasta>/lv2/dm_echo.lv2/dm_echo.dll
 *   <pasta>/lv2/dm_echo.lv2/            mais manifest.ttl e dm_echo.ttl desta pasta
 * Os controles: delay_ms (1 a 1000, padrao 250), feedback (0 a 0,95, padrao 0,4) e mix (0 a 1, padrao 0,5); no
 * LADSPA, c0, c1 e c2. */
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

#define MAX_SECONDS 2

typedef struct {
    float *delay_ms, *feedback, *mix, *in, *out;
    float *buffer;
    unsigned long size, pos;
    double rate;
} Echo;

static void *make(double rate) {
    Echo *e = (Echo *)calloc(1, sizeof(Echo));
    e->rate = rate;
    e->size = (unsigned long)(rate * MAX_SECONDS) + 1;
    e->buffer = (float *)calloc(e->size, sizeof(float));
    return e;
}

static void run_echo(Echo *e, unsigned long n) {
    unsigned long delay = (unsigned long)(*e->delay_ms * 0.001 * e->rate);
    if (delay < 1) delay = 1;
    if (delay >= e->size) delay = e->size - 1;
    float fb = *e->feedback, mix = *e->mix;
    for (unsigned long i = 0; i < n; i++) {
        unsigned long read = (e->pos + e->size - delay) % e->size;
        float delayed = e->buffer[read];
        float dry = e->in[i];
        e->buffer[e->pos] = dry + fb * delayed;
        e->out[i] = dry + mix * delayed;
        e->pos = (e->pos + 1) % e->size;
    }
}

static void connect(Echo *e, unsigned long port, void *data) {
    switch (port) {
    case 0: e->delay_ms = (float *)data; break;
    case 1: e->feedback = (float *)data; break;
    case 2: e->mix = (float *)data; break;
    case 3: e->in = (float *)data; break;
    case 4: e->out = (float *)data; break;
    }
}

static void cleanup(Echo *e) {
    free(e->buffer);
    free(e);
}

#ifdef KIND_LADSPA
typedef float LADSPA_Data;
typedef struct { int HintDescriptor; LADSPA_Data LowerBound, UpperBound; } PortHint;
typedef struct Descriptor {
    unsigned long UniqueID;
    const char *Label;
    int Properties;
    const char *Name, *Maker, *Copyright;
    unsigned long PortCount;
    const int *PortDescriptors;
    const char *const *PortNames;
    const PortHint *PortRangeHints;
    void *ImplementationData;
    void *(*instantiate)(const struct Descriptor *, unsigned long);
    void (*connect_port)(void *, unsigned long, LADSPA_Data *);
    void (*activate)(void *);
    void (*run)(void *, unsigned long);
    void (*run_adding)(void *, unsigned long);
    void (*set_run_adding_gain)(void *, LADSPA_Data);
    void (*deactivate)(void *);
    void (*cleanup)(void *);
} Descriptor;

static void *l_inst(const Descriptor *d, unsigned long rate) { (void)d; return make((double)rate); }
static void l_conn(void *h, unsigned long p, LADSPA_Data *d) { connect((Echo *)h, p, d); }
static void l_run(void *h, unsigned long n) { run_echo((Echo *)h, n); }
static void l_clean(void *h) { cleanup((Echo *)h); }

/* INPUT=1 OUTPUT=2 CONTROL=4 AUDIO=8; BOUNDED_BELOW=1 BOUNDED_ABOVE=2 DEFAULT_*: 0x40 min, 0x80 low, 0xC0 mid, 0x100 high, 0x140 max */
static const int ports[5] = {1 | 4, 1 | 4, 1 | 4, 1 | 8, 2 | 8};
static const char *const names[5] = {"Atraso (ms)", "Realimentacao", "Mistura", "Entrada", "Saida"};
static const PortHint hints[5] = {
    {1 | 2 | 0xC0, 1.0f, 1000.0f},
    {1 | 2 | 0x80, 0.0f, 0.95f},
    {1 | 2 | 0xC0, 0.0f, 1.0f},
    {0, 0, 0},
    {0, 0, 0}};
static Descriptor desc = {0x444D0001ul, "dm_echo", 0, "DMaker Eco de teste", "DMaker", "dominio publico", 5, ports,
                          names, hints, 0, l_inst, l_conn, 0, l_run, 0, 0, 0, l_clean};

EXPORT const Descriptor *ladspa_descriptor(unsigned long index) { return index == 0 ? &desc : 0; }
#endif

#ifdef KIND_LV2
typedef struct { const char *URI; void *data; } Feature;
typedef struct Descriptor {
    const char *URI;
    void *(*instantiate)(const struct Descriptor *, double, const char *, const Feature *const *);
    void (*connect_port)(void *, uint32_t, void *);
    void (*activate)(void *);
    void (*run)(void *, uint32_t);
    void (*deactivate)(void *);
    void (*cleanup)(void *);
    const void *(*extension_data)(const char *);
} Descriptor;

static void *v_inst(const Descriptor *d, double rate, const char *b, const Feature *const *f) {
    (void)d; (void)b; (void)f;
    return make(rate);
}
static void v_conn(void *h, uint32_t p, void *d) { connect((Echo *)h, p, d); }
static void v_run(void *h, uint32_t n) { run_echo((Echo *)h, n); }
static void v_clean(void *h) { cleanup((Echo *)h); }
static Descriptor desc = {"urn:dmaker:test:echo", v_inst, v_conn, 0, v_run, 0, v_clean, 0};

EXPORT const Descriptor *lv2_descriptor(uint32_t index) { return index == 0 ? &desc : 0; }
#endif
