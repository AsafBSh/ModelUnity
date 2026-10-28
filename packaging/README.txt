================================================================
  Modelunify - Portable Edition
  Local 3D AI creation; Falcon BMS is the primary workflow
================================================================

WHAT THIS IS
------------
A self-contained build of Modelunify. Nothing is installed on
your system. The whole folder is portable: copy it to another
drive, another machine, or a USB stick and validate the included checks before relying on it.

OPTIONAL TRELLIS.2 / PIXAL3D
--------------------------
Run "Setup ComfyUI.bat" and choose the models explicitly. Setup checks free disk
and the NVIDIA driver before downloading a separate ComfyUI runtime and weights.
It may install private PSF-signed Python into app\.runtime\comfyui without
changing PATH or your default Python. Internet, multi-GB disk space and an
R580-or-newer driver family plus a successful CUDA probe are required for this
CUDA 13 runtime. This is separate from the base app's CUDA 12.4 requirements.
Normal Generate never installs this runtime. Read app\docs\COMFYUI.md.

REQUIREMENTS
------------
  - Windows 10 / 11 x64
  - NVIDIA GPU with >= 8 GB VRAM (12 GB recommended)
  - NVIDIA driver 555.x or newer
  - About 25 GB free disk space (5 GB for this folder, ~8 GB for
    model weights downloaded on first run, plus working space)
  - Internet access for uncached model weights when first requested
  - Paint only in builds that explicitly include matching CUDA extensions
    and the external RealESRGAN checkpoint; NVIDIA CUDA required

HOW TO RUN
----------
  1. Make sure the folder is fully extracted (don't run from
     inside the .7z directly).
  2. Double-click   run.bat
  3. ModelUnify opens in its own Edge/Chrome application window.
     Edge or Chrome must already be installed. Local ports start at 7861;
     another installation automatically gets its own available port.
  4. Use run.bat --browser for a browser tab or --legacy for the original UI.
     Closing the window leaves queued jobs/server running. Reopen to reconnect.
  5. Use the web UI to generate 3D meshes.

The desktop launcher exits after opening the window; closing that window
does not stop the background server. For a foreground server you can stop
with Ctrl+C, run from this folder:
  run.bat --server --port 7862
Use foreground mode when no server is running for this installation.

FIRST LAUNCH IS SLOW
--------------------
Uncached models download weights when first requested. Size depends on the
selected model: TripoSG/RMBG uses about 8 GB; Hunyuan shape and PBR paint need
additional caches. Allow additional working space for painting. Downloads live
under app\pretrained_weights\ or models_cache\. After those models are cached,
the operations can run offline. Back up projects, inputs, outputs, bms_export
and caches before deleting a bundle.

WHERE THINGS LIVE
-----------------
  run.bat                       <-- double-click to start
  Open inputs folder.bat        opens app\inputs in Explorer
  Open outputs folder.bat       opens app\outputs in Explorer
  python\                       embedded Python (don't touch)
  app\scripts\                  the source code
  app\tools\                    InstaLOD staging + recipes (manual Studio workflow)
  app\config.yaml               edit if you want to change defaults
  app\inputs\                   drop your source photos here
  app\outputs\                  finished .glb meshes appear here
  app\bms_export\               LODs for external Blender/BMS export
  app\projects\                 saved assets, checkpoints and job artifacts
  app\.runtime\workbench_preview\ queue, logs and private window profile
  models_cache\                 AI weights (created on first run)

INPUT FOLDERS (you can also drag-drop in the UI)
------------------------------------------------
  app\inputs\satellite\         top-down / aerial shots
  app\inputs\ground\            ground-level / oblique photos

OUTPUTS
-------
  app\outputs\           single-model .glb files
  app\bms_export\<name>\ a folder per asset with Model_0..6
                         plus the BMS template files

CONFIG (optional)
-----------------
Open  app\config.yaml  in any text editor to change:
  - Generation step count (quality vs speed)
  - Face counts per LOD
  - Path to your Falcon BMS install (for deploy_bms.py)
  - low_vram_mode (leave true on 12 GB cards)

TROUBLESHOOTING
---------------
* "[FATAL] PyTorch / torchvision build mismatch detected"
    You shouldn't see this in a fresh portable bundle. If you
    do, the bundle is corrupted - re-extract from the .7z.

* Console flashes and disappears immediately
    Either the bundle isn't fully extracted, or your antivirus
    is blocking python.exe. Restore from quarantine and add
    this folder to your AV's allow-list.

* "CUDA out of memory" mid-generation
    Lower octree/render/texture settings in the UI,
    or close other GPU-heavy apps (browser, games, Blender).

* "operator torchvision::nms does not exist"
    Re-extract from the .7z; do not pip install anything into
    the embedded Python.

* The web UI never opens
    Open http://127.0.0.1:7860 manually. If that page is
    blank, check the console for the real error.

UNINSTALLING
------------
Back up your inputs, outputs and BMS exports before deleting the folder.
The optional installer preserves generated user data and caches on uninstall.

CREDITS
-------
See app\README.md for the full credits + model licenses
(TripoSG, Hunyuan3D-2 / 2.1, RMBG-1.4, rembg).
