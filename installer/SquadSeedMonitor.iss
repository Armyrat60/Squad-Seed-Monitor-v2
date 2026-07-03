; Inno Setup script for Squad Seed Monitor.
; Builds a Windows installer that:
;   - installs SquadSeedMonitor.exe to Program Files
;   - ASKS about a desktop shortcut (Select Additional Tasks page)
;   - adds Start Menu entries + an Uninstall entry
;   - registers in "Apps & features" so it can be uninstalled or repaired
;     (re-running the installer reinstalls/repairs the files)
;
; Build locally:  ISCC.exe installer\SquadSeedMonitor.iss   (needs Inno Setup 6)
; The exe must already be built (pyinstaller seedmon.spec -> dist\SquadSeedMonitor.exe).
; Output: dist\SquadSeedMonitor-Setup-<version>.exe

#define MyAppName "Squad Seed Monitor"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Armyrat60"
#define MyAppURL "https://github.com/Armyrat60/Squad-Seed-Monitor-v2"
#define MyAppExeName "SquadSeedMonitor.exe"

[Setup]
; A stable, unique AppId ties installs/upgrades/uninstalls together. Do NOT change it.
AppId={{A7F3C2E1-9B4D-4E6A-8C1F-2D5B7E9A3F14}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\SquadSeedMonitor
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=SquadSeedMonitor-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user data (config/log) lives in %LOCALAPPDATA%\SquadSeedMonitor and is left
; in place on uninstall so favorites survive a reinstall/upgrade.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\SquadSeedMonitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent
