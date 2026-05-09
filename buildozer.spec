[app]
title = Warehouse App
package.name = warehouseapp
package.domain = org.warehouse
source.dir = .
source.main = main.py
version = 1.0
requirements = python3,kivy==2.3.0,android,pillow
orientation = portrait
fullscreen = 0
android.permissions = CAMERA,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,INTERNET
android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33
android.accept_sdk_license = True
android.arch = arm64-v8a
source.include_exts = py,otf,ttf
log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
warn_on_root = 1
