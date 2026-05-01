#!/bin/bash
# apply_patches.sh — Применяет патчи Health Connect к шаблонам python-for-android.
#
# Модификации:
#   1. AndroidManifest.tmpl.xml — HC intent-filters, foregroundServiceType="health", <queries>
#   2. build.tmpl.gradle — исключение дублирующихся kotlin-stdlib-jdk7/jdk8
#
# Патчи идемпотентны: повторный вызов безопасен.
set -e

PATCHES_DIR="$(cd "$(dirname "$0")/../patches" && pwd)"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

patch_root() {
    local root="$1"
    local patched=0

    [ -n "$root" ] || return 0
    [ -d "$root" ] || return 0

    local p4a_sdl2_templates="$root/android/platform/python-for-android/pythonforandroid/bootstraps/sdl2/build/templates"
    local p4a_common_templates="$root/android/platform/python-for-android/pythonforandroid/bootstraps/common/build/templates"

    if [ -f "$PATCHES_DIR/AndroidManifest.tmpl.xml" ]; then
        for dest in "$p4a_sdl2_templates" "$root"/android/platform/build-*/build/bootstrap_builds/sdl2/templates; do
            if [ -d "$dest" ]; then
                cp "$PATCHES_DIR/AndroidManifest.tmpl.xml" "$dest/AndroidManifest.tmpl.xml"
                echo "[patch] AndroidManifest.tmpl.xml -> $dest"
                patched=1
            fi
        done
    fi

    if [ -f "$PATCHES_DIR/build.tmpl.gradle" ]; then
        for dest in "$p4a_common_templates" "$root"/android/platform/build-*/build/bootstrap_builds/sdl2/templates; do
            if [ -d "$dest" ]; then
                cp "$PATCHES_DIR/build.tmpl.gradle" "$dest/build.tmpl.gradle"
                echo "[patch] build.tmpl.gradle -> $dest"
                patched=1
            fi
        done
    fi

    if [ "$patched" -eq 1 ]; then
        for dist_dir in "$root"/android/platform/build-*/dists/FitnessTracker; do
            if [ -d "$dist_dir" ]; then
                rm -rf "$dist_dir"
                echo "[patch] Dist удалён — будет пересоздан при следующей сборке: $dist_dir"
            fi
        done
    fi
}

HOME_BUILDOZER_DIR="${BUILDOZER_DIR:-$HOME/.buildozer}"
PROJECT_BUILDOZER_DIR="$PROJECT_DIR/.buildozer"

patch_root "$HOME_BUILDOZER_DIR"
if [ "$PROJECT_BUILDOZER_DIR" != "$HOME_BUILDOZER_DIR" ]; then
    patch_root "$PROJECT_BUILDOZER_DIR"
fi

echo "=== Патчи применены ==="
