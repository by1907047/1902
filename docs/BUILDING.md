# Building

## Toolchain

The archived Windows build used the EWDK 10.0.26100 toolchain, KMDF 1.31 and NetAdapterCx 2.4 for x64. Use the official EWDK build environment; Python/Clang CI does not produce a Windows driver. A separately installed Visual Studio/WDK environment must supply equivalent MSBuild, C++ and driver dependencies and has not been verified here.

Use a neutral local path such as `C:\build\apple1902`. The old build embedded its original directory in WPP/debug strings; omitting the PDB from a download does not remove those strings from the SYS. Keep this in mind before releasing artifacts.

## Unsigned build

From the EWDK command prompt, at the repository root:

```bat
set "Inf2CatUseLocalTime=true"
call NCM-Driver-for-Windows\scripts\build-1902.cmd
```

The helper rebuilds Debug and Release x64 with code analysis, `SignMode=Off`, `/nr:false` and limited parallelism. It does not sign, trust, install, restart a device, or change boot policy. `Inf2CatUseLocalTime` addresses an observed StampInf/Inf2Cat local-date mismatch; inspect the generated INF date rather than suppressing catalog errors.

The source INF intentionally leaves DriverVer and KMDF substitutions for the build tools. Use the generated package, not the source INF. Preserve the MSBuild exit code and logs, then locate the matching SYS/INF/CAT/PDB output for each configuration. Run the kit's InfVerif on each generated INF, verify the catalog and inspect all diagnostics before considering a package usable.

## Known build limitations

The archived Debug/Release logs had zero errors and **70/68 warnings** respectively. These are not a warning-free build or a certification result. The explicit `SidelineCompileOnly=true` property relaxes warnings-as-errors only in the vendored DMF Release x64 project; it does not disable driver code analysis or globally suppress warnings.

This publication preserves the source used by the archived candidate. No new Windows native build was performed for this source-only release. Build success alone is not proof of driver load, recovery, memory safety or HVCI compatibility.

For future binary publication, record compiler/kit versions, source commit and file hashes; check SYS and PDB strings for personal paths; sign only the exact frozen package; verify it; and repeat hardware tests. Never patch a signed SYS to remove a path or replace an INF without rebuilding its catalog.
