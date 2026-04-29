@echo off
echo ========================================
echo Smart Citizen - Build Script
echo ========================================
echo.

:: ---------------------------------------------------------------------------
:: Detect code-signing configuration (all optional)
::   SC_SIGN_THUMB     SHA-1 thumbprint of a cert already in Windows cert store
::   SC_SIGN_CERT      Path to a PFX certificate file
::   SC_SIGN_PASSWORD  Password for the PFX file (leave unset for password-less certs)
:: ---------------------------------------------------------------------------
set SIGN_BUILD=0
if not "%SC_SIGN_THUMB%"=="" set SIGN_BUILD=1
if not "%SC_SIGN_CERT%"==""  set SIGN_BUILD=1

if "%SIGN_BUILD%"=="1" (
    echo Code signing: ENABLED
) else (
    echo Code signing: DISABLED  ^(set SC_SIGN_THUMB or SC_SIGN_CERT to enable^)
)
echo.

echo Step 1: Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo   - Old builds removed
echo.

echo Step 2: Building executable...
if "%SIGN_BUILD%"=="1" (
    uv run python scripts\build\build_exe.py --sign
) else (
    uv run python scripts\build\build_exe.py
)
if errorlevel 1 (
    echo ERROR: Failed to build executable
    pause
    exit /b 1
)
echo   - Executable created
echo.

echo Step 3: Verifying onedir build...
if exist "dist\SmartCitizen\" (
    echo   - Build folder exists: OK
) else (
    echo   - ERROR: Build folder not found at dist\SmartCitizen\
    pause
    exit /b 1
)
echo.

echo Step 4: Creating installer (requires Inno Setup)...
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"  set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe

if "%ISCC%"=="" (
    echo WARNING: Inno Setup not found
    echo Skipping installer creation
    echo You can install Inno Setup from: https://jrsoftware.org/isdl.php
    echo Or create the installer manually by opening installer.iss
) else (
    "%ISCC%" installer.iss
    if errorlevel 1 (
        echo WARNING: Installer creation failed
        echo You can create it manually with Inno Setup
    ) else (
        echo   - Installer created successfully!
    )
)
echo.

if "%SIGN_BUILD%"=="1" (
    echo Step 5: Signing installer...
    for %%f in (dist\SmartCitizen-*-Setup.exe) do (
        uv run python scripts\build\build_exe.py --sign-file "%%f"
        if errorlevel 1 (
            echo ERROR: Failed to sign installer
            pause
            exit /b 1
        )
    )
    echo.
)

echo ========================================
echo Build Complete!
echo ========================================
echo.
echo Outputs:
for %%f in (dist\SmartCitizen-*-Setup.exe) do (
    echo   [OK] Installer: %%f
)
echo.
echo Next steps:
echo   1. Test the installer: dist\SmartCitizen-*-Setup.exe
echo   2. Upload the installer to GitHub releases!
echo.
pause
