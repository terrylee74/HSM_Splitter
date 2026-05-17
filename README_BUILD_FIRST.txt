HSM Splitter v7 - Full Build Package

Files included:
- hsm_splitter_app_v7.py
- HSM_Splitter_v7.spec
- build_simple.bat
- apply_branding.py
- apply_branding_simple.bat
- version_info.txt
- brand_config.json
- README_BUILD_FIRST.txt

You must add these files yourself:
- ffmpeg.exe
- ffprobe.exe
- app.ico (optional)

Recommended folder:
D:\HSM_BUILD

How to build:
1. Install Python
2. Put all package files in one folder
3. Put ffmpeg.exe and ffprobe.exe in the same folder
4. Open the folder
5. Type cmd in the address bar
6. Run build_simple.bat
7. Output will be created here:
   dist\HSM_Splitter

Notes:
- If matching MP3 is missing, the app shows a warning and continues with the next CUE.
- Matching rule: same folder + same file name + .mp3 extension
- Output MP3 format is fixed to 44.1kHz / 64kbps / mono
