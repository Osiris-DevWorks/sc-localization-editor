; Single source of truth: VERSION.TXT at the project root. Update that file
; and re-run the build — every version-stamped field below is derived from it.
#define VersionFile FileOpen(AddBackslash(SourcePath) + "VERSION.TXT")
#define AppVer Trim(FileRead(VersionFile))
#expr FileClose(VersionFile)
#undef VersionFile

[Setup]
AppId={{9A8B7C6D-4E3F-5B2A-0D1E-8F7G6H5I4J3K}
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
PrivilegesRequired=admin
SetupIconFile=assets\logo.ico
; Write a per-run install log to %TEMP%\Setup Log YYYY-MM-DD #NNN.txt.
; Critical for diagnosing the upgrade-uninstall race (see UnInstallOldVersion):
; without this, the WARNING from a WaitForUninstallToFinish timeout goes nowhere
; and a tester reporting "uninstall.exe was deleted" gives us nothing to grep.
SetupLogging=yes

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
  { 1.4.1: cache lives on a separate page so users can split the ~1.4 GB
    DataForge tree off the user-data folder (e.g. SSD for cache,
    OneDrive Documents for user.ini). Saved to HKCU\...\cache_dir;
    cleared on Reset so the app's default (%LOCALAPPDATA%\Smart Citizen)
    wins on resolution. }
  CacheDirPage: TInputDirWizardPage;

function GetLocalCacheDefault(): String;
begin
  { Mirrors AppSettings.get_dataforge_cache_base() default for registry
    mode: %LOCALAPPDATA%\Smart Citizen. Channel/cache/dataforge nesting
    is added by the app at runtime. }
  Result := ExpandConstant('{%LOCALAPPDATA}\Smart Citizen');
end;

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

function WaitForUninstallToFinish(MaxSeconds: Integer): Boolean;
var
  RegPath: String;
  Dummy: String;
  Elapsed: Integer;
begin
  { Inno Setup's silent uninstaller copies itself to %TEMP%\_iu*.tmp and the
    original exits immediately — so the Exec() that launched it returns long
    before the temp copy has finished its work. The temp copy's very last
    act is to delete the AppId_is1 entry under Uninstall, so we use that
    disappearance as the "fully done" signal. Polling the registry rather
    than the on-disk unins000.exe avoids racing with our own InstallDelete. }
  RegPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1';
  Elapsed := 0;
  while Elapsed < MaxSeconds * 4 do
  begin
    if (not RegQueryStringValue(HKLM, RegPath, 'UninstallString', Dummy)) and
       (not RegQueryStringValue(HKCU, RegPath, 'UninstallString', Dummy)) then
    begin
      Result := True;
      Exit;
    end;
    Sleep(250);
    Inc(Elapsed);
  end;
  Result := False;
end;

function UnInstallOldVersion(): Integer;
var
  sUnInstallString: String;
  iResultCode: Integer;
  SavedStatus: String;
  SavedStyle: TNewProgressBarStyle;
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

  { Distinct upgrade-uninstall step: flip the wizard's status label to
    "Uninstalling previous version..." and run the progress bar in marquee
    mode while the old uninstaller does its work. Without this UX cue,
    users saw the install page sit silently for 5–30s and assumed the
    installer had hung. }
  SavedStatus := WizardForm.StatusLabel.Caption;
  SavedStyle := WizardForm.ProgressGauge.Style;
  WizardForm.StatusLabel.Caption := 'Uninstalling previous version...';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  WizardForm.Update;

  if Exec(sUnInstallString, '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
  begin
    { Race fix: without WaitForUninstallToFinish(), the detached temp copy
      of the old uninstaller would still be running when InstallDelete and
      Files execute. Its final-act registry+file cleanup would then delete
      the *new* unins000.exe in the app dir and clear the freshly-written
      AppId_is1 entry under Uninstall — leaving users with an installed
      app and no way to uninstall it. Reported upgrading 1.1.0 -> 1.2.0.

      Timeout bumped 90 -> 180 s to cover slow-disk + actively-syncing-
      OneDrive + Defender-on-access environments where the old uninstaller
      temp copy's final cleanup pass routinely runs 60–120 s. When the
      timeout *does* fire, surface a wizard error dialog instead of only
      logging — the original log-only warning meant users discovered the
      broken state days later when they tried to uninstall and found
      nothing in Apps & Features. }
    if not WaitForUninstallToFinish(180) then
    begin
      Log('WARNING: timed out waiting for old uninstaller to finish (180s). The new install may produce a broken uninstaller; user should uninstall + reinstall manually if the Apps & Features entry is missing.');
      MsgBox('The previous version''s uninstaller did not finish within 3 minutes.' + #13#10 + #13#10 +
             'The install will continue, but the new uninstaller file (unins000.exe) may be deleted by the old uninstaller''s delayed cleanup. If that happens, Smart Citizen will install successfully but will not appear in Apps & Features.' + #13#10 + #13#10 +
             'If you later cannot uninstall Smart Citizen, re-run this installer and choose the Uninstall option, or delete the install folder manually.' + #13#10 + #13#10 +
             'Closing other apps (especially OneDrive sync, antivirus scans, and the Search Indexer) before the install can avoid this.',
             mbError, MB_OK);
    end;
    Result := 3;
  end
  else
    Result := 2;

  { Restore the wizard for the install phase. }
  WizardForm.StatusLabel.Caption := SavedStatus;
  WizardForm.ProgressGauge.Style := SavedStyle;
  WizardForm.Update;
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

procedure WriteInstallerChoicesToRegistry();
var
  RegPath: String;
  FinalPath: String;
  DataDir: String;
  DocsDefault: String;
  CacheDir: String;
  CacheDefault: String;
begin
  { Persist the user's choices from the installer wizard pages
    (SC install dir + Smart Citizen data folder) into the registry
    so the app reads them on first launch. Called from
    CurStepChanged at ssPostInstall — AFTER files have been copied
    so ForceDirectories on a custom data folder doesn't race the
    install itself. }

  { SC directory: written to BOTH the new (Smart Citizen) and legacy
    (SC Localization Editor) registry nodes. The new node survives
    the app's migrate_registry_appname() — which deletes the legacy
    subtree after copying values across. The legacy write is a compat
    fallback for very old app versions that haven't been launched
    yet to perform their own migration; cheap and keeps downgrade
    paths working. }
  FinalPath := SCDirectoryPage.Values[0];
  if FinalPath <> '' then
  begin
    RegPath := 'Software\Osiris DevWorks\Smart Citizen';
    RegWriteStringValue(HKCU, RegPath, 'sc_directory', FinalPath);
    RegWriteStringValue(HKCU, RegPath, 'game_install_path', FinalPath);
    { Write sc_install_root (parent of the channel folder) so a reinstall
      with a changed SC path doesn't leave the stale root from a prior
      migration winning over the freshly chosen directory. }
    RegWriteStringValue(HKCU, RegPath, 'sc_install_root', ExtractFileDir(RemoveBackslash(FinalPath)));
    RegWriteStringValue(HKCU,
      'Software\Osiris DevWorks\SC Localization Editor',
      'sc_directory', FinalPath);
    Log('Saved sc_directory to registry (Smart Citizen + legacy nodes): ' + FinalPath);
  end;

  { Persist the data folder choice. The page is always shown in 1.3.0+,
    so every install reaches this branch. Comparison rules:
      - Empty field, or value equal to the natural Documents default:
        clear the override so the app's dynamic Documents resolution
        wins on every launch (matches the in-app Reset behavior in
        AppSettings.set_user_data_dir(None)). Keeps the registry tidy
        for users who never wanted a custom path.
      - Anything else: write user_data_dir. Also clear the legacy
        camelCase 'UserDataDir' alias if present so the app reads the
        canonical value. ForceDirectories ensures the chosen folder
        exists by the time the app first launches.
    Writes are scoped to the NEW (Smart Citizen) registry node — the
    app's migrate_registry_appname() preserves it across rebrand
    migrations. }
  DataDir := DataDirPage.Values[0];
  DocsDefault := GetDocumentsBase() + '\Smart Citizen';
  if (DataDir = '') or (CompareText(DataDir, DocsDefault) = 0) then
  begin
    RegDeleteValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen', 'user_data_dir');
    RegDeleteValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen', 'UserDataDir');
    Log('User chose default Documents folder; cleared user_data_dir override.');
  end
  else
  begin
    RegWriteStringValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen',
      'user_data_dir', DataDir);
    RegDeleteValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen', 'UserDataDir');
    ForceDirectories(DataDir);
    Log('Saved user_data_dir to registry: ' + DataDir);
  end;

  { 1.4.1+: persist the cache folder choice. Same comparison rule as
    user_data_dir — clear the override when the user accepted the
    %LOCALAPPDATA%\Smart Citizen default so the app's runtime resolver
    stays in charge. Otherwise write cache_dir and pre-create the
    directory. }
  CacheDir := CacheDirPage.Values[0];
  CacheDefault := GetLocalCacheDefault();
  if (CacheDir = '') or (CompareText(CacheDir, CacheDefault) = 0) then
  begin
    RegDeleteValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen', 'cache_dir');
    Log('User chose default cache folder; cleared cache_dir override.');
  end
  else
  begin
    RegWriteStringValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen',
      'cache_dir', CacheDir);
    ForceDirectories(CacheDir);
    Log('Saved cache_dir to registry: ' + CacheDir);
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

  if (CurStep = ssPostInstall) then
  begin
    { Persist wizard-page choices (sc_directory + user_data_dir) to the
      registry. Previously this lived in a procedure named
      `CurFinished(LastStep: TSetupStep)` — NOT a real Inno Setup event
      callback name (Inno doesn't support that signature) — so the
      whole block silently never ran. Users who customized the data
      folder in the installer would see Documents\Smart Citizen on
      first launch instead of their pick. Discovered post-1.3.0 release
      after a user reported the data-dir choice not carrying over. }
    WriteInstallerChoicesToRegistry();

    // Catch-all sanity check: by ssPostInstall, Inno has written its
    // generated uninstaller to the install dir. If it isn't there,
    // something removed it between [Files] completion and now — most
    // likely the upgrade-uninstall race (WaitForUninstallToFinish
    // timeout fired and the old uninstaller's temp copy nuked our new
    // one) or a Smart App Control / Defender quarantine of the unsigned
    // uninstaller binary. Tell the user explicitly rather than letting
    // them discover it days later when Apps & Features has no entry.
    // The install itself is kept — the app works fine without the
    // uninstaller; only removal is affected.
    // Using // line comments here rather than block comments because the
    // Inno constant syntax below (curly-brace form) closes Pascal block
    // comments early — both block forms in Pascal have non-nesting
    // terminators and are tripped by literal references to that syntax.
    if not FileExists(ExpandConstant('{app}\unins000.exe')) then
    begin
      Log('ERROR: unins000.exe missing from {app} post-install. Install completed but uninstall is broken.');
      MsgBox('Smart Citizen installed successfully, but the uninstaller file (unins000.exe) is missing from:' + #13#10 + #13#10 +
             '  ' + ExpandConstant('{app}') + #13#10 + #13#10 +
             'Smart Citizen will not appear in Apps & Features. The app itself works normally — only uninstall is affected.' + #13#10 + #13#10 +
             'Likely causes:' + #13#10 +
             '  - Windows Smart App Control or Defender quarantined the unsigned uninstaller' + #13#10 +
             '    (check Windows Security -> Protection history)' + #13#10 +
             '  - A previous version''s uninstaller finished cleanup after this install wrote its files' + #13#10 + #13#10 +
             'To remove Smart Citizen later: re-run this installer and choose the Uninstall option, or delete the install folder manually.',
             mbError, MB_OK);
    end;
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

function IsValidSCPath(const Path: String): Boolean;
var
  BasePath: String;
  LastName: String;
begin
  { Returns True if Path looks like a valid Star Citizen install path.
    Accepts either:
      - a root containing channel subdirectories (LIVE, PTU, etc.), or
      - a channel path (last component is a channel name like LIVE).
    Guards against stale registry values like 'SmartCitizen 1.4.1'. }
  BasePath := RemoveBackslash(Path) + '\';
  LastName := LowerCase(ExtractFileName(BasePath));
  if (LastName = 'live') or (LastName = 'ptu') or (LastName = 'eptu') or
     (LastName = 'hotfix') or (LastName = 'tech-preview') then
    Result := True
  else
    Result := DirExists(BasePath + 'LIVE') or DirExists(BasePath + 'PTU') or
              DirExists(BasePath + 'EPTU') or DirExists(BasePath + 'HOTFIX') or
              DirExists(BasePath + 'TECH-PREVIEW');
end;

procedure InitializeWizard();
var
  NewRegPath: String;
  LegacyRegPath: String;
  DefaultPath: String;
  SavedPath: String;
  SCRoot: String;
  ActiveChannel: String;
  SavedDataDir: String;
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
         prefilled on the first reinstall. The installer's
         WriteInstallerChoicesToRegistry (called from CurStepChanged
         at ssPostInstall) writes to the NEW node regardless, so
         subsequent reinstalls resolve via path 1. }
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
  if RegQueryStringValue(HKCU, NewRegPath, 'sc_install_root', SCRoot) and (SCRoot <> '') and IsValidSCPath(SCRoot) then
  begin
    ActiveChannel := 'LIVE';
    DefaultPath := SCRoot + '\' + ActiveChannel;
  end;

  { Fall back to previously saved sc_directory / game_install_path in the
    NEW node, then the LEGACY node.  Each value is validated to ensure it
    actually looks like a valid SC install path (either ends with a channel
    name, or contains channel subdirectories).  Validation is folded into
    the condition so a stale value causes fallthrough to the next option. }
  if DefaultPath = '' then
  begin
    if RegQueryStringValue(HKCU, NewRegPath, 'sc_directory', SavedPath) and (SavedPath <> '') and IsValidSCPath(SavedPath) then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, NewRegPath, 'game_install_path', SavedPath) and (SavedPath <> '') and IsValidSCPath(SavedPath) then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, LegacyRegPath, 'sc_directory', SavedPath) and (SavedPath <> '') and IsValidSCPath(SavedPath) then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, LegacyRegPath, 'game_install_path', SavedPath) and (SavedPath <> '') and IsValidSCPath(SavedPath) then
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

  { Smart Citizen data location: always exposed so users can move the
    cache, custom edits, and backups off the default Documents folder —
    useful even when Documents isn't OneDrive-synced (e.g. user wants the
    2 GB cache on a faster SSD or a different drive). The default value
    adapts:
      1. If a prior override exists, pre-fill it (respects the user's
         previous choice across reinstalls).
      2. Else if Documents is OneDrive-synced, suggest the local
         %USERPROFILE%\Documents\Smart Citizen junction (escapes the sync).
      3. Else pre-fill Documents\Smart Citizen (the natural default).
    WriteInstallerChoicesToRegistry compares the final value against the
    natural default and only writes user_data_dir when the user actually
    picked something different — so leaving the field at its default
    keeps the registry clean and lets the app's dynamic Documents
    resolution win. }
  DataDirPage := CreateInputDirPage(
    SCDirectoryPage.ID,
    'Smart Citizen Data Location',
    'Choose where Smart Citizen stores user.ini, source cache, enhancement INIs, and backups.',
    'Smart Citizen stores your custom edits (user.ini), the localization source cache, '
    + 'generated enhancement INIs, and rolling backups under this folder. The default is your '
    + 'Documents folder.'
    + #13#10 + #13#10 +
    'The ~1.4 GB DataForge XML cache lives on its own page next — splitting them lets you keep '
    + 'your tiny user data wherever you like while sending the cache to a fast SSD.'
    + #13#10 + #13#10 +
    'Consider a custom location if:'
    + #13#10 +
    '  - Your Documents folder is synced to OneDrive (causes occasional "Access is denied"'
    + #13#10 +
    '    errors and slow cleanup of generated INIs)'
    + #13#10 +
    '  - You manage multiple profiles or installs and want them isolated'
    + #13#10 + #13#10 +
    'You can change this later from the app''s Config tab.',
    False,
    'Smart Citizen Data'
  );
  DataDirPage.Add('');

  { Pre-fill: existing override > OneDrive suggestion > Documents default. }
  if RegQueryStringValue(HKCU, NewRegPath, 'user_data_dir', SavedDataDir) and
     (SavedDataDir <> '') then
    DataDirPage.Values[0] := SavedDataDir
  else if IsDocsOnOneDrive() then
    DataDirPage.Values[0] := SuggestLocalDataDir()
  else
    DataDirPage.Values[0] := GetDocumentsBase() + '\Smart Citizen';

  { 1.4.1+: DataForge cache lives on its own page so users can split it
    off the user-data folder. The app's runtime default is
    %LOCALAPPDATA%\Smart Citizen (never OneDrive-synced) and that's what
    we offer here. WriteInstallerChoicesToRegistry only writes cache_dir
    when the field differs from this default, so users who accept the
    default keep the registry clean and let the app's resolver win. }
  CacheDirPage := CreateInputDirPage(
    DataDirPage.ID,
    'DataForge Cache Location',
    'Choose where Smart Citizen stores the ~1.4 GB DataForge XML cache.',
    'The DataForge cache contains ~28,000 entity XMLs extracted from Star Citizen''s '
    + 'Data.p4k file. It''s used to generate the in-game item descriptions you see in the '
    + 'Enhancements tab.'
    + #13#10 + #13#10 +
    'The default keeps the cache in your Windows AppData\Local folder — never synced to '
    + 'OneDrive — so extraction and cleanup stay fast even when your Documents are.'
    + #13#10 + #13#10 +
    'Pick a custom location if you want to:'
    + #13#10 +
    '  - Move the 1.4 GB tree to a different drive (faster SSD, or to free C: space)'
    + #13#10 +
    '  - Share the cache between multiple Smart Citizen installs on this PC'
    + #13#10 + #13#10 +
    'You can change this later from the app''s Config tab. Changing the path triggers a '
    + 'one-time re-extraction.',
    False,
    'DataForge Cache'
  );
  CacheDirPage.Add('');

  { Pre-fill: existing override > LOCALAPPDATA default. No OneDrive
    branch because LOCALAPPDATA is the OneDrive-safe location by
    definition (it's machine-local, never roamed). }
  if RegQueryStringValue(HKCU, NewRegPath, 'cache_dir', SavedDataDir) and
     (SavedDataDir <> '') then
    CacheDirPage.Values[0] := SavedDataDir
  else
    CacheDirPage.Values[0] := GetLocalCacheDefault();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { 1.3.0+: the data-folder page is always shown so every user gets a
    chance to relocate the cache (not just OneDrive-synced installs). The
    OneDrive-only gate was removed — pre-fill logic in InitializeWizard
    handles the OneDrive case by suggesting a local path. }
  Result := False;
end;

