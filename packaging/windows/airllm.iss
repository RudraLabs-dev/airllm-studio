; Inno Setup 6 script for the AirLLM Windows installer.
; Built by CI:  iscc /DAppVersion=4.0.0-1 /DNumericVersion=4.0.0.1 /DSourceDir=build\stage /DOutputDir=dist packaging\windows\airllm.iss
;
; Silent install:   AirLLM-<ver>-setup-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/DIR="D:\AirLLM"] [/CURRENTUSER] [/TASKS=""]
; Silent uninstall: "%ProgramFiles%\AirLLM\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

#ifndef AppVersion
  #define AppVersion "0.0.0-0"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\build\stage"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
; Never change AppId: Windows uses it to recognise upgrades of the same product.
AppId={{50300B08-0449-49D6-8548-AEAB8C54BFD5}
AppName=AirLLM
AppVersion={#AppVersion}
AppVerName=AirLLM {#AppVersion}
AppPublisher=RudraLabs
AppPublisherURL=https://github.com/RudraLabs-dev/airllm-studio
AppSupportURL=https://github.com/RudraLabs-dev/airllm-studio/issues
AppUpdatesURL=https://github.com/RudraLabs-dev/airllm-studio/releases
VersionInfoVersion={#NumericVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoDescription=AirLLM installer
VersionInfoCompany=RudraLabs
VersionInfoCopyright=Copyright (C) RudraLabs
VersionInfoProductName=AirLLM Studio
VersionInfoProductTextVersion={#AppVersion}
DefaultDirName={autopf}\AirLLM
DefaultGroupName=AirLLM
DisableProgramGroupPage=yes
SetupIconFile={#SourceDir}\airllm.ico
UninstallDisplayIcon={app}\airllm.ico
LicenseFile={#SourceDir}\LICENSE.txt
OutputDir={#OutputDir}
OutputBaseFilename=AirLLM-{#AppVersion}-setup-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Admin (all users) by default; "/CURRENTUSER" or the dialog allows a per-user install.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ChangesEnvironment=yes
UninstallDisplayName=AirLLM {#AppVersion}
WizardStyle=modern
; ~1.5 GB of mostly binaries: solid LZMA2 on several threads keeps CI time reasonable.
Compression=lzma2/normal
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start AirLLM in the background when I sign in (tray icon, API on port 11435)"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "addtopath"; Description: "Add AirLLM to PATH (airllm, airllm-python, airllm-enable-cuda)"; GroupDescription: "Command line:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AirLLM"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m airllm_studio app"; WorkingDir: "{app}"; IconFilename: "{app}\airllm.ico"; Comment: "Chat with large language models on this computer"
Name: "{autodesktop}\AirLLM"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m airllm_studio app"; WorkingDir: "{app}"; IconFilename: "{app}\airllm.ico"; Tasks: desktopicon
Name: "{autostartup}\AirLLM"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m airllm_studio app --background"; WorkingDir: "{app}"; IconFilename: "{app}\airllm.ico"; Tasks: startup
Name: "{group}\AirLLM Command Prompt"; Filename: "{cmd}"; Parameters: "/k ""{app}\airllm-shell.cmd"""; WorkingDir: "{userdocs}"
Name: "{group}\Uninstall AirLLM"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m airllm_studio app"; WorkingDir: "{app}"; Description: "Open AirLLM"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: "-m airllm_studio stop --quiet"; Flags: runhidden waituntilterminated; RunOnceId: "StopAirLLM"

[UninstallDelete]
; Files created after install: the optional CUDA overlay and runtime .pyc caches.
Type: filesandordirs; Name: "{app}\cuda-site"
Type: filesandordirs; Name: "{app}\cuda-site.new"
Type: filesandordirs; Name: "{app}\python"
Type: dirifempty; Name: "{app}"

[Code]
function EnvRoot: Integer;
begin
  if IsAdminInstallMode then Result := HKEY_LOCAL_MACHINE else Result := HKEY_CURRENT_USER;
end;

function EnvKey: String;
begin
  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else
    Result := 'Environment';
end;

procedure AddToPath(Dir: String);
var
  Paths: String;
begin
  if not RegQueryStringValue(EnvRoot, EnvKey, 'Path', Paths) then Paths := '';
  if Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') > 0 then Exit;
  if (Paths <> '') and (Copy(Paths, Length(Paths), 1) <> ';') then Paths := Paths + ';';
  RegWriteExpandStringValue(EnvRoot, EnvKey, 'Path', Paths + Dir);
end;

procedure RemoveFromPath(Dir: String);
var
  Paths: String;
  P: Integer;
begin
  if not RegQueryStringValue(EnvRoot, EnvKey, 'Path', Paths) then Exit;
  Paths := ';' + Paths + ';';
  P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Paths));
  if P = 0 then Exit;
  Delete(Paths, P, Length(Dir) + 1);
  if Length(Paths) >= 2 then Paths := Copy(Paths, 2, Length(Paths) - 2) else Paths := '';
  RegWriteExpandStringValue(EnvRoot, EnvKey, 'Path', Paths);
end;

// Stop a running AirLLM server (tray app or `airllm serve`) so an upgrade can replace its files.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Py: String;
begin
  Py := ExpandConstant('{app}\python\python.exe');
  if FileExists(Py) then
    Exec(Py, '-m airllm_studio stop --quiet', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    AddToPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
