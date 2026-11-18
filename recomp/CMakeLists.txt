cmake_minimum_required(VERSION 3.19)
project(AdvancedDaisenryakuRecomp VERSION 0.1.0 LANGUAGES C CXX)

# Native port of Advanced Daisenryaku via segagenesisrecomp.
# Template: RocketKnightAdventuresRecomp/CMakeLists.txt (without launcher UI, widescreen, release packaging).
# Invoked via tools/build.sh (reads config.env, sets GENESIS_RECOMP_ROOT).

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)   # Apple clang otherwise defaults to C++98 (ymfm needs C++11+)

set(GENESIS_RECOMP_ROOT "" CACHE PATH "segagenesisrecomp checkout (sibling folder)")
if(NOT GENESIS_RECOMP_ROOT OR NOT EXISTS "${GENESIS_RECOMP_ROOT}/runner/main.c")
    message(FATAL_ERROR "GENESIS_RECOMP_ROOT does not point to segagenesisrecomp: '${GENESIS_RECOMP_ROOT}'")
endif()
set(RECOMP_ROOT "${GENESIS_RECOMP_ROOT}")
set(RUNNER_ROOT "${RECOMP_ROOT}/runner")

# SDL2 (macOS: Homebrew; Windows: the SDL2 VC package bundled in the framework,
# runner/external/SDL2/SDL2-2.28.5 – headers under include/SDL2, x64 SDL2.dll)
if(WIN32)
    file(GLOB _bundled_sdl2 LIST_DIRECTORIES true "${RUNNER_ROOT}/external/SDL2/SDL2-*")
    list(APPEND CMAKE_PREFIX_PATH ${_bundled_sdl2})
elseif(APPLE)
    find_program(BREW_EXECUTABLE brew)
    if(BREW_EXECUTABLE)
        execute_process(COMMAND "${BREW_EXECUTABLE}" --prefix sdl2
            OUTPUT_VARIABLE _brew_sdl2 OUTPUT_STRIP_TRAILING_WHITESPACE
            ERROR_QUIET RESULT_VARIABLE _brew_rc)
        if(_brew_rc EQUAL 0 AND _brew_sdl2)
            list(APPEND CMAKE_PREFIX_PATH "${_brew_sdl2}")
        endif()
    endif()
endif()
find_package(SDL2 REQUIRED)
# The runner includes <SDL2/SDL.h> → the parent directory of .../include/SDL2 is needed too
set(SDL2_PARENT_INCLUDE_DIRS "")
foreach(_inc IN LISTS SDL2_INCLUDE_DIRS)
    get_filename_component(_name "${_inc}" NAME)
    if(_name STREQUAL "SDL2")
        get_filename_component(_parent "${_inc}" DIRECTORY)
        list(APPEND SDL2_PARENT_INCLUDE_DIRS "${_parent}")
    endif()
endforeach()

# Windows: the C runtime linked in statically, so players need no Visual C++ Redistributable
# (set before the framework adds its targets, so every library uses the same runtime).
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

option(GEN_ENABLE_TRACE "TCP debug server + observation rings" ON)
option(SONIC_REVERSE_DEBUG "reverse debug instrumentation (WRAM store ring)" ON)

include("${RECOMP_ROOT}/cmake/GenesisRecompGenerated.cmake")   # also includes GenesisRecompRunner.cmake

# ROM variant: jp (original), en (Nebelwurfer patch, only data changed) or tr (our translation,
# 3 MiB, generated from jp). tools/build.sh sets all three values.
set(AD_ROM_VARIANT "jp" CACHE STRING "ROM variant (jp|en|tr)")
set_property(CACHE AD_ROM_VARIANT PROPERTY STRINGS jp en tr)
set(AD_ROM_CRC32 "" CACHE STRING "CRC32 of the ROM variant (0x…)")
set(AD_ROM_SIZE "0x100000" CACHE STRING "ROM size in bytes (0x…)")
if(NOT AD_ROM_VARIANT MATCHES "^(jp|en|tr)$" OR NOT AD_ROM_CRC32 MATCHES "^0x[0-9A-Fa-f]+$"
   OR NOT AD_ROM_SIZE MATCHES "^0x[0-9A-Fa-f]+$")
    message(FATAL_ERROR "set AD_ROM_VARIANT (jp|en|tr), AD_ROM_CRC32 and AD_ROM_SIZE (0x…) – invoke via tools/build.sh")
endif()
message(STATUS "ROM variant: ${AD_ROM_VARIANT} (CRC32 ${AD_ROM_CRC32}, ${AD_ROM_SIZE} bytes)")

set(GAME_DIR "${CMAKE_CURRENT_SOURCE_DIR}/game")
# The ROM is a symlink game/ad-<variant>.bin (created by tools/build.sh, excluded via .gitignore).
genesisrecomp_add_generated_sources(GENERATED_SOURCES ad "${GAME_DIR}" "ad-${AD_ROM_VARIANT}.bin"
    REVERSE_DEBUG "${SONIC_REVERSE_DEBUG}")
genesisrecomp_runner_sources(RUNNER_SOURCES
    TRACE "${GEN_ENABLE_TRACE}" REVERSE_DEBUG "${SONIC_REVERSE_DEBUG}")

add_executable(ADRecomp ${RUNNER_SOURCES} ${GENERATED_SOURCES} "${GAME_DIR}/ad_spec.c" "${GAME_DIR}/ad_mapzoom.c" "${GAME_DIR}/ad_record.c" "${GAME_DIR}/ad_lang.c" "${GAME_DIR}/ad_frame.c" "${GAME_DIR}/ad_restart.c")
add_dependencies(ADRecomp ${GENERATED_SOURCES_TARGET})
target_compile_definitions(ADRecomp PRIVATE
    INCLUDE_GENERATED_CODE=1 ENABLE_RECOMPILED_CODE=1 OWN_BACKEND=1
    DEFAULT_DEBUG_PORT=4392
    AD_ROM_CRC32=${AD_ROM_CRC32}u
    AD_ROM_SIZE=${AD_ROM_SIZE}u
    AD_ROM_VARIANT_EN=$<STREQUAL:${AD_ROM_VARIANT},en>
    AD_ROM_VARIANT_TR=$<STREQUAL:${AD_ROM_VARIANT},tr>
    $<$<BOOL:${GEN_ENABLE_TRACE}>:GEN_ENABLE_TRACE=1>
    $<$<BOOL:${SONIC_REVERSE_DEBUG}>:SONIC_REVERSE_DEBUG=1>)
target_include_directories(ADRecomp PRIVATE
    "${RUNNER_ROOT}" "${RUNNER_ROOT}/include" "${RUNNER_ROOT}/video"
    "${RUNNER_ROOT}/external/ymfm/src"
    "${RUNNER_ROOT}/external/superzazu"
    "${RUNNER_ROOT}/external/clowncommon"
    "${RECOMP_ROOT}/recompiler/src"
    "${GAME_DIR}"
    ${SDL2_INCLUDE_DIRS} ${SDL2_PARENT_INCLUDE_DIRS})
target_link_libraries(ADRecomp PRIVATE SDL2::SDL2main SDL2::SDL2)
genesisrecomp_runner_target(ADRecomp)

if(MSVC)
    # Sources are UTF-8 (comments, the language block's strings); fopen/getenv/strncpy are fine here.
    target_compile_options(ADRecomp PRIVATE /utf-8 /bigobj)
    target_compile_definitions(ADRecomp PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()
if(WIN32)
    # SDL2.dll next to ADRecomp.exe, so the game starts from the build folder (docs/notes/windows.md).
    add_custom_command(TARGET ADRecomp POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:SDL2::SDL2>" "$<TARGET_FILE_DIR:ADRecomp>")
    # UTF-8 process code page: paths with non-ASCII letters (user name in %APPDATA%).
    set(AD_WIN_MANIFEST "${CMAKE_CURRENT_SOURCE_DIR}/../release/windows/utf8.manifest")
    target_sources(ADRecomp PRIVATE "${AD_WIN_MANIFEST}")
    # Launcher for players (packaged as "Advanced Daisenryaku.exe" by tools/release_windows.sh):
    # a GUI program with a plain main(); launcher.rc gives it the icon.
    add_executable(ADLauncher WIN32 "${CMAKE_CURRENT_SOURCE_DIR}/../release/windows/launcher.c"
        "${CMAKE_CURRENT_SOURCE_DIR}/../release/windows/launcher.rc" "${AD_WIN_MANIFEST}")
    target_link_libraries(ADLauncher PRIVATE comdlg32 user32)
    if(MSVC)
        target_link_options(ADLauncher PRIVATE "/ENTRY:mainCRTStartup")
        target_compile_options(ADLauncher PRIVATE /utf-8 /W3)
        target_compile_definitions(ADLauncher PRIVATE _CRT_SECURE_NO_WARNINGS)
    endif()
endif()
