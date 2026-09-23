#Requires -Version 5.1
# myPA Windows installer — permission-first, no silent installs.
# Started by double-clicking Setup-myPA.bat
Write-Host "=== myPA Windows setup ==="
python --version
$ans = Read-Host "Install myPA Python package (pip install -e .)? [y/N]"
if ($ans -match '^(y|yes)$') { python -m pip install -e . } else { Write-Host "Skipped." }
$ans2 = Read-Host "Run setup wizard (providers, Ollama local models, keys)? [Y/n]"
if ($ans2 -match '^(n|no)$') { Write-Host "Run 'python setup_wizard.py' later." } else { python setup_wizard.py }
$ans3 = Read-Host "Create mypa.bat launcher + Start Menu/Desktop shortcuts? [Y/n]"
if ($ans3 -match '^(n|no)$') { Write-Host "Skipped shortcuts." } else { python setup_win.py --shortcuts-only }
Write-Host "Done. Double-click mypa.bat or run: python -m mypa --web"
