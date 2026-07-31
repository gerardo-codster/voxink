; NSIS Installer Script for Voxink (Windows)
; 
; This creates a proper Windows installer (.exe) with:
; - Install wizard
; - Start Menu shortcut
; - Desktop shortcut (optional)
; - Uninstaller
; - Auto-start on login (optional)
;
; Prerequisites: 
;   1. Build the exe first: scripts\build_windows.bat
;   2. Install NSIS: https://nsis.sourceforge.io/
;   3. Run: makensis scripts\installer_windows.nsi

!include "MUI2.nsh"

Name "Voxink"
OutFile "..\dist\VoxinkSetup.exe"
InstallDir "$PROGRAMFILES\Voxink"
InstallDirRegKey HKCU "Software\Voxink" "InstallDir"
RequestExecutionLevel user

; UI
!define MUI_ICON "..\assets\icon.ico"
!define MUI_UNICON "..\assets\icon.ico"
!define MUI_ABORTWARNING

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"

Section "Install"
    SetOutPath $INSTDIR
    
    ; Copy the executable
    File "..\dist\voxink.exe"
    File "..\assets\icon.ico"
    
    ; Create uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    ; Start Menu
    CreateDirectory "$SMPROGRAMS\Voxink"
    CreateShortCut "$SMPROGRAMS\Voxink\Voxink.lnk" "$INSTDIR\voxink.exe" "" "$INSTDIR\icon.ico"
    CreateShortCut "$SMPROGRAMS\Voxink\Desinstalar.lnk" "$INSTDIR\uninstall.exe"
    
    ; Desktop shortcut
    CreateShortCut "$DESKTOP\Voxink.lnk" "$INSTDIR\voxink.exe" "" "$INSTDIR\icon.ico"
    
    ; Auto-start on login
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Voxink" "$INSTDIR\voxink.exe"
    
    ; Registry for uninstaller
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Voxink" "DisplayName" "Voxink"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Voxink" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Voxink" "DisplayIcon" "$INSTDIR\icon.ico"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Voxink" "Publisher" "Voxink"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Voxink" "DisplayVersion" "0.1.0"
SectionEnd

Section "Uninstall"
    ; Remove files
    Delete "$INSTDIR\voxink.exe"
    Delete "$INSTDIR\icon.ico"
    Delete "$INSTDIR\uninstall.exe"
    RMDir "$INSTDIR"
    
    ; Remove shortcuts
    Delete "$SMPROGRAMS\Voxink\Voxink.lnk"
    Delete "$SMPROGRAMS\Voxink\Desinstalar.lnk"
    RMDir "$SMPROGRAMS\Voxink"
    Delete "$DESKTOP\Voxink.lnk"
    
    ; Remove auto-start
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Voxink"
    
    ; Remove registry
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Voxink"
    DeleteRegKey HKCU "Software\Voxink"
SectionEnd
