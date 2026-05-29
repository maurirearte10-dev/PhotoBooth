; Inno Setup — PhotoBooth
; Instalador profesional para PhotoBooth de Pampa Guazú

#define MyAppName "PhotoBooth"
#define MyAppVersion "1.0.22"
#define MyAppPublisher "Pampa Guazú"
#define MyAppURL "https://pampaguazu.com.ar"
#define MyAppExeName "PhotoBooth.exe"

[Setup]
AppId={{B2D4F6A8-3C5E-7A9B-1D2F-4E6A8C0B2D4F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installers
OutputBaseFilename=PhotoBooth_Setup
SetupIconFile=assets\photobooth.ico
UninstallDisplayIcon={app}\assets\photobooth.ico
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=force
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Files]
Source: "dist\PhotoBooth\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  TempDir: String;
  SR: TFindRec;
begin
  Exec('taskkill', '/F /IM PhotoBooth.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);

  TempDir := GetEnv('TEMP');
  if FindFirst(TempDir + '\_MEI*', SR) then begin
    try
      repeat
        if (SR.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          DelTree(TempDir + '\' + SR.Name, True, True, True);
      until not FindNext(SR);
    finally
      FindClose(SR);
    end;
  end;

  Result := True;
end;

function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill', '/F /IM PhotoBooth.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1000);
  Result := True;
end;

procedure SHChangeNotify(wEventId: Integer; uFlags: Cardinal; dwItem1: Integer; dwItem2: Integer);
  external 'SHChangeNotify@shell32.dll stdcall';

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
    // Forzar refresh del cache de íconos de Windows tras instalar
    SHChangeNotify($8000000, $1000, 0, 0);
end;
