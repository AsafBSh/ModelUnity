; ============================================================
;  Modelunify - Inno Setup script
;
;  This is OPTIONAL. The .7z portable bundle is already
;  "no-install". This script wraps that same folder in a
;  classic Setup.exe so users get:
;     - a Start Menu shortcut
;     - an optional desktop icon
;     - a proper "Uninstall" entry in Apps & Features
;
;  It installs per-user (no admin needed) into
;  %LocalAppData%\Programs\Modelunify by default, so it
;  works exactly like Cursor / VS Code / Discord installers.
;
;  PREREQUISITES
;  -------------
;  1. Run  .\build_portable.ps1  first to produce
;     dist\Modelunify-<version>-portable\
;  2. Install Inno Setup 6+ from https://jrsoftware.org/isinfo.php
;  3. Open this .iss in the Inno Setup Compiler and hit "Compile",
;     or from PowerShell:
;        & 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' packaging\installer.iss
;  4. The output is  dist\Modelunify-<version>-Setup.exe
; ============================================================

#define MyAppName       "Modelunify"
#define MyAppPublisher  "Modelunify Project"
#define MyAppExeName    "run.bat"
#ifndef MyAppVersion
  #error Use packaging/build_installer.ps1 to pass the version from scripts/_version.py
#endif

#ifndef InstallerName
  #define InstallerName "Modelunify-" + MyAppVersion + "-Setup"
#endif
#ifndef BundleCompression
  #define BundleCompression "lzma2/normal"
#endif

; Source layout (relative to this .iss file)
#ifndef BundleRoot
  #define BundleRoot      "..\dist\Modelunify-" + MyAppVersion + "-portable"
#endif

[Setup]
AppId={{8E2A6F2B-4D1F-4F6E-9C2B-91A2C2F4D6E8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

; --- Per-user install: no admin prompt, no UAC, behaves like Discord/Cursor ---
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\app\assets\logo.png

; --- Output ---
OutputDir=..\dist
OutputBaseFilename={#InstallerName}
Compression={#BundleCompression}
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=2

; --- Wizard look & feel ---
WizardStyle=modern
ShowLanguageDialog=no
SetupIconFile=
; Setup wizard requires 64-bit Windows because we ship 64-bit Python + CUDA wheels.
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "comfy"; Description: "Set up the optional ComfyUI runtime (NVIDIA, internet and multi-GB downloads)"; Flags: unchecked
Name: "comfy\trellis"; Description: "TRELLIS.2"; Flags: exclusive unchecked
Name: "comfy\pixal"; Description: "Pixal3D single image"; Flags: exclusive unchecked
Name: "comfy\pixalmv"; Description: "Pixal3D fixed-orbit multiview"; Flags: exclusive unchecked
Name: "comfy\all"; Description: "All three variants"; Flags: exclusive unchecked
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Pull the ENTIRE portable bundle in. recursesubdirs + createallsubdirs preserves
; the python\, app\, models_cache\ skeleton exactly.
Source: "{#BundleRoot}\*"; DestDir: "{app}"; \
    Excludes: "models_cache\*,app\projects\*,app\.runtime\*,app\.gradio_tmp\*,app\inputs\*,app\outputs\*,app\bms_export\*,app\pretrained_weights\*,app\tools\instalod\inbox\*,app\tools\instalod\outbox\*,*\__pycache__\*"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; IconFilename: "{app}\app\assets\logo.png"
Name: "{group}\Open inputs folder";        Filename: "{app}\Open inputs folder.bat"; \
    WorkingDir: "{app}"
Name: "{group}\Open outputs folder";       Filename: "{app}\Open outputs folder.bat"; \
    WorkingDir: "{app}"
Name: "{group}\Read me";                   Filename: "{app}\README.txt"
Name: "{group}\Uninstall {#MyAppName}";    Filename: "{uninstallexe}"

Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; IconFilename: "{app}\app\assets\logo.png"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\Setup ComfyUI.bat"; Parameters: "trellis"; Description: "Download and set up TRELLIS.2"; WorkingDir: "{app}"; Tasks: comfy\trellis; Flags: postinstall skipifsilent shellexec
Filename: "{app}\Setup ComfyUI.bat"; Parameters: "pixal"; Description: "Download and set up Pixal3D"; WorkingDir: "{app}"; Tasks: comfy\pixal; Flags: postinstall skipifsilent shellexec
Filename: "{app}\Setup ComfyUI.bat"; Parameters: "pixal-mv"; Description: "Download and set up Pixal3D multiview"; WorkingDir: "{app}"; Tasks: comfy\pixalmv; Flags: postinstall skipifsilent shellexec
Filename: "{app}\Setup ComfyUI.bat"; Parameters: "all"; Description: "Download and set up all Comfy 3D variants"; WorkingDir: "{app}"; Tasks: comfy\all; Flags: postinstall skipifsilent shellexec
; Offer to launch immediately on finish (unchecked by default - first run
; downloads 8 GB of weights, user might want to read README first).
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; \
    WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; Preserve user models, inputs, checkpoints and caches on uninstall.
; Only the launcher's disposable temporary files are removed here.
Type: filesandordirs; Name: "{app}\app\.gradio_tmp"

[Code]
function InitializeSetup(): Boolean;
var
  WinVersion: TWindowsVersion;
begin
  GetWindowsVersionEx(WinVersion);
  if WinVersion.Major < 10 then
  begin
    MsgBox('Modelunify requires Windows 10 or newer.', mbError, MB_OK);
    Result := False;
    exit;
  end;
  Result := True;
end;
