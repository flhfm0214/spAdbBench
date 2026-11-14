; spAdbBench installer template (Inno Setup 6)
; Build with:
;   ISCC.exe /DAppVersion=1.0.0 installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "spAdbBench"
#define AppExe "spAdbBench.exe"
#define AppId "{{A887F67A-AE61-4FC7-B0B6-C0D32DA8FD1A}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=spAdbBench
AppPublisherURL=https://github.com/flhfm0214/spAdbBench
AppSupportURL=https://github.com/flhfm0214/spAdbBench
AppUpdatesURL=https://github.com/flhfm0214/spAdbBench
AppComments=安装后应用以管理员权限运行，可在任意目录创建文件。
DefaultDirName={autopf}\spAdbBench
DefaultGroupName=spAdbBench
AllowNoIcons=yes
DisableDirPage=no
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableReadyPage=no
DisableFinishedPage=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=spAdbBench-Setup-{#AppVersion}
SetupIconFile=spAdbBench.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no
VersionInfoVersion=1.0.0.0
VersionInfoTextVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany=spAdbBench
VersionInfoDescription={#AppName} 安装程序

[Languages]
Name: "chinesesimplified"; MessagesFile: "{#SourcePath}\ChineseSimplified.isl"

[CustomMessages]
desktopicon=创建桌面快捷方式
launchapp=启动 spAdbBench

[Messages]
WelcomeLabel2=安装程序将申请管理员权限，并把 [name] 安装到你选择的目录。%n%n应用启动时也会申请管理员权限，以便在任意目录创建文件。

[Tasks]
Name: "desktopicon"; Description: "{cm:desktopicon}"; GroupDescription: "附加任务："; Flags: checkedonce

[Dirs]
Name: "{app}"; Permissions: users-modify
Name: "{app}\config"; Permissions: users-modify
Name: "{app}\data"; Permissions: users-modify

[Files]
Source: "..\dist\spAdbBench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\spAdbBench"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\spAdbBench"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:launchapp}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\config"
Type: filesandordirs; Name: "{app}\data"
