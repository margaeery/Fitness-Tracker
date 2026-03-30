[app]

title = FintessApp
package.name = myapp
package.domain = org.test
version = 1.0.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_exts = spec

log_level = 2

android.api = 31
android.minapi = 21
android.ndk = 25b
android.arch = arm64-v8a
android.accept_sdk_license = True

requirements = python3,kivy

orientation = portrait

osx.python_version = 3
osx.kivy_version = 2.2.0

fullscreen = 0

p4a.source =
p4a.branch = master
