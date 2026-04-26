#!/bin/bash
# apply_patches.sh — Применяет патчи Health Connect к шаблонам python-for-android.
#
# Модификации:
#   1. AndroidManifest.tmpl.xml — HC intent-filters, foregroundServiceType="health", <queries>
#   2. build.tmpl.gradle — исключение дублирующихся kotlin-stdlib-jdk7/jdk8
#
# Патчи идемпотентны: повторный вызов безопасен.
set -e

BUILDOZER_DIR="${BUILDOZER_DIR:-$HOME/.buildozer}"
PATCHES_DIR="$(cd "$(dirname "$0")/../patches" && pwd)"

# Пути к шаблонам p4a
P4A_SDL2_TEMPLATES="$BUILDOZER_DIR/android/platform/python-for-android/pythonforandroid/bootstraps/sdl2/build/templates"
P4A_COMMON_TEMPLATES="$BUILDOZER_DIR/android/platform/python-for-android/pythonforandroid/bootstraps/common/build/templates"

# Пути к копиям шаблонов в области сборки
BOOTSTRAP_TEMPLATES="$BUILDOZER_DIR/android/platform/build-arm64-v8a/build/bootstrap_builds/sdl2/templates"

# Dist (генерируется из шаблонов — удаляем для пересоздания)
DIST_DIR="$BUILDOZER_DIR/android/platform/build-arm64-v8a/dists/FitnessTracker"

PATCHED=0

# --- 1. AndroidManifest.tmpl.xml ---
if [ -f "$PATCHES_DIR/AndroidManifest.tmpl.xml" ]; then
    for dest in "$P4A_SDL2_TEMPLATES" "$BOOTSTRAP_TEMPLATES"; do
        if [ -d "$dest" ]; then
            cp "$PATCHES_DIR/AndroidManifest.tmpl.xml" "$dest/AndroidManifest.tmpl.xml"
            echo "[patch] AndroidManifest.tmpl.xml -> $dest"
            PATCHED=1
        fi
    done
fi

# --- 2. build.tmpl.gradle ---
if [ -f "$PATCHES_DIR/build.tmpl.gradle" ]; then
    for dest in "$P4A_COMMON_TEMPLATES" "$BOOTSTRAP_TEMPLATES"; do
        if [ -d "$dest" ]; then
            cp "$PATCHES_DIR/build.tmpl.gradle" "$dest/build.tmpl.gradle"
            echo "[patch] build.tmpl.gradle -> $dest"
            PATCHED=1
        fi
    done
fi

# --- 3. Удаляем dist, чтобы buildozer пересоздал его из пропатченных шаблонов ---
if [ "$PATCHED" -eq 1 ] && [ -d "$DIST_DIR" ]; then
    rm -rf "$DIST_DIR"
    echo "[patch] Dist удалён — будет пересоздан при следующей сборке"
fi

echo "=== Патчи применены ==="
