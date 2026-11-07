@echo off
setlocal enabledelayedexpansion

:: ============================================================================
::  Batch AI Image Generator - release build
::
::  Produces  dist\Batch AI Image Generator\  ready to zip and upload.
::
::  IMPORTANT: this script deliberately does NOT copy config.json or
::  credentials.json into the release. Those sit beside the program during
::  development and contain your real API keys. Copying them into a public
::  zip is the single most likely way a token leaks, so the script checks
::  for them at the end and refuses to look like it succeeded if they show up.
:: ============================================================================

set PROJECT_NAME=Batch AI Image Generator
set DIST_DIR=dist\%PROJECT_NAME%

echo.
echo === Building %PROJECT_NAME% ===
echo.

:: --- Clean previous build artifacts ---------------------------------------
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "build"      rmdir /s /q "build"
if exist "dist"       rmdir /s /q "dist"
if exist "%PROJECT_NAME%.spec" del /q "%PROJECT_NAME%.spec"

:: --- Compile ---------------------------------------------------------------
echo [1/4] Running PyInstaller...
:: The excludes are dead weight, not dependencies: nothing in core/gui/utils
:: imports them, but PyInstaller follows Pillow's optional hooks into whatever
:: the dev Python has installed and bundled ~20 MB of them (matplotlib alone
:: 11 MB). Verified safe by running the full test suite with all five blocked.
pyinstaller --onedir --windowed --noconfirm ^
  --icon "assets\icon.ico" ^
  --add-data "assets\icon.ico;." ^
  --hidden-import ttkbootstrap ^
  --hidden-import PIL ^
  --hidden-import PIL.Image ^
  --hidden-import httpx ^
  --exclude-module matplotlib ^
  --exclude-module numpy ^
  --exclude-module IPython ^
  --exclude-module jedi ^
  --exclude-module parso ^
  --name "%PROJECT_NAME%" ^
  main.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED - PyInstaller returned an error.
    pause
    exit /b 1
)

if not exist "%DIST_DIR%\%PROJECT_NAME%.exe" (
    echo.
    echo BUILD FAILED - no exe was produced at "%DIST_DIR%\%PROJECT_NAME%.exe"
    pause
    exit /b 1
)

:: --- Assemble the release folder ------------------------------------------
:: The exe looks for guide.md, recipes.md and assets\icon.ico beside itself at
:: runtime: the Help button opens the guide, the Helpers tab is BUILT from
:: recipes.md (parsed at load -- see core/recipes.py), and the window icon
:: loads from assets. Ship all three or those features break in the release
:: while working perfectly from source.
echo [2/4] Copying documentation and assets...
:: The "!" in this filename is eaten by ENABLEDELAYEDEXPANSION -- "!START HERE.png!"
:: parses as a delayed variable reference and expands to nothing, so the copy
:: silently did nothing and the file was missing from every release built this
:: way. Toggle delayed expansion off for just this line; the LEAK check below
:: genuinely needs it, so it cannot simply be disabled for the whole script.
setlocal disabledelayedexpansion
copy /y "!START HERE.png"  "%DIST_DIR%\!START HERE.png"  >nul
endlocal
copy /y "guide.md"  "%DIST_DIR%\guide.md"  >nul
copy /y "readme.md" "%DIST_DIR%\readme.md" >nul
:: promo.md is DEV-ONLY and must never ship: it is store copy, the marketing
:: plan and the pricing strategy, none of which is a customer's business.
copy /y "changelog.md" "%DIST_DIR%\changelog.md" >nul
copy /y "prompting.md" "%DIST_DIR%\prompting.md" >nul
:: Not just docs: the Helpers tab parses this at runtime. See core/recipes.py.
copy /y "recipes.md"   "%DIST_DIR%\recipes.md"   >nul
:: The two setup pages. Both open offline: no CDN, no webfont, no remote asset.
:: Both show screenshots from promo\ (GUI tabs) and promo\!cloudflare info\, which
:: the promo copy below puts in the same release folder -- so these must stay
:: on the same side of that copy. Their prices are baked in but pinned by
:: test_setup_pages_quote_the_registrys_own_prices, which fails if a figure in
:: core/models.py moves and a page still quotes the old one.
copy /y "1 first time setup tutorial.html" "%DIST_DIR%\1 first time setup tutorial.html" >nul
copy /y "2 advanced usage tutorial.html"    "%DIST_DIR%\2 advanced usage tutorial.html"    >nul

mkdir "%DIST_DIR%\assets"
copy /y "assets\icon.ico" "%DIST_DIR%\assets\icon.ico" >nul
:: The setup pages use this as their masthead art, so it is a shipped
:: asset now rather than just the icon master.
copy /y "assets\icon og (2).jpg" "%DIST_DIR%\assets\icon og (2).jpg" >nul

:: /e copies SUBDIRECTORIES too. Without it only the top-level files ship, and
:: "promo\!cloudflare info\" -- the step-by-step setup screenshots that
:: guide.md points customers at by name -- silently does not. Verified 2026-09-06.
mkdir "%DIST_DIR%\promo"
xcopy /q /y /e "promo\*" "%DIST_DIR%\promo\" >nul

:: Example files so the expected prompt-file format is obvious
copy /y "test_prompts.txt"           "%DIST_DIR%\example_prompts.txt"     >nul
copy /y "test_style_prompt_addon.txt" "%DIST_DIR%\example_style_suffix.txt" >nul

:: --- Ship the source too ---------------------------------------------------
:: cli.py is a documented, supported second front end, and publishing the
:: source is what lets a cautious user verify where their API token goes.
echo [3/4] Copying source (CLI front end + engine)...

copy /y "cli.py"  "%DIST_DIR%\cli.py"  >nul
copy /y "main.py" "%DIST_DIR%\main.py" >nul

for %%D in (core gui utils) do (
    xcopy /q /y /e /i "%%D" "%DIST_DIR%\%%D" >nul
)

:: Strip every __pycache__ that xcopy carried across, at any depth.
:: A plain "for /d /r" only walks directories that still exist when the loop
:: starts, so nested ones get missed -- collect the paths first, then delete.
for /f "delims=" %%P in ('dir /s /b /ad "%DIST_DIR%\__pycache__" 2^>nul') do (
    if exist "%%P" rmdir /s /q "%%P"
)

:: --- Safety check ----------------------------------------------------------
echo [4/4] Checking for secrets...

set LEAK=0
if exist "%DIST_DIR%\credentials.json" set LEAK=1
if exist "%DIST_DIR%\config.json"      set LEAK=1
:: The one-off prompt box persists here. A user file, not a shipped one.
if exist "%DIST_DIR%\single_custom.txt" set LEAK=1

if "!LEAK!"=="1" (
    echo.
    echo ************************************************************
    echo  STOP - credentials.json, config.json or single_custom.txt
    echo  is in the release folder. DO NOT ZIP OR UPLOAD IT. Delete
    echo  those files from "%DIST_DIR%" first.
    echo ************************************************************
    pause
    exit /b 1
)

:: --- Tidy PyInstaller working dirs ----------------------------------------
if exist "build" rmdir /s /q "build"
if exist "%PROJECT_NAME%.spec" del /q "%PROJECT_NAME%.spec"

echo.
echo ============================================================
echo  Done. Release folder:
echo    %DIST_DIR%
echo.
echo  No credentials found in the release - safe to zip.
echo.
echo  Next steps:
echo    1. Test the exe from a DIFFERENT folder than this one,
echo       so it cannot pick up your dev config.json.
echo    2. Zip the "%PROJECT_NAME%" folder inside dist\.
echo    3. Upload to itch.io.
echo ============================================================
echo.
pause
