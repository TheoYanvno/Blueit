# Builds dist\Blueit.exe on Windows with PyInstaller. Run from the Blueit folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# The React page is already built in blueit\static, so Node isn't needed unless you change ui\.
$ErrorActionPreference = "Stop"
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --name Blueit `
  --add-data "blueit\static;blueit\static" `
  packaging\blueit_app.py
Copy-Item blueit.example.toml dist\blueit.example.toml -Force
Write-Host "Built dist\Blueit.exe"
