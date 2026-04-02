[app]

title = FitnessTracker
package.name = FitnessTracker
package.domain = org.test
version = 0.0.3

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_exts = spec,db

icon.filename = %(source.dir)s/images/icons8-кеды-60.png
presplash.filename = %(source.dir)s/images/filename.png
android.presplash_color = #FFFFFF

log_level = 2

android.api = 30
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True

requirements = python3,kivy

orientation = portrait

android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

osx.python_version = 3
osx.kivy_version = 2.2.0

fullscreen = 0

p4a.source =
p4a.branch = master
allow_root = true
