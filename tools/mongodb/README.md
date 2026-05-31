# Portable MongoDB Bundle

The customer installer/startup flow expects the portable MongoDB runtime here:

```text
tools\mongodb\bin\mongod.exe
```

For final customer packaging, include the extracted MongoDB Community Server ZIP contents in this folder. The setup script also has an official ZIP fallback that fills this folder automatically when the bundle is missing, without installing MongoDB as a Windows Service.

Runtime database files are not stored here. They are created per Windows user under:

```text
%LOCALAPPDATA%\FiverrLeadCRM\data\db
%LOCALAPPDATA%\FiverrLeadCRM\logs\mongod.log
```
