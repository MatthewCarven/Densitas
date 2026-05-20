@echo off
REM ============================================================================
REM Densitas - launch the game.
REM
REM Activates the local virtualenv if one exists (.venv\), then runs the game
REM via "python -m densitas.main". Run from anywhere; the script cd's to the
REM project root automatically.
REM ============================================================================

setlocal

REM cd to the directory this script lives in.
pushd "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [start.cmd] no .venv found. Using system Python.
    echo [start.cmd] run build.cmd first to set up a virtualenv.
    echo.
)

python -m densitas.main
set ERR=%ERRLEVEL%

popd

if not %ERR%==0 (
    echo.
    echo [start.cmd] Densitas exited with code %ERR%.
    pause
)
endlocal
exit /b %ERR%
