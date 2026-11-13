[app]

title = GraphML Explorer
package.name = graphmlexplorer
package.domain = org.graphml

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt,graphml
source.exclude_dirs = tests,bin,.git,.venv,venv,__pycache__,output,build,dist

version = 0.1

requirements = python3,kivy==2.3.0,networkx==3.3,pyjnius

orientation = portrait, landscape, portrait-reverse, landscape-reverse
fullscreen = 0

android.permissions = READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True
android.release_artifact = apk

[buildozer]

log_level = 2
warn_on_root = 1