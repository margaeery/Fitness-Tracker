#!/bin/bash
# entrypoint.sh — Точка входа Docker-контейнера для сборки APK.
#
# Логика:
#   1. Если патчи уже применены (маркер есть) — сразу собираем.
#   2. Иначе: запускаем buildozer (скачивает SDK/NDK/p4a), применяем патчи, пересобираем.
#
# APK появляется в ./bin/
set -e

cd /home/user/hostcwd

MARKER="$HOME/.buildozer/.patches_applied"

if [ -f "$MARKER" ]; then
    echo "=== Патчи уже применены, собираем APK ==="
    buildozer android debug
else
    echo "=== Первый запуск: скачивание зависимостей ==="
    # Первая сборка скачивает SDK, NDK, p4a и компилирует рецепты.
    # Может упасть на этапе Gradle (Kotlin duplicate classes) — это ожидаемо.
    buildozer android debug 2>&1 || echo "[info] Первая сборка завершилась с ошибкой (ожидаемо)"

    echo "=== Применение патчей Health Connect ==="
    bash scripts/apply_patches.sh
    touch "$MARKER"

    echo "=== Пересборка APK с патчами ==="
    buildozer android debug
fi

echo "=== Готово! APK в каталоге bin/ ==="
ls -lh bin/*.apk 2>/dev/null || echo "(APK не найден — проверьте логи сборки)"
