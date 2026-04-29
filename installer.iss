; Single source of truth: VERSION.TXT at the project root. Update that file
; and re-run the build — every version-stamped field below is derived from it.
#define VersionFile FileOpen(AddBackslash(SourcePath) + "VERSION.TXT")
#define AppVer Trim(FileRead(VersionFile))
#expr FileClose(VersionFile)
#undef VersionFile

[Setup]
AppId={{0CCDDCA2-CD87-4942-A600-F338F6841466}
AppName=Smart Citizen
AppVersion={#AppVer}
AppPublisher=Osiris DevWorks
AppPublisherURL=https://github.com/Osiris-DevWorks/smart-citizen
DefaultDirName={localappdata}\Osiris DevWorks\Smart Citizen
DefaultGroupName=Smart Citizen
OutputDir=dist
OutputBaseFilename=SmartCitizen-{#AppVer}-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
DisableDirPage=no
AllowUNCPath=no
PrivilegesRequired=lowest
SetupIconFile=assets\logo.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
SCDirectoryPrompt=Star Citizen Directory
SCDirectoryPromptDesc=Please specify your Star Citizen LIVE directory for automatic file detection.
SCDirectoryDefaultDesc=This is typically located at:
SCDirectoryDefaultPath=C:\Program Files\Roberts Space Industries\StarCitizen\LIVE

[InstallDelete]
; Clear previous install directory completely before installing new files
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "dist\SmartCitizen-v{#AppVer}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Smart Citizen"; Filename: "{app}\SmartCitizen-v{#AppVer}.exe"
Name: "{group}\{cm:UninstallProgram,Smart Citizen}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Smart Citizen"; Filename: "{app}\SmartCitizen-v{#AppVer}.exe"

[Run]
Filename: "{app}\SmartCitizen-v{#AppVer}.exe"; Description: "{cm:LaunchProgram,Smart Citizen}"; Flags: nowait postinstall skipifsilent

[Code]
var
  SCDirectoryPage: TInputDirWizardPage;
  DataDirPage: TInputDirWizardPage;
  DataDirPromptShown: Boolean;

function IsDocsOnOneDrive(): Boolean;
var
  DocsPath: String;
begin
  { Read the invoking user's Documents shell-folder path. When Windows has
    folder-redirected Documents into OneDrive (the default on most OneDrive
    installs now), this string contains "\OneDrive\". Cache extraction +
    50,000-file rmtree under an actively-synced OneDrive tree is 3-5x
    slower and routinely fails with WinError 5 — worth warning the user
    and offering a local-only alternative. }
  Result := False;
  if RegQueryStringValue(HKCU,
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders',
    'Personal', DocsPath) then
  begin
    Result := (Pos('\OneDrive\', DocsPath) > 0) or
              (Pos('\OneDrive/', DocsPath) > 0);
  end;
end;

function HasDataDirOverride(): Boolean;
var
  Dummy: String;
begin
  { Respect existing user choice — if the override is already set in either
    the new "Smart Citizen" node or the legacy "SC Localization Editor"
    node, skip the prompt entirely. }
  Result := RegQueryStringValue(HKCU,
              'Software\Osiris DevWorks\Smart Citizen',
              'user_data_dir', Dummy) or
            RegQueryStringValue(HKCU,
              'Software\Osiris DevWorks\SC Localization Editor',
              'user_data_dir', Dummy);
end;

function SuggestLocalDataDir(): String;
begin
  { Build a sensible default pointing at the local (non-OneDrive) profile.
    %USERPROFILE% is the real NTFS path; \Documents here is the junction
    that Windows keeps even when the shell's Personal has been redirected. }
  Result := ExpandConstant('{%USERPROFILE}\Documents\Smart Citizen');
end;

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

procedure ClearStaleUninstallEntry();
var
  sRegPath: String;
begin
  { Remove zombie registry entries that point at a non-existent unins000.exe.
    Background: when a user's previous install lived under a non-default path
    (e.g. Documents\Smart Citizen\) and the folder was manually deleted or
    moved without running the uninstaller, Windows keeps the Uninstall
    registry entry — and "Installed Apps" on Win10/11 then shows the app
    with an Uninstall button that fails ("Windows cannot find …\unins000.exe").
    Left alone, the entry also blocks our GetUninstallString() / IsUpgrade()
    flow from doing the right thing. Clearing both HKLM and HKCU variants
    is safe: the install about to run will recreate the entry cleanly. }
  sRegPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1';
  RegDeleteKeyIncludingSubkeys(HKLM, sRegPath);
  RegDeleteKeyIncludingSubkeys(HKCU, sRegPath);
  Log('Cleared stale uninstall registry entry (unins000.exe was missing)');
end;

function UnInstallOldVersion(): Integer;
var
  sUnInstallString: String;
  iResultCode: Integer;
begin
  { Return Values:
    1 - uninstall string is empty
    2 - error executing the UnInstallString
    3 - successfully executed the UnInstallString
    4 - uninstall string found but the unins000.exe doesn't exist (zombie
        entry from a manual folder deletion) — cleared the registry entry
        so the new install can register fresh. }

  Result := 0;

  { get the uninstall string of the old app }
  sUnInstallString := GetUninstallString();
  if sUnInstallString = '' then begin
    Result := 1;
    Exit;
  end;

  sUnInstallString := RemoveQuotes(sUnInstallString);

  { Zombie-entry guard: if the recorded unins000.exe isn't on disk, running
    Exec() against it would fail silently and leave the registry entry
    dangling forever (plus Windows' "Installed Apps" would keep offering a
    broken Uninstall button). Nuke the registry entry and let the new
    install write a fresh one. Addresses the
      "Windows cannot find …\unins000.exe"
    error users report after a partial/manual removal of a custom-path
    install. }
  if not FileExists(sUnInstallString) then begin
    ClearStaleUninstallEntry();
    Result := 4;
    Exit;
  end;

  if Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
    Result := 3
  else
    Result := 2;
end;

function GetDocumentsBase(): String;
begin
  if not RegQueryStringValue(HKCU,
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders',
    'Personal', Result) then
  begin
    Result := ExpandConstant('{userdocs}');
  end;
end;

function GetDocumentsDir(): String;
var
  OverridePath: String;
begin
  { Match the app's resolution order (AppSettings.get_user_data_dir):
      1. user_data_dir registry override — set when the user picked a
         non-Documents folder during install (OneDrive escape) or via the
         in-app data dir setting. If the app is storing cache here, the
         uninstaller MUST clean here too — otherwise stale 2GB+ caches
         survive uninstall.
      2. userdocs \Smart Citizen — the default. }
  if RegQueryStringValue(HKCU,
    'Software\Osiris DevWorks\Smart Citizen',
    'user_data_dir', OverridePath) and (OverridePath <> '') then
  begin
    Result := OverridePath;
    Exit;
  end;
  Result := GetDocumentsBase() + '\Smart Citizen';
end;

procedure MigrateUserDocsFolder();
var
  DocsBase, OldDir, NewDir: String;
begin
  { Rebrand: rename Documents\SC Localization Editor\ → Documents\Smart Citizen\
    if the old folder exists and the new one does not. User data (user.ini,
    backups, cache) moves with the rename — no copy required. }
  DocsBase := GetDocumentsBase();
  OldDir := DocsBase + '\SC Localization Editor';
  NewDir := DocsBase + '\Smart Citizen';
  if DirExists(OldDir) and not DirExists(NewDir) then
  begin
    MsgBox('Your user data folder will be renamed as part of this update:' + #13#10 + #13#10 +
           '  ' + OldDir + #13#10 +
           '  →  ' + NewDir + #13#10 + #13#10 +
           'Your custom edits, backups, and cached files will move with it — nothing is lost.',
           mbInformation, MB_OK);
    Log('Renaming user data folder: ' + OldDir + ' -> ' + NewDir);
    if not RenameFile(OldDir, NewDir) then
      Log('WARNING: rename failed; data remains at old location');
  end;
end;

procedure CleanPerChannelCaches(UserDataDir: String);
var
  Channels: array[0..4] of String;
  i: Integer;
  CachePath: String;
  Deleted: Boolean;
begin
  { Per-channel layout (0.9.3+): each Star Citizen channel has its own
    user data subtree at Documents\Smart Citizen\<channel>\. Only \cache
    is disposable — \backups (the user's global.ini safety net) and
    user.ini (their customizations) must survive both install and
    uninstall, so we delete \cache per channel and leave the rest alone.

    Logs the path tried, the DelTree return value, and whether the
    directory still exists afterwards. Surfaces silent failures (locked
    files under OneDrive sync / Defender real-time scan) in the install
    log so users reporting "cache wasn't removed" can be diagnosed. }
  Channels[0] := 'LIVE';
  Channels[1] := 'PTU';
  Channels[2] := 'EPTU';
  Channels[3] := 'HOTFIX';
  Channels[4] := 'TECH-PREVIEW';
  for i := 0 to 4 do
  begin
    CachePath := UserDataDir + '\' + Channels[i] + '\cache';
    if DirExists(CachePath) then
    begin
      Log('Deleting per-channel cache: ' + CachePath);
      Deleted := DelTree(CachePath, True, True, True);
      if not Deleted then
        Log('WARNING: DelTree returned false for ' + CachePath);
      if DirExists(CachePath) then
        Log('WARNING: cache path still exists after DelTree: ' + CachePath +
            ' (likely a file is locked by OneDrive sync, Windows Defender, ' +
            'or the Search Indexer — close those processes and retry the uninstaller)');
    end
    else
    begin
      Log('Per-channel cache absent (nothing to delete): ' + CachePath);
    end;
  end;
end;

procedure CleanCachedData();
var
  UserDataDir, LegacyCache: String;
begin
  UserDataDir := GetDocumentsDir();
  if DirExists(UserDataDir) then
  begin
    Log('Cleaning cached data from: ' + UserDataDir);
    { Current layout — delete \cache under each channel subtree. }
    CleanPerChannelCaches(UserDataDir);
    { Defensive: pre-0.9.3 flat layout kept cache at \Smart Citizen\cache\.
      The channel migrator runs at app launch and should have moved this
      already, but if a user is upgrading from a state where the migrator
      never ran (e.g. they uninstalled before first launching 0.9.3+),
      mop it up here. }
    LegacyCache := UserDataDir + '\cache';
    if DirExists(LegacyCache) then
    begin
      Log('Deleting legacy flat-layout cache: ' + LegacyCache);
      DelTree(LegacyCache, True, True, True);
    end;
  end;
end;

procedure CleanRegistrySettings();
var
  RegPath: String;
  SavedSCDir: String;
  HadSCDir: Boolean;
begin
  RegPath := 'Software\Osiris DevWorks\SC Localization Editor';

  { Preserve sc_directory so the installer page can pre-fill it }
  HadSCDir := RegQueryStringValue(HKCU, RegPath, 'sc_directory', SavedSCDir);

  { Delete the entire app registry key }
  RegDeleteKeyIncludingSubkeys(HKCU, RegPath);

  { Restore sc_directory if it existed }
  if HadSCDir and (SavedSCDir <> '') then
  begin
    RegWriteStringValue(HKCU, RegPath, 'sc_directory', SavedSCDir);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep=ssInstall) then
  begin
    if (IsUpgrade()) then
    begin
      UnInstallOldVersion();
    end;

    { Rebrand migration: rename Documents\SC Localization Editor\ to
      Documents\Smart Citizen\ before we touch any cached data. }
    MigrateUserDocsFolder();

    { Clear cached data but preserve registry settings (source paths, preferences, etc.) }
    CleanCachedData();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    { Same cleanup contract as install/upgrade: per-channel \cache gets
      nuked, \backups + user.ini survive so a reinstall picks up where
      the user left off. }
    Log('Cleaning cached data during uninstall');
    CleanCachedData();
  end;
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  UninstallString: String;
  UninstallExe: String;
  ButtonPressed: Integer;
begin
  Result := True;

  { Check if the application is already installed }
  UninstallString := GetUninstallString();
  if UninstallString <> '' then
  begin
    { Zombie-entry guard: if the uninstall string points at a file that's
      no longer on disk, the prior "upgrade?" dialog would offer choices
      that would all fail (Exec against a missing unins000.exe is a silent
      no-op, leaving the dangling registry entry in place forever). Clear
      the stale entry and continue as a fresh install — skipping the
      dialog entirely since there's nothing real to upgrade from. }
    UninstallExe := RemoveQuotes(UninstallString);
    if not FileExists(UninstallExe) then
    begin
      ClearStaleUninstallEntry();
      Exit;  { Result is already True — proceed with fresh install }
    end;

    { Show custom dialog with three options }
    ButtonPressed := MsgBox('A previous version of this application is already installed.' + #13#10 + #13#10 +
                            'Choose an option:' + #13#10 +
                            '  - Click YES to uninstall the old version and install this new version' + #13#10 +
                            '  - Click NO to uninstall the old version only (without installing)' + #13#10 +
                            '  - Click CANCEL to exit without making any changes',
                            mbConfirmation, MB_YESNOCANCEL);

    case ButtonPressed of
      IDYES: begin
        { Continue with upgrade (uninstall old, then install new) }
        Result := True;
      end;
      IDNO: begin
        { Uninstall only, without installing new version }
        UninstallString := RemoveQuotes(UninstallString);
        Exec(UninstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        Result := False;
      end;
      IDCANCEL: begin
        { Cancel installation }
        Result := False;
      end;
    end;
  end;
end;

procedure InitializeWizard();
var
  NewRegPath: String;
  LegacyRegPath: String;
  DefaultPath: String;
  SavedPath: String;
  SCRoot: String;
  ActiveChannel: String;
begin
  { Registry path resolution order:
      1. NEW "Smart Citizen" node (post-0.9.2 rebrand) — every app launch
         writes here, and the one-shot migrate_registry_appname() in the
         app's main() deletes the legacy subtree after copying values over.
         That means any sc_directory we wrote to the legacy node on a
         previous installer run was subsequently wiped by the app. Writing
         and reading from the NEW node is the fix.
      2. LEGACY "SC Localization Editor" node — kept as a read-side
         fallback so users who upgrade from a version earlier than 0.9.2
         (and therefore have no NEW node yet) still get their path
         prefilled on the first reinstall. The installer's CurFinished
         writes to the NEW node regardless, so subsequent reinstalls
         resolve via path 1. }
  NewRegPath := 'Software\Osiris DevWorks\Smart Citizen';
  LegacyRegPath := 'Software\Osiris DevWorks\SC Localization Editor';
  DefaultPath := '';

  { 0.9.3+: the app stores the SC install root (parent of LIVE/PTU/...) in
    sc_install_root. Always default the installer's prompt to the LIVE
    subfolder — the page title says "Star Citizen LIVE Directory" and
    users consistently expect LIVE to be offered regardless of which
    channel the app is currently pointed at. The active_channel value is
    ignored here on purpose; the app-side channel switcher handles
    per-channel paths at runtime. }
  if RegQueryStringValue(HKCU, NewRegPath, 'sc_install_root', SCRoot) and (SCRoot <> '') then
  begin
    ActiveChannel := 'LIVE';
    DefaultPath := SCRoot + '\' + ActiveChannel;
  end;

  { Fall back to previously saved sc_directory / game_install_path in the
    NEW node, then the LEGACY node. }
  if DefaultPath = '' then
  begin
    if RegQueryStringValue(HKCU, NewRegPath, 'sc_directory', SavedPath) and (SavedPath <> '') then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, NewRegPath, 'game_install_path', SavedPath) and (SavedPath <> '') then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, LegacyRegPath, 'sc_directory', SavedPath) and (SavedPath <> '') then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, LegacyRegPath, 'game_install_path', SavedPath) and (SavedPath <> '') then
      DefaultPath := SavedPath
    else if DirExists('C:\Program Files\Roberts Space Industries\StarCitizen\LIVE') then
      DefaultPath := 'C:\Program Files\Roberts Space Industries\StarCitizen\LIVE'
    else if DirExists('C:\Program Files (x86)\Roberts Space Industries\StarCitizen\LIVE') then
      DefaultPath := 'C:\Program Files (x86)\Roberts Space Industries\StarCitizen\LIVE'
    else
      DefaultPath := 'C:\Program Files\Roberts Space Industries\StarCitizen';
  end;

  { Normalize the prompt default to the LIVE subfolder: if the resolved
    path ends in a non-LIVE channel name (because the app persisted
    game_install_path as the channel-suffixed path while the friend was
    on a non-LIVE channel), swap the suffix for \LIVE. The page is
    specifically asking for the LIVE directory; offering a non-LIVE one
    as the default confuses users whose main SC install is LIVE. }
  if LowerCase(ExtractFileName(DefaultPath)) = 'ptu' then
    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE'
  else if LowerCase(ExtractFileName(DefaultPath)) = 'eptu' then
    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE'
  else if LowerCase(ExtractFileName(DefaultPath)) = 'hotfix' then
    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE'
  else if LowerCase(ExtractFileName(DefaultPath)) = 'tech-preview' then
    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE';

  SCDirectoryPage := CreateInputDirPage(
    wpSelectTasks,
    ExpandConstant('{cm:SCDirectoryPrompt}'),
    ExpandConstant('{cm:SCDirectoryPromptDesc}'),
    ExpandConstant('{cm:SCDirectoryDefaultDesc}' + #13#10 + '{cm:SCDirectoryDefaultPath}'),
    False,
    'Star Citizen LIVE Directory'
  );

  SCDirectoryPage.Add('');
  SCDirectoryPage.Values[0] := DefaultPath;

  { Rebrand: if the prior install is still under the old "SC Localization
    Editor" folder name, override the prefilled app dir (and start-menu
    group) to the new brand. Any other prior location — including one the
    user customized — is preserved. }
  if Pos('SC Localization Editor', WizardForm.DirEdit.Text) > 0 then
    WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\Osiris DevWorks\Smart Citizen');
  if Pos('SC Localization Editor', WizardForm.GroupEdit.Text) > 0 then
    WizardForm.GroupEdit.Text := 'Smart Citizen';

  { OneDrive guard rail: when Documents is redirected to OneDrive, offer
    to store Smart Citizen's cache + user.ini on a local path instead.
    The page is *always* created (so ShouldSkipPage has something to
    reference) but hidden when it doesn't apply. DataDirPromptShown
    records whether it was actually exposed, so CurFinished only persists
    a value the user was given the chance to see. }
  DataDirPage := CreateInputDirPage(
    SCDirectoryPage.ID,
    'Smart Citizen Data Location',
    'Your Documents folder is synced to OneDrive — pick where to store data.',
    'Smart Citizen caches 2+ GB of extracted game data and stores your custom edits ' +
    'under your Documents folder. OneDrive-synced Documents is known to cause problems:'
    + #13#10 + #13#10 +
    '  - DataForge extraction is 3-5x slower because OneDrive, Windows Defender,'
    + #13#10 +
    '    and the Search Indexer each intercept every one of the 50,000+ files'
    + #13#10 +
    '  - Cache rebuilds can fail with "Access is denied" errors when OneDrive holds'
    + #13#10 +
    '    a transient file lock'
    + #13#10 +
    '  - The 2+ GB cache uploads to your OneDrive cloud quota on every rebuild'
    + #13#10 + #13#10 +
    'We recommend a local (non-OneDrive) folder. Accept the suggestion below, browse ' +
    'to a different location, or clear the field to keep the OneDrive default.',
    False,
    'Smart Citizen Data'
  );
  DataDirPage.Add('');
  DataDirPage.Values[0] := SuggestLocalDataDir();
  DataDirPromptShown := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (DataDirPage <> nil) and (PageID = DataDirPage.ID) then
  begin
    { Skip unless Documents is OneDrive-synced AND the user hasn't already
      set an override from a prior launch. }
    if IsDocsOnOneDrive() and not HasDataDirOverride() then
      DataDirPromptShown := True
    else
      Result := True;
  end;
end;

procedure CurFinished(LastStep: TSetupStep);
var
  RegPath: String;
  FinalPath: String;
  DataDir: String;
begin
  if LastStep = ssPostInstall then
  begin
    { Read the SC directory value at finish time (not page-change time)
      to ensure we capture any edits the user made on the page }
    FinalPath := SCDirectoryPage.Values[0];
    if FinalPath <> '' then
    begin
      { Write to the NEW ("Smart Citizen") node so the value survives
        the app's migrate_registry_appname() — which deletes the legacy
        subtree after copying values across. Prior installer revs wrote
        only to the legacy node and lost sc_directory on the next app
        launch, so reinstalls couldn't pre-fill the path. Writing to the
        legacy node ALSO (as a compat fallback for very old app versions
        that don't understand the new node yet) is cheap and keeps
        downgrade paths working. }
      RegPath := 'Software\Osiris DevWorks\Smart Citizen';
      RegWriteStringValue(HKCU, RegPath, 'sc_directory', FinalPath);
      RegWriteStringValue(HKCU, RegPath, 'game_install_path', FinalPath);
      RegWriteStringValue(HKCU,
        'Software\Osiris DevWorks\SC Localization Editor',
        'sc_directory', FinalPath);
      Log('Saved sc_directory to registry (Smart Citizen + legacy nodes): ' + FinalPath);
    end;

    { Persist the OneDrive-escape choice. Writes to the NEW (Smart Citizen)
      node — 0.9.2+ reads user_data_dir from there. If a legacy install's
      migration runs afterwards and the old node happens to carry its own
      user_data_dir, that user's prior explicit choice wins (migration
      overwrites). Otherwise this installer-written value survives. }
    if DataDirPromptShown then
    begin
      DataDir := DataDirPage.Values[0];
      if DataDir <> '' then
      begin
        RegWriteStringValue(HKCU,
          'Software\Osiris DevWorks\Smart Citizen',
          'user_data_dir', DataDir);
        ForceDirectories(DataDir);
        Log('Saved user_data_dir to registry: ' + DataDir);
      end
      else
      begin
        Log('User cleared data-dir override; keeping OneDrive default.');
      end;
    end;
  end;
end;
