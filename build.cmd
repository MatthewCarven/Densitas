@echo off
REM ============================================================================
REM Densitas - build & test helper.
REM
REM Usage:
REM   build.cmd            (default) - create .venv, install deps, run tests
REM   build.cmd --exe      - everything above, plus PyInstaller exe to dist\
REM   build.cmd --clean    - remove .venv, dist\, build\, *.spec, then exit
REM
REM Idempotent. Re-run any time. Safe to commit nothing it produces;
REM .venv, build\, dist\, and *.spec are all .gitignored.
REM ============================================================================

setlocal EnableDelayedExpansion
pushd "%~dp0"

REM ---- Parse args -----------------------------------------------------------
set DO_EXE=0
set DO_CLEAN=0
if "%~1"=="--exe"   set DO_EXE=1
if "%~1"=="--clean" set DO_CLEAN=1

REM ---- Clean ----------------------------------------------------------------
if %DO_CLEAN%==1 (
    echo [build.cmd] cleaning .venv\, dist\, build\, *.spec...
    if exist ".venv" rmdir /s /q ".venv"
    if exist "dist"  rmdir /s /q "dist"
    if exist "build" rmdir /s /q "build"
    del /q *.spec 2>nul
    echo [build.cmd] clean complete.
    popd
    endlocal
    exit /b 0
)

REM ---- Create venv if missing ----------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [build.cmd] creating .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [build.cmd] FAILED to create .venv. Is Python on PATH?
        popd & endlocal & exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

REM ---- Install / upgrade deps ----------------------------------------------
echo [build.cmd] installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [build.cmd] FAILED to install requirements.
    popd & endlocal & exit /b 1
)

REM ---- Run tests ------------------------------------------------------------
echo.
echo [build.cmd] running test_world.py...
python tests\test_world.py
if errorlevel 1 (
    echo [build.cmd] test_world.py FAILED.
    popd & endlocal & exit /b 1
)

echo.
echo [build.cmd] running test_citizen.py...
python tests\test_citizen.py
if errorlevel 1 (
    echo [build.cmd] test_citizen.py FAILED.
    popd & endlocal & exit /b 1
)

REM ---- Optional: PyInstaller exe -------------------------------------------
if %DO_EXE%==1 (
    echo.
    echo [build.cmd] building exe via PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [build.cmd] FAILED to install pyinstaller.
        popd & endlocal & exit /b 1
    )
    REM Use entry.py as the PyInstaller target so relative imports work.
    pyinstaller --onefile --windowed --name Densitas ^
                --add-data "config.toml;." ^
                entry.py
    if errorlevel 1 (
        echo [build.cmd] pyinstaller FAILED.
        popd & endlocal & exit /b 1
    )
    echo.
    echo [build.cmd] exe built: dist\Densitas.exe
)

echo.
echo [build.cmd] OK.
popd
endlocal
exit /b 0
