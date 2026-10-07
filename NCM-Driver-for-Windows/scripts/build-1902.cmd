@echo off
setlocal
rem Run only from the official EWDK build environment. No install/signing step.
pushd "%~dp0.."
call msbuild projects\host\host.vcxproj /t:Rebuild /p:Configuration=Debug /p:Platform=x64 /p:SignMode=Off /p:RunCodeAnalysis=true /p:SidelineCompileOnly=true /nr:false /m:2 /fl /flp:logfile=build-1902-Debug.log
if errorlevel 1 goto failed
call msbuild projects\host\host.vcxproj /t:Rebuild /p:Configuration=Release /p:Platform=x64 /p:SignMode=Off /p:RunCodeAnalysis=true /p:SidelineCompileOnly=true /nr:false /m:2 /fl /flp:logfile=build-1902-Release.log
if errorlevel 1 goto failed
popd
echo NCM_BUILD_EXIT=0
exit /b 0
:failed
set "NCM_BUILD_EXIT=%errorlevel%"
popd
echo NCM_BUILD_EXIT=%NCM_BUILD_EXIT%
exit /b %NCM_BUILD_EXIT%
