; Paragon PR7-SM installer (Inno Setup 6): a system monitor, the way Process Explorer shows what runs.
;   iscc /DAppVersion=0.1.0 installer\pr7sm.iss      (after pyinstaller pr7sm.spec has made dist\PR7-SM)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-SM, with a Start menu entry. Replace Task Manager is
; an unticked task: it's machine-wide, so it asks for administrator rights (PR7-SM --replace-taskmgr, elevated).
; Uninstalling puts Task Manager back if PR7-SM had replaced it (--uninstall asks for rights only then).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{DA18598E-10B7-4EA2-B221-71F0CFC56AA8}
AppName=Paragon PR7-SM
AppVersion={#AppVersion}
AppVerName=Paragon PR7-SM {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-SM
DefaultGroupName=Paragon PR7-SM
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-SM-Setup-{#AppVersion}
SetupIconFile=..\pr7sm\icons\app.ico
UninstallDisplayIcon={app}\PR7-SM.exe
UninstallDisplayName=Paragon PR7-SM
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "taskmgr"; Description: "Replace Task Manager (Ctrl+Shift+Esc opens PR7-SM; Windows asks for permission)"; GroupDescription: "Windows:"; Flags: unchecked
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-SM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-SM"; Filename: "{app}\PR7-SM.exe"; Comment: "System monitor"
Name: "{autodesktop}\Paragon PR7-SM"; Filename: "{app}\PR7-SM.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-SM.exe"; Parameters: "--replace-taskmgr"; Verb: runas; Flags: shellexec runhidden waituntilterminated; Tasks: taskmgr
Filename: "{app}\PR7-SM.exe"; Description: "{cm:LaunchProgram,Paragon PR7-SM}"; Flags: nowait postinstall skipifsilent
; Updates (Check for updates runs this installer with /SILENT /relaunch=1): start PR7-SM again when done.
Filename: "{app}\PR7-SM.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[UninstallRun]
Filename: "{app}\PR7-SM.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "Uninstall"

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
