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

#define PINBALL_SCREEN_WIDTH 160
#define PINBALL_SCREEN_HEIGHT 144
#define PINBALL_MAX_HORIZONTAL_SCROLL 34
#define PINBALL_BOARD_WIDTH (PINBALL_SCREEN_WIDTH + PINBALL_MAX_HORIZONTAL_SCROLL)
#define PINBALL_STAGE_Y_OFFSET 136
#define PINBALL_BOARD_HEIGHT (PINBALL_SCREEN_HEIGHT + PINBALL_STAGE_Y_OFFSET)
#define POKEMON_PINBALL_STAGE_ADDR 0xD4AC
#define POKEMON_PINBALL_SCX_ADDR 0xD7AB
#define POKEMON_PINBALL_BALL_Y_ADDR 0xD4B5
#define PINBALL_TRANSITION_CATCHUP_LIMIT 60
#define POKEMON_PINBALL_LOCAL_COPY_LOOP_ADDR 0x065D
#define POKEMON_PINBALL_LOCAL_COPY_EXIT_ADDR 0x0665
#define POKEMON_PINBALL_FAR_COPY_LOOP_ADDR 0x067E
#define POKEMON_PINBALL_FAR_COPY_EXIT_ADDR 0x0686
#define POKEMON_PINBALL_VIDEO_COPY_LOOP_ADDR 0x06EB
#define POKEMON_PINBALL_VIDEO_COPY_EXIT_ADDR 0x06F3
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
static int pokemon_pinball_transition_from_stage = -1;
static bool pokemon_pinball_transition_pending = false;

static uint32_t retained_frame_1[256 * 224];
''',
    'pinball state',
)

replace_once(
    '    info->library_name     = "SameBoy";\n',
    '    info->library_name     = "SameBoy Pinball Full Table v4.4 Fast Stage Copy";\n',
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
        pokemon_pinball_transition_from_stage = -1;
        pokemon_pinball_transition_pending = false;
    }

    geometry_updated = true;
}

static void pokemon_pinball_video_refresh(void)
{
    const unsigned width = GB_get_screen_width(&gameboy[0]);
    const unsigned height = GB_get_screen_height(&gameboy[0]);

    if (!pokemon_pinball_full_table ||
        width != PINBALL_SCREEN_WIDTH ||
        height != PINBALL_SCREEN_HEIGHT) {
        video_cb(frame_buf, width, height, width * sizeof(uint32_t));
        return;
    }

    const uint8_t stage = GB_safe_read_memory(&gameboy[0], POKEMON_PINBALL_STAGE_ADDR);
    uint8_t scx = GB_safe_read_memory(&gameboy[0], POKEMON_PINBALL_SCX_ADDR);
    if (scx > PINBALL_MAX_HORIZONTAL_SCROLL) {
        scx = PINBALL_MAX_HORIZONTAL_SCROLL;
    }
    const unsigned x_offset = scx;
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
            const unsigned bonus_x_offset = (PINBALL_BOARD_WIDTH - PINBALL_SCREEN_WIDTH) / 2;
            for (unsigned y = 0; y < PINBALL_SCREEN_HEIGHT; y++) {
                memcpy(pokemon_pinball_frame + (y + y_offset) * PINBALL_BOARD_WIDTH + bonus_x_offset,
                       frame_buf + y * PINBALL_SCREEN_WIDTH,
                       PINBALL_SCREEN_WIDTH * sizeof(uint32_t));
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
        pokemon_pinball_transition_from_stage = -1;
        pokemon_pinball_transition_pending = false;
    }

    const unsigned total_pixels = PINBALL_SCREEN_WIDTH * PINBALL_SCREEN_HEIGHT;

    /*
     * The original game blanks the LCD while swapping field VRAM. Suppress
     * those maintenance frames before they ever reach the stitched output.
     */
    const uint32_t blank_color = frame_buf[0];
    unsigned uniform_pixels = 0;
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

    /*
     * wCurrentStage may advance before the completed framebuffer does.
     * Remember the half we came from. While the live source still strongly
     * matches that cached old half, keep the already-stitched board visible.
     * Accept the first genuinely new, non-blank field frame immediately.
     */
    if (pokemon_pinball_last_stage >= 0 &&
        stage != pokemon_pinball_last_stage) {
        pokemon_pinball_transition_from_stage = pokemon_pinball_last_stage;
        pokemon_pinball_transition_pending = true;
        pokemon_pinball_last_stage = stage;
    }
    else if (pokemon_pinball_last_stage < 0) {
        pokemon_pinball_last_stage = stage;
    }

    if (pokemon_pinball_transition_pending &&
        pokemon_pinball_transition_from_stage >= 0) {
        const unsigned old_y_offset =
            (pokemon_pinball_transition_from_stage == 0x01 ||
             pokemon_pinball_transition_from_stage == 0x05)
                ? PINBALL_STAGE_Y_OFFSET : 0;

        unsigned old_half_matches = 0;
        for (unsigned y = 0; y < PINBALL_SCREEN_HEIGHT; y++) {
            const uint32_t *old_row =
                pokemon_pinball_frame +
                (y + old_y_offset) * PINBALL_BOARD_WIDTH +
                x_offset;
            const uint32_t *src_row =
                frame_buf + y * PINBALL_SCREEN_WIDTH;

            for (unsigned x = 0; x < PINBALL_SCREEN_WIDTH; x++) {
                if (src_row[x] == old_row[x]) {
                    old_half_matches++;
                }
            }
        }

        if (old_half_matches * 100 >= total_pixels * 90) {
            video_cb(pokemon_pinball_frame,
                     PINBALL_BOARD_WIDTH,
                     PINBALL_BOARD_HEIGHT,
                     PINBALL_BOARD_WIDTH * sizeof(uint32_t));
            return;
        }

        pokemon_pinball_transition_pending = false;
        pokemon_pinball_transition_from_stage = -1;
    }

    for (unsigned y = 0; y < PINBALL_SCREEN_HEIGHT; y++) {
        memcpy(pokemon_pinball_frame + (y + y_offset) * PINBALL_BOARD_WIDTH + x_offset,
               frame_buf + y * PINBALL_SCREEN_WIDTH,
               PINBALL_SCREEN_WIDTH * sizeof(uint32_t));
    }

    video_cb(pokemon_pinball_frame,
             PINBALL_BOARD_WIDTH,
             PINBALL_BOARD_HEIGHT,
             PINBALL_BOARD_WIDTH * sizeof(uint32_t));
}

static uint16_t pokemon_pinball_ball_y(void)
{
    const uint16_t low =
        GB_safe_read_memory(&gameboy[0], POKEMON_PINBALL_BALL_Y_ADDR);
    const uint16_t high =
        GB_safe_read_memory(&gameboy[0], POKEMON_PINBALL_BALL_Y_ADDR + 1);
    return low | (high << 8);
}
/*
 * Pokemon Pinball's vertical transition disables the LCD and then copies
 * several kilobytes of tiles, tilemaps, palettes, and collision data through
 * three generic byte-at-a-time SM83 loops. With the LCD disabled there is no
 * display frame boundary, so one GB_run_frame() call waits for all of those
 * emulated CPU iterations to finish.
 *
 * Preserve the exact reads and writes, including mapper and VRAM behavior,
 * but perform the loop body on the host when one of those known loops is
 * reached during an LCD-off seam transition. The fetched LD A,[HL+] executes
 * once after this callback, rereading the final source byte so the resulting
 * A, F, HL, DE, and BC registers match the original loop without changing
 * SameBoy's CPU core.
 */
static void pokemon_pinball_fast_copy_callback(GB_gameboy_t *gb,
                                                uint16_t address,
                                                uint8_t opcode)
{
    if (!pokemon_pinball_full_table ||
        gb != &gameboy[0] ||
        opcode != 0x2a || /* LD A,[HL+] */
        (gb->io_registers[GB_IO_LCDC] & GB_LCDC_ENABLE) ||
        gb->bc == 0) {
        return;
    }

    uint16_t exit_address;
    switch (address) {
        case POKEMON_PINBALL_LOCAL_COPY_LOOP_ADDR:
            exit_address = POKEMON_PINBALL_LOCAL_COPY_EXIT_ADDR;
            break;
        case POKEMON_PINBALL_FAR_COPY_LOOP_ADDR:
            exit_address = POKEMON_PINBALL_FAR_COPY_EXIT_ADDR;
            break;
        case POKEMON_PINBALL_VIDEO_COPY_LOOP_ADDR:
            exit_address = POKEMON_PINBALL_VIDEO_COPY_EXIT_ADDR;
            break;
        default:
            return;
    }

    uint16_t source = gb->hl;
    uint16_t destination = gb->de;
    const uint16_t count = gb->bc;

    for (uint32_t i = 0; i < count; i++) {
        const uint8_t value = GB_read_memory(gb, source++);
        GB_write_memory(gb, destination++, value);
    }

    gb->f = GB_ZERO_FLAG;
    gb->hl = source - 1;
    gb->de = destination;
    gb->bc = 0;
    gb->pc = exit_address;
}

static bool pokemon_pinball_near_vertical_seam(uint8_t stage)
{
    const uint8_t ball_y_high =
        GB_safe_read_memory(&gameboy[0], POKEMON_PINBALL_BALL_Y_ADDR + 1);

    return ((stage == 0x00 || stage == 0x04) && ball_y_high >= 0x98) ||
           ((stage == 0x01 || stage == 0x05) && ball_y_high <= 0x20);
}

static bool pokemon_pinball_is_main_field_stage(uint8_t stage)
{
    return stage == 0x00 || stage == 0x01 || stage == 0x04 || stage == 0x05;
}

static bool pokemon_pinball_is_vertical_pair(uint8_t a, uint8_t b)
{
    return (a == 0x00 && b == 0x01) ||
           (a == 0x01 && b == 0x00) ||
           (a == 0x04 && b == 0x05) ||
           (a == 0x05 && b == 0x04);
}

void retro_run(void)
'''

replace_once(helper_anchor, helper_replacement, 'video helper')

replace_once(
    '''    else {
        GB_run_frame(&gameboy[0]);
    }

    if (emulated_devices == 2) {
''',
    '''    else {
        uint8_t pinball_stage_before = 0xff;

        GB_set_execution_callback(&gameboy[0], NULL);
        if (pokemon_pinball_full_table &&
            pokemon_pinball_near_vertical_seam(
                GB_safe_read_memory(&gameboy[0],
                                    POKEMON_PINBALL_STAGE_ADDR))) {
            GB_set_execution_callback(&gameboy[0],
                                      pokemon_pinball_fast_copy_callback);

        }
        if (pokemon_pinball_full_table) {
            pinball_stage_before =
                GB_safe_read_memory(&gameboy[0], POKEMON_PINBALL_STAGE_ADDR);
        }

        GB_run_frame(&gameboy[0]);

        if (pokemon_pinball_full_table) {
            const uint8_t pinball_stage_after =
                GB_safe_read_memory(&gameboy[0], POKEMON_PINBALL_STAGE_ADDR);

            /*
             * The original game can spend multiple display frames with the
             * ball position frozen while it finishes the field swap. Instead
             * of skipping an arbitrary number of frames, consume only those
             * dead frames: stop on the first frame where the 8.8 fixed-point
             * ball Y position changes again. The high limit is only a safety
             * ceiling for unusually long LCD-off stage loads; it is not a
             * fixed skip count. Normal gameplay resumes on the first frame
             * where the real 8.8 ball Y value changes.
             */
            if (pokemon_pinball_is_main_field_stage(pinball_stage_before) &&
                pokemon_pinball_is_main_field_stage(pinball_stage_after) &&
                pokemon_pinball_is_vertical_pair(pinball_stage_before,
                                                  pinball_stage_after)) {
                const uint16_t frozen_ball_y = pokemon_pinball_ball_y();
                for (unsigned catchup = 0;
                     catchup < PINBALL_TRANSITION_CATCHUP_LIMIT;
                     catchup++) {
                    GB_run_frame(&gameboy[0]);
                    if (pokemon_pinball_ball_y() != frozen_ball_y) {
                        break;
                    }
                }
            }
        }
    }

    if (emulated_devices == 2) {
''',
    'condition-based seam catch-up',
)

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
    pokemon_pinball_transition_from_stage = -1;
    pokemon_pinball_transition_pending = false;
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


replace_once(
    '''    for (int i = 0; i < emulated_devices; i++) {
        init_for_current_model(i);
        GB_load_rom_from_buffer(&gameboy[i], content_data, content_size);
    }

    bool achievements = true;
''',
    '''    for (int i = 0; i < emulated_devices; i++) {
        init_for_current_model(i);
        GB_load_rom_from_buffer(&gameboy[i], content_data, content_size);
    }

    /*
     * Pokemon Pinball deliberately blanks the palettes and executes
     * rst $10 (AdvanceFrame) during FieldVerticalTransition. Our full-table
     * renderer no longer needs that maintenance frame. Patch only the unique
     * in-memory instruction sequence:
     *   E0 47 E0 48 E0 49 D7
     * to:
     *   E0 47 E0 48 E0 49 00
     * The user's .gbc file on disk is never modified.
     */
    if (pokemon_pinball_full_table && emulated_devices == 1) {
        size_t rom_size = 0;
        uint8_t *rom = GB_get_direct_access(&gameboy[0],
                                            GB_DIRECT_ACCESS_ROM,
                                            &rom_size,
                                            NULL);
        static const uint8_t transition_wait_pattern[] = {
            0xE0, 0x47, 0xE0, 0x48, 0xE0, 0x49, 0xD7
        };

        size_t match_offset = 0;
        unsigned match_count = 0;
        if (rom && rom_size >= sizeof(transition_wait_pattern)) {
            for (size_t i = 0;
                 i + sizeof(transition_wait_pattern) <= rom_size;
                 i++) {
                if (memcmp(rom + i,
                           transition_wait_pattern,
                           sizeof(transition_wait_pattern)) == 0) {
                    match_offset = i;
                    match_count++;
                }
            }
        }

        if (match_count == 1) {
            rom[match_offset + sizeof(transition_wait_pattern) - 1] = 0x00;
            log_cb(RETRO_LOG_INFO,
                   "Pokemon Pinball: removed transition AdvanceFrame at ROM offset 0x%zx\\n",
                   match_offset);
        }
        else {
            log_cb(RETRO_LOG_WARN,
                   "Pokemon Pinball: transition wait patch skipped (pattern matches: %u)\\n",
                   match_count);
        }
    }

    bool achievements = true;
''',
    'runtime transition wait patch',
)

path.write_text(src)
print(f"Patched {path}")
