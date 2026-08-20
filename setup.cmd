@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "LAGNIAPPE_VENV_DIR=%~dp0venv"
set "LAGNIAPPE_VENV_PYTHON=%~dp0venv\Scripts\python.exe"

if not exist "%LAGNIAPPE_VENV_PYTHON%" goto prepare_environment

"%LAGNIAPPE_VENV_PYTHON%" -E -c "import pathlib, sys; base=str(pathlib.Path(sys.base_prefix)).lower(); unsafe='google-cloud-sdk' in base and 'bundledpython' in base; raise SystemExit(42 if unsafe else 0)" >nul 2>nul
if "%errorlevel%"=="42" goto replace_cloud_sdk_environment
if errorlevel 1 goto environment_failed
goto run_setup

:replace_cloud_sdk_environment
echo Replacing Lagniappe's generated Python environment...
rmdir /s /q "%LAGNIAPPE_VENV_DIR%"
if exist "%LAGNIAPPE_VENV_DIR%" goto environment_failed

:prepare_environment
echo Preparing Lagniappe's isolated Python environment...
set "LAGNIAPPE_BOOTSTRAP_PYTHON="

:try_python_launcher
where py >nul 2>nul
if errorlevel 1 goto try_local_python
py -3 -E -c "import pathlib, sys; base=str(pathlib.Path(sys.base_prefix)).lower(); unsafe='google-cloud-sdk' in base and 'bundledpython' in base; raise SystemExit(sys.version_info < (3, 12) or unsafe)" >nul 2>nul
if not errorlevel 1 goto create_with_launcher

:try_local_python
for %%V in (314 313 312) do if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
    set "LAGNIAPPE_BOOTSTRAP_PYTHON=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
    goto create_with_path
)

:try_python
where python >nul 2>nul
if errorlevel 1 goto try_python3
python -E -c "import pathlib, sys; base=str(pathlib.Path(sys.base_prefix)).lower(); unsafe='google-cloud-sdk' in base and 'bundledpython' in base; raise SystemExit(sys.version_info < (3, 12) or unsafe)" >nul 2>nul
if not errorlevel 1 goto create_with_python

:try_python3
where python3 >nul 2>nul
if errorlevel 1 goto install_python
python3 -E -c "import pathlib, sys; base=str(pathlib.Path(sys.base_prefix)).lower(); unsafe='google-cloud-sdk' in base and 'bundledpython' in base; raise SystemExit(sys.version_info < (3, 12) or unsafe)" >nul 2>nul
if not errorlevel 1 goto create_with_python3

:install_python
where winget >nul 2>nul
if errorlevel 1 goto missing_python
echo.
set "LAGNIAPPE_INSTALL_PYTHON="
set /p "LAGNIAPPE_INSTALL_PYTHON=Install standalone Python 3.14 for this Windows user now? [Y/n]: "
if /i "%LAGNIAPPE_INSTALL_PYTHON%"=="n" goto missing_python
winget install --id Python.Python.3.14 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
if errorlevel 1 goto python_install_failed
set "LAGNIAPPE_BOOTSTRAP_PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%LAGNIAPPE_BOOTSTRAP_PYTHON%" goto create_with_path
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Python\PythonCore\3.14\InstallPath" /ve 2^>nul ^| findstr /i "REG_SZ"') do set "LAGNIAPPE_BOOTSTRAP_PYTHON=%%Bpython.exe"
if defined LAGNIAPPE_BOOTSTRAP_PYTHON if exist "%LAGNIAPPE_BOOTSTRAP_PYTHON%" goto create_with_path
goto python_install_failed

:missing_python
echo.
echo Lagniappe requires standalone Python 3.12 or newer.
echo Install Python from https://www.python.org/downloads/windows/ and run
echo setup.cmd again.
exit /b 1

:python_install_failed
echo.
echo WinGet could not install or locate Python 3.14.
echo Install Python from https://www.python.org/downloads/windows/ and run
echo setup.cmd again.
exit /b 1

:create_with_path
"%LAGNIAPPE_BOOTSTRAP_PYTHON%" -E -m venv "%~dp0venv"
if errorlevel 1 goto environment_failed
goto check_environment

:create_with_launcher
py -3 -E -m venv "%~dp0venv"
if errorlevel 1 goto environment_failed
goto check_environment

:create_with_python
python -E -m venv "%~dp0venv"
if errorlevel 1 goto environment_failed
goto check_environment

:create_with_python3
python3 -E -m venv "%~dp0venv"
if errorlevel 1 goto environment_failed

:check_environment
if not exist "%LAGNIAPPE_VENV_PYTHON%" goto environment_failed
"%LAGNIAPPE_VENV_PYTHON%" -E -c "import sys; paths=[str(path).lower() for path in sys.path]; raise SystemExit(any('google-cloud-sdk' in path and 'bundledpython' in path for path in paths))" >nul 2>nul
if errorlevel 1 goto contaminated_environment
echo Lagniappe's isolated Python environment is ready.
echo.
goto run_setup

:contaminated_environment
echo.
echo The new Python environment could not be isolated.
echo Install or repair standalone Python, then run setup.cmd again.
exit /b 1

:environment_failed
echo.
echo Python could not create Lagniappe's isolated environment.
echo Repair or reinstall standalone Python, then run setup.cmd again.
exit /b 1

:run_setup
"%LAGNIAPPE_VENV_PYTHON%" -E -m installer %*
exit /b %errorlevel%
