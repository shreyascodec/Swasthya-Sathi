; Swasthya Sathi — Windows installer (Inno Setup 6)
;
; Produces a single SwasthyaSathiSetup.exe that:
;   1) Copies the app tree to a per-user, WRITABLE folder (no admin / no UAC).
;   2) Silently installs Python 3.12 per-user IF no Python 3.10+ is present.
;   3) Launches first-run setup (deploy\appliance_setup.py --gui --start),
;      which downloads models/weights, installs Ollama, and starts the app.
;
; Build it via:  powershell -ExecutionPolicy Bypass -File deploy\build_release.ps1
; (that script builds frontend\dist, downloads the bundled Python + Ollama
;  installers into deploy\bundle\, then compiles this .iss with ISCC.)
;
; Inner clinic PCs need NOTHING pre-installed — internet is used only during
; the first run to fetch models; the app runs offline afterward.

#define AppName        "Swasthya Sathi"
#define AppVersion     "1.0.0"
#define AppPublisher   "Swasthya Sathi"
#define AppExeName     "SwasthyaSathi.bat"

[Setup]
; A stable, unique AppId keeps upgrades/uninstall consistent across versions.
AppId={{7B1D9F2A-3C4E-4A6B-9E20-5A7C9B0D1E2F}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\SwasthyaSathi
DefaultGroupName={#AppName}
; Per-user install -> writable folder, no admin prompt (fewest clicks).
PrivilegesRequired=lowest
; Keep the wizard short.
DisableProgramGroupPage=yes
DisableDirPage=yes
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=SwasthyaSathiSetup
UninstallDisplayName={#AppName}
; SetupIconFile=setup.ico   ; add a .ico here later if you have branding

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; --- Application code ------------------------------------------------------
Source: "..\server\*";         DestDir: "{app}\server";        Excludes: "__pycache__\*,*\__pycache__\*,*.pyc"; Flags: recursesubdirs createallsubdirs
Source: "..\core\*";           DestDir: "{app}\core";          Excludes: "__pycache__\*,*\__pycache__\*,*.pyc"; Flags: recursesubdirs createallsubdirs
Source: "..\stages\*";         DestDir: "{app}\stages";        Excludes: "__pycache__\*,*\__pycache__\*,*.pyc"; Flags: recursesubdirs createallsubdirs
; models\ ships the Python model wrappers but NOT the big weights (downloaded on first run).
Source: "..\models\*";         DestDir: "{app}\models";        Excludes: "weights\*,__pycache__\*,*\__pycache__\*,*.pyc"; Flags: recursesubdirs createallsubdirs
; config\ ships defaults but NOT a machine-specific env\local.yaml (written on first run).
Source: "..\config\*";         DestDir: "{app}\config";        Excludes: "env\local.yaml,__pycache__\*,*\__pycache__\*,*.pyc"; Flags: recursesubdirs createallsubdirs
; Prebuilt UI (required; no Node on clinic PCs).
Source: "..\frontend\dist\*";  DestDir: "{app}\frontend\dist"; Flags: recursesubdirs createallsubdirs

; --- Setup engine + launchers ---------------------------------------------
Source: "..\deploy\appliance_setup.py"; DestDir: "{app}\deploy"
Source: "..\deploy\setup_launcher.py";  DestDir: "{app}\deploy"
Source: "..\deploy\__init__.py";        DestDir: "{app}\deploy"
Source: "..\requirements.txt";          DestDir: "{app}"
Source: "..\SwasthyaSathi.bat";         DestDir: "{app}"
Source: "..\setup.bat";                 DestDir: "{app}"
Source: "..\start_kiosk.bat";           DestDir: "{app}"
Source: "..\START_HERE.txt";            DestDir: "{app}"

; --- Bundled offline installer (downloaded by build_release.ps1) -----------
; Python is only run when the target PC lacks Python 3.10+.
; Ollama is NOT bundled (keeps the installer ~1 GB smaller); appliance_setup.py
; installs it via winget / direct download at first run (internet is available
; during install). To ship it offline instead, drop OllamaSetup.exe into
; deploy\bundle\ and add a matching Source line here.
Source: "bundle\python-installer.exe";  DestDir: "{app}\deploy\bundle"; Flags: skipifsourcedoesntexist

[Icons]
Name: "{group}\Swasthya Sathi";          Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall Swasthya Sathi"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Swasthya Sathi";    Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; 1) Ensure Python 3.10+ exists (per-user, silent, no UAC). Only when missing.
Filename: "{app}\deploy\bundle\python-installer.exe"; \
  Parameters: "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_test=0"; \
  StatusMsg: "Installing Python (one time)..."; \
  Check: NeedsPython; Flags: waituntilterminated skipifdoesntexist

; 2) First-run setup + launch. Shows its own progress window (model downloads
;    can take a while), so we don't block the wizard here.
Filename: "{app}\{#AppExeName}"; Description: "Start Swasthya Sathi now"; \
  WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up everything first-run created inside the app folder.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\models\weights"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\_session_data"
Type: files;          Name: "{app}\config\env\local.yaml"

[Code]
function ExecSilent(const Params: String): Integer;
var
  RC: Integer;
begin
  // Run a hidden cmd; return the child process exit code (or -1 on launch failure).
  if not Exec(ExpandConstant('{cmd}'), Params, '', SW_HIDE, ewWaitUntilTerminated, RC) then
    RC := -1;
  Result := RC;
end;

function HasSuitablePython(): Boolean;
begin
  // Python exits 0 only when version >= 3.10. Try the py launcher, then python.
  Result := False;
  if ExecSilent('/C py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"') = 0 then
    Result := True
  else if ExecSilent('/C python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"') = 0 then
    Result := True;
end;

function NeedsPython(): Boolean;
begin
  Result := not HasSuitablePython();
end;
