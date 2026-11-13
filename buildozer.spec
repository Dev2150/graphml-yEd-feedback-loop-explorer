[app]

title = GraphML Explorer
package.name = graphmlexplorer
package.domain = org.graphml

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt,graphml
source.exclude_dirs = tests,bin,.git,.venv,venv,__pycache__,output,build,dist

version = 0.1

requirements = python3==3.11.9,kivy==2.3.1,networkx==3.3

orientation = portrait, landscape, portrait-reverse, landscape-reverse
fullscreen = 0

android.permissions = READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.python_version = 3.11
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.release_artifact = apk
p4a.branch = release-2024.01.21

[buildozer]

log_level = 2
warn_on_root = 1