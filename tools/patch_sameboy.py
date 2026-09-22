#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "SameBoy")
path = root / "libretro" / "libretro.c"
src = path.read_text()

def replace_once(old, new, label):
    global src
    if old not in src:
        raise SystemExit(f"Patch anchor not found: {label}")
    src = src.replace(old, new, 1)

replace_once(
    '#include <Core/gb.h>\n',
    '#include <Core/gb.h>\n#include <Core/memory.h>\n',
    'memory include',
)

replace_once(
    '#define MAX_VIDEO_PIXELS (MAX_VIDEO_WIDTH * MAX_VIDEO_HEIGHT)\n',
    '''#define MAX_VIDEO_PIXELS (MAX_VIDEO_WIDTH * MAX_VIDEO_HEIGHT)

#define PINBALL_BOARD_WIDTH 160
#define PINBALL_SCREEN_HEIGHT 144
#define PINBALL_STAGE_Y_OFFSET 136
#define PINBALL_BOARD_HEIGHT (PINBALL_SCREEN_HEIGHT + PINBALL_STAGE_Y_OFFSET)
#define POKEMON_PINBALL_STAGE_ADDR 0xD4AC
''',
    'video constants',
)

replace_once(
    '''static uint32_t *frame_buf = NULL;
static uint32_t *frame_buf_copy = NULL;
static uint32_t retained_frame_1[256 * 224];
''',
    '''static uint32_t *frame_buf = NULL;
static uint32_t *frame_buf_copy = NULL;

/*
 * Pokemon Pinball full-table prototype.
 *
 * The game uses two 160x144 stages for each main table. Its own transition
 * routine moves the ball by 0x88 (136) pixels when changing halves, so the
 * reconstructed table is 160x280 with an 8-pixel overlap.
 */
static bool pokemon_pinball_full_table = false;
static uint32_t pokemon_pinball_frame[PINBALL_BOARD_WIDTH * PINBALL_BOARD_HEIGHT];
static int pokemon_pinball_table_id = -1;
static int pokemon_pinball_last_stage = -1;

static uint32_t retained_frame_1[256 * 224];
''',
    'pinball state',
)

replace_once(
    '    info->library_name     = "SameBoy";\n',
    '    info->library_name     = "SameBoy Pinball Full Table v2.1 No Flash";\n',
    'core name',
)

replace_once(
    '''    else {
        geom.base_width = GB_get_screen_width(&gameboy[0]);
        geom.base_height = GB_get_screen_height(&gameboy[0]);
        geom.aspect_ratio = (double)GB_get_screen_width(&gameboy[0]) / GB_get_screen_height(&gameboy[0]);
    }

    geom.max_width = MAX_VIDEO_WIDTH * emulated_devices;
    geom.max_height = MAX_VIDEO_HEIGHT * emulated_devices;
''',
    '''    else if (pokemon_pinball_full_table) {
        geom.base_width = PINBALL_BOARD_WIDTH;
        geom.base_height = PINBALL_BOARD_HEIGHT;
        geom.aspect_ratio = (double)PINBALL_BOARD_WIDTH / PINBALL_BOARD_HEIGHT;
    }
    else {
        geom.base_width = GB_get_screen_width(&gameboy[0]);
        geom.base_height = GB_get_screen_height(&gameboy[0]);
        geom.aspect_ratio = (double)GB_get_screen_width(&gameboy[0]) / GB_get_screen_height(&gameboy[0]);
    }

    if (pokemon_pinball_full_table && emulated_devices == 1) {
        geom.max_width = PINBALL_BOARD_WIDTH;
        geom.max_height = PINBALL_BOARD_HEIGHT;
    }
    else {
        geom.max_width = MAX_VIDEO_WIDTH * emulated_devices;
        geom.max_height = MAX_VIDEO_HEIGHT * emulated_devices;
    }
''',
    'AV geometry',
)

helper_anchor = '''void retro_reset(void)
{
    check_variables();

    for (int i = 0; i < emulated_devices; i++) {
        init_for_current_model(i);
        GB_reset(&gameboy[i]);
    }
    
    if (emulated_devices == 2) {
        if (GB_get_unmultiplied_clock_rate(&gameboy[0]) != GB_get_unmultiplied_clock_rate(&gameboy[1])) {
            audio_out = AUDIO_OUT_GB_1;
        }
    }
    else {
        audio_out = AUDIO_OUT_GB_1;
    }

    geometry_updated = true;
}

void retro_run(void)
'''

helper_replacement = '''void retro_reset(void)
{
    check_variables();

    for (int i = 0; i < emulated_devices; i++) {
        init_for_current_model(i);
        GB_reset(&gameboy[i]);
    }
    
    if (emulated_devices == 2) {
        if (GB_get_unmultiplied_clock_rate(&gameboy[0]) != GB_get_unmultiplied_clock_rate(&gameboy[1])) {
            audio_out = AUDIO_OUT_GB_1;
        }
    }
    else {
        audio_out = AUDIO_OUT_GB_1;
    }

    if (pokemon_pinball_full_table) {
        memset(pokemon_pinball_frame, 0, sizeof(pokemon_pinball_frame));
        pokemon_pinball_table_id = -1;
        pokemon_pinball_last_stage = -1;
    }

    geometry_updated = true;
}

static void pokemon_pinball_video_refresh(void)
{
    const unsigned width = GB_get_screen_width(&gameboy[0]);
    const unsigned height = GB_get_screen_height(&gameboy[0]);

    if (!pokemon_pinball_full_table ||
        width != PINBALL_BOARD_WIDTH ||
        height != PINBALL_SCREEN_HEIGHT) {
        video_cb(frame_buf, width, height, width * sizeof(uint32_t));
        return;
    }

    const uint8_t stage = GB_safe_read_memory(&gameboy[0], POKEMON_PINBALL_STAGE_ADDR);
    int table_id = -1;
    unsigned y_offset = 0;

    switch (stage) {
        case 0x00: /* Red Field Top */
            table_id = 0;
            y_offset = 0;
            break;
        case 0x01: /* Red Field Bottom */
            table_id = 0;
            y_offset = PINBALL_STAGE_Y_OFFSET;
            break;
        case 0x04: /* Blue Field Top */
            table_id = 1;
            y_offset = 0;
            break;
        case 0x05: /* Blue Field Bottom */
            table_id = 1;
            y_offset = PINBALL_STAGE_Y_OFFSET;
            break;
        default:
            /*
             * Bonus/non-field stage: keep the 160x280 output geometry stable
             * and center the normal 160x144 frame.
             */
            memset(pokemon_pinball_frame, 0, sizeof(pokemon_pinball_frame));
            y_offset = (PINBALL_BOARD_HEIGHT - PINBALL_SCREEN_HEIGHT) / 2;
            for (unsigned y = 0; y < PINBALL_SCREEN_HEIGHT; y++) {
                memcpy(pokemon_pinball_frame + (y + y_offset) * PINBALL_BOARD_WIDTH,
                       frame_buf + y * PINBALL_BOARD_WIDTH,
                       PINBALL_BOARD_WIDTH * sizeof(uint32_t));
            }
            pokemon_pinball_table_id = -1;
            video_cb(pokemon_pinball_frame,
                     PINBALL_BOARD_WIDTH,
                     PINBALL_BOARD_HEIGHT,
                     PINBALL_BOARD_WIDTH * sizeof(uint32_t));
            return;
    }

    if (table_id != pokemon_pinball_table_id) {
        memset(pokemon_pinball_frame, 0, sizeof(pokemon_pinball_frame));
        pokemon_pinball_table_id = table_id;
        pokemon_pinball_last_stage = -1;
    }

    /*
     * Pokemon Pinball intentionally outputs one blank/white frame while
     * FieldVerticalTransition swaps stage VRAM. Since our full-table buffer
     * already contains the previous field image, hold that composite for the
     * first frame after a top<->bottom stage change. The emulated game still
     * performs its normal transition internally; we only suppress the flash
     * in the video presented to RetroArch.
     */
    if (pokemon_pinball_last_stage >= 0 &&
        stage != pokemon_pinball_last_stage) {
        pokemon_pinball_last_stage = stage;
        video_cb(pokemon_pinball_frame,
                 PINBALL_BOARD_WIDTH,
                 PINBALL_BOARD_HEIGHT,
                 PINBALL_BOARD_WIDTH * sizeof(uint32_t));
        return;
    }

    pokemon_pinball_last_stage = stage;

    /*
     * The original game can blank the display before wCurrentStage changes.
     * Catch those transition frames directly: if >98% of the 160x144 source
     * frame is the exact same pixel, treat it as a blank maintenance frame and
     * keep showing our already-built composite instead.
     */
    const uint32_t blank_color = frame_buf[0];
    unsigned uniform_pixels = 0;
    const unsigned total_pixels = PINBALL_BOARD_WIDTH * PINBALL_SCREEN_HEIGHT;
    for (unsigned i = 0; i < total_pixels; i++) {
        if (frame_buf[i] == blank_color) {
            uniform_pixels++;
        }
    }
    if (uniform_pixels * 100 >= total_pixels * 98) {
        video_cb(pokemon_pinball_frame,
                 PINBALL_BOARD_WIDTH,
                 PINBALL_BOARD_HEIGHT,
                 PINBALL_BOARD_WIDTH * sizeof(uint32_t));
        return;
    }

    for (unsigned y = 0; y < PINBALL_SCREEN_HEIGHT; y++) {
        memcpy(pokemon_pinball_frame + (y + y_offset) * PINBALL_BOARD_WIDTH,
               frame_buf + y * PINBALL_BOARD_WIDTH,
               PINBALL_BOARD_WIDTH * sizeof(uint32_t));
    }

    video_cb(pokemon_pinball_frame,
             PINBALL_BOARD_WIDTH,
             PINBALL_BOARD_HEIGHT,
             PINBALL_BOARD_WIDTH * sizeof(uint32_t));
}

void retro_run(void)
'''

replace_once(helper_anchor, helper_replacement, 'video helper')

replace_once(
    '''    else {
        video_cb(frame_buf,
                 GB_get_screen_width(&gameboy[0]),
                 GB_get_screen_height(&gameboy[0]),
                 GB_get_screen_width(&gameboy[0]) * sizeof(uint32_t));
    }
''',
    '''    else {
        pokemon_pinball_video_refresh();
    }
''',
    'single-screen refresh',
)

replace_once(
    '''    if (info) {
        content_data = (const uint8_t *)info->data;
        content_size = info->size;
        content_type = check_rom_header(content_data, content_size);
    }

    check_variables();
''',
    '''    if (info) {
        content_data = (const uint8_t *)info->data;
        content_size = info->size;
        content_type = check_rom_header(content_data, content_size);
    }

    pokemon_pinball_full_table = false;
    pokemon_pinball_table_id = -1;
    pokemon_pinball_last_stage = -1;
    memset(pokemon_pinball_frame, 0, sizeof(pokemon_pinball_frame));

    /*
     * Pokemon Pinball's ROM header title is POKEPINBALL.
     * Keep this opt-in so every other GB/GBC game behaves like stock SameBoy.
     */
    if (content_data && content_size >= 0x13F &&
        memcmp(content_data + 0x134, "POKEPINBALL", 11) == 0) {
        pokemon_pinball_full_table = true;
        geometry_updated = true;
        log_cb(RETRO_LOG_INFO, "Pokemon Pinball detected: full-table prototype enabled\\n");
    }

    check_variables();
''',
    'ROM detection',
)

path.write_text(src)
print(f"Patched {path}")
