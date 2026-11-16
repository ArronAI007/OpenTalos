#define MyAppName "OpenTalos"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyAppArch
  #define MyAppArch "x86_64"
#endif
#define MyAppPublisher "OpenTalos"
#define MyAppExeName "OpenTalos.exe"

[Setup]
AppId={{A0E8D2A4-26D3-4F55-9F12-3A21C56632AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\OpenTalos
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\releases
OutputBaseFilename=OpenTalos-{#MyAppVersion}-windows-{#MyAppArch}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\..\assets\icon\opentalos.ico
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\..\dist\OpenTalos\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OpenTalos"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\OpenTalos"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch OpenTalos"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('Remove OpenTalos user data, plugins, media, and local databases?', mbConfirmation, MB_YESNO) = IDYES then
      Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--uninstall --purge --yes', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
    else
      Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--uninstall --keep-data --yes', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
