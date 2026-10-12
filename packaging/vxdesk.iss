; VxDesk installer — Inno Setup 6 script.
; Build: tools/innosetup/ISCC.exe packaging/vxdesk.iss   (or scripts/build_desktop.py)

#define AppVersion "0.1.0"

[Setup]
AppId={{7F3A2C1E-9B4D-4E5F-A6C7-8D9E0F1A2B3C}
AppName=VxDesk
AppVersion={#AppVersion}
AppVerName=VxDesk {#AppVersion}
AppPublisher=VxDesk
DefaultDirName={localappdata}\Programs\VxDesk
DefaultGroupName=VxDesk
PrivilegesRequired=lowest
OutputDir=..\installer-output
OutputBaseFilename=VxDeskSetup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\VxDesk.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; user data lives in %LOCALAPPDATA%\VxDesk and is NOT touched on uninstall

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\VxDesk\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\VxDesk"; Filename: "{app}\VxDesk.exe"
Name: "{group}\Uninstall VxDesk"; Filename: "{uninstallexe}"
Name: "{autodesktop}\VxDesk"; Filename: "{app}\VxDesk.exe"; Tasks: desktopicon
