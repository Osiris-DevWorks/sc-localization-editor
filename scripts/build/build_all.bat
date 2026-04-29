@echo off
echo ========================================
echo Smart Citizen - Build Script
echo ========================================
echo.

echo Step 1: Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo   - Old builds removed
echo.

echo Step 2: Building executable...
uv run python scripts\build\build_exe.py
if errorlevel 1 (
    echo ERROR: Failed to build executable
    pause
    exit /b 1
)
echo   - Executable created
echo.

echo Step 3: Verifying onedir build...
if exist "dist\SmartCitizen-v*\" (
    echo   - Build folder exists: OK
) else (
    echo   - ERROR: Build folder not found!
    pause
    exit /b 1
)
echo.

echo Step 4: Creating installer (requires Inno Setup)...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
    if errorlevel 1 (
        echo WARNING: Installer creation failed
        echo You can create it manually with Inno Setup
    ) else (
        echo   - Installer created successfully!
    )
) else (
    echo WARNING: Inno Setup not found at default location
    echo Skipping installer creation
    echo You can install Inno Setup from: https://jrsoftware.org/isdl.php
    echo Or create the installer manually by opening installer.iss
)
echo.

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
