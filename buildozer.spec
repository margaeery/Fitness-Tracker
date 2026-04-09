[app]

title = FitnessTracker
package.name = FitnessTracker
package.domain = org.test
version = 0.0.8

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_exts = spec,db

icon.filename = %(source.dir)s/images/icons8-кеды-60.png
presplash.filename = %(source.dir)s/images/filename.png
android.presplash_color = #FFFFFF

log_level = 2

android.api = 34
android.minapi = 26
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True

requirements = python3,kivy,android,plyer

orientation = portrait

android.gradle_dependencies = androidx.health.connect:connect-client:1.0.0-alpha11

android.permissions = ACTIVITY_RECOGNITION,POST_NOTIFICATIONS,FOREGROUND_SERVICE,WAKE_LOCK,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,android.permission.health.READ_STEPS,android.permission.health.READ_DISTANCE,android.permission.health.READ_TOTAL_CALORIES_BURNED

osx.python_version = 3
osx.kivy_version = 2.2.0

fullscreen = 0

p4a.source =
p4a.branch = master
allow_root = true

services = Stepservice:service.py:foreground


