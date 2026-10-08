@echo off
rem Build lerd_devtools as a DLL against an official PHP devel pack.
rem
rem   build-devtools-windows.cmd <vcvars64.bat> <toolset> <devel-pack-dir> <ext-src-dir> <staging-dir> <php-sdk-dir>
rem
rem The toolset is picked by build-windows.py: PHP refuses a module linked with a
rem newer MSVC than its core, so 8.1 to 8.3 (VS 2019 cores) need v142 even on a
rem VS 2022 machine. Leaves <staging-dir>\x64\Release\php_lerd_devtools.dll.
setlocal
set VCVARS=%~1
set TOOLSET=%~2
set DEVEL=%~3
set SRC=%~4
set STAGING=%~5
set SDK=%~6

call "%VCVARS%" -vcvars_ver=%TOOLSET% >nul || exit /b 1
rem configure.js insists on bison and re2c even for an extension that uses neither.
set PATH=%SDK%\bin;%SDK%\msys2\usr\bin;%PATH%

if exist "%STAGING%" rmdir /s /q "%STAGING%"
mkdir "%STAGING%" || exit /b 1
copy /y "%SRC%\*.c" "%STAGING%\" >nul || exit /b 1
copy /y "%SRC%\*.h" "%STAGING%\" >nul || exit /b 1
copy /y "%SRC%\config.w32" "%STAGING%\" >nul || exit /b 1

rem phpize.bat changes directory, so every later step names the staging tree.
cd /d "%STAGING%"
call "%DEVEL%\phpize.bat" || exit /b 1
cd /d "%STAGING%"
call "%STAGING%\configure.bat" --enable-lerd-devtools=shared || exit /b 1
nmake /nologo || exit /b 1
