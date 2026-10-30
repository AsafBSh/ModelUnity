================================================================
  Modelunify - Portable Edition
  Local 3D AI creation; Falcon BMS is the primary workflow
================================================================

WHAT THIS IS
------------
This file describes a separately built portable edition. A source release ZIP
contains no embedded runtime; follow docs/INSTALLATION.md instead.

A self-contained build of Modelunify. Nothing is installed on
your system. The whole folder is portable: copy it to another
drive, another machine, or a USB stick and validate the included checks before relying on it.
After moving installed weights, use Models to register and verify their new
locations before inference. Existing model records retain their original paths.

OPTIONAL TRELLIS.2 / PIXAL3D
--------------------------
Open Models to install/verify the ComfyUI runtime and selected models as tracked
jobs. "Setup ComfyUI.bat" remains an advanced alternative. Setup checks free disk
and the NVIDIA driver before downloading the separate runtime and weights.
It may install private PSF-signed Python into app\.runtime\comfyui without
changing PATH or your default Python. Internet, multi-GB disk space and an
R580-or-newer driver family plus a successful CUDA probe are required for this
CUDA 13 runtime. This is separate from the base app's CUDA 12.4 requirements.
Normal Generate never installs this runtime. Read app\docs\COMFYUI.md.

REQUIREMENTS
------------
  - Windows 10 / 11 x64
  - NVIDIA CUDA GPU for supported AI workflows; memory needs vary by model
    and settings. Existing-mesh CPU tools need no NVIDIA GPU.
  - NVIDIA driver 555.x or newer
  - Enough disk space for the runtime, selected models, shared dependencies
    and working files. Review model sizes and available space in Models.
  - Internet access when explicitly installing or updating models
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
  5. Open Models. Choose storage, install the required checkpoints and verify
     runtime prerequisites before generating meshes.

The desktop launcher exits after opening the window; closing that window
does not stop the background server. For a foreground server you can stop
with Ctrl+C, run from this folder:
  run.bat --server --port 7862
Use foreground mode when no server is running for this installation.

MODELS AND DOWNLOADS
--------------------
Cold library imports can make first launch slow; they do not download weights.
Open Models to install, verify, repair, update or review removal. Follow real
bytes, speed and ETA during transfers; Cancel and Retry / resume retain partial
files when supported by the source. Runtime installation reports its live log.
New weights default to app\pretrained_weights\managed; a selected storage folder
overrides that destination for new jobs. Generation reports missing models
without downloading them. Back up projects, inputs, outputs, bms_export and
models before deleting a bundle. See app\docs\MODEL_WEIGHTS.md.

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
  app\pretrained_weights\managed\ default managed weights
  app\.runtime\model_manager\   model inventory, download jobs and logs
  models_cache\                 legacy library caches (not managed downloads)

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
    Read app\.runtime\workbench_preview\server.log for its actual URL and
    startup errors. Ports begin at 7861 and can change if already occupied.

UNINSTALLING
------------
Back up your inputs, outputs and BMS exports before deleting the folder.
The optional installer preserves generated user data and caches on uninstall.

CREDITS
-------
See app\README.md for the full credits + model licenses
(TripoSG, Hunyuan3D-2 / 2.1, RMBG-1.4, rembg).
