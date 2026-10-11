; Download Catalog 설치 프로그램 (Inno Setup 6)
; 컴파일: ISCC.exe packaging\installer.iss  (build.ps1이 대신 실행)
#define MyAppName "Download Catalog"
#define MyAppVersion "1.2.4"
#define MyAppExe "DownloadCatalog.exe"
; 앱이 만드는 뮤텍스 이름(single_instance.py의 MUTEX_NAME과 같아야 함). 시험 빌드에서만 /D로 바꾼다.
#ifndef AppMutexName
  #define AppMutexName "DownloadCatalog_SingleInstance"
#endif

[Setup]
AppId={{B7C0A6E2-5F1D-4C7B-9A3E-D0A1C2B3E4F5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Download Catalog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 관리자 권한 없이 현재 사용자용으로 설치(Program Files가 아닌 사용자 폴더)
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=DownloadCatalog-Setup-{#MyAppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 실행 중이면 설치·제거 전에 종료를 안내(앱이 같은 이름의 뮤텍스를 만든다)
AppMutex={#AppMutexName}
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.GroupStart=프로그램 실행 방식:
english.GroupStart=How to start the program:
korean.TaskAutoStart=Windows를 시작할 때 자동으로 실행 (권장)
english.TaskAutoStart=Start automatically when Windows starts (recommended)
korean.TaskManual=자동 실행하지 않음 (필요할 때 시작 메뉴에서 직접 실행)
english.TaskManual=Do not start automatically (launch manually from the Start menu)
korean.TaskDesktop=바탕화면에 바로가기 만들기
english.TaskDesktop=Create a desktop shortcut
korean.RunAfter=설치 후 Download Catalog 실행
english.RunAfter=Launch Download Catalog now

[Tasks]
; 둘 중 하나만 선택(exclusive). 기본값은 자동 실행.
Name: "autostart"; Description: "{cm:TaskAutoStart}"; GroupDescription: "{cm:GroupStart}"; Flags: exclusive
Name: "manual"; Description: "{cm:TaskManual}"; GroupDescription: "{cm:GroupStart}"; Flags: exclusive unchecked
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; Flags: unchecked

[Files]
Source: "..\dist\DownloadCatalog\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; 자동 실행을 고른 경우에만 등록. 제거할 때 값도 함께 삭제된다.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "DownloadCatalog"; ValueData: """{app}\{#MyAppExe}"""; Tasks: autostart; \
    Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:RunAfter}"; Flags: nowait postinstall skipifsilent

[Code]
// 재설치(업데이트) 시 이전에 고른 자동 실행 선택을 반영하기 위해,
// '자동 실행하지 않음'을 고르면 기존에 등록된 Run 값을 지운다.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('manual') then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DownloadCatalog');
end;
