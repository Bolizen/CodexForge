$ErrorActionPreference = "Stop"

$payloadJson = $env:GLACIAL_PORTABLE_ZIP_VALIDATION_JSON
if (-not $payloadJson) {
    throw "GLACIAL_PORTABLE_ZIP_VALIDATION_JSON is required."
}

$payload = $payloadJson | ConvertFrom-Json
$operation = [string] $payload.operation
$archive = [System.IO.Path]::GetFullPath([string] $payload.archive)
if ($operation -ne "create" -and -not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    throw "The portable ZIP does not exist."
}

switch ($operation) {
    "create" {
        if (Test-Path -LiteralPath $archive) {
            throw "The portable ZIP already exists."
        }
        $source = [System.IO.Path]::GetFullPath([string] $payload.source)
        if (-not (Test-Path -LiteralPath $source -PathType Container)) {
            throw "The portable source directory does not exist."
        }
        $archiveParent = Split-Path -Parent $archive
        if (-not (Test-Path -LiteralPath $archiveParent -PathType Container)) {
            throw "The portable ZIP parent directory does not exist."
        }

        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $sourcePrefix = $source.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
        $files = @(Get-ChildItem -LiteralPath $source -Recurse -File | Sort-Object FullName)
        if ($files.Count -eq 0) {
            throw "The portable source directory contains no files."
        }
        $zip = [System.IO.Compression.ZipFile]::Open($archive, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($file in $files) {
                if (-not $file.FullName.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "A portable source file escaped the source directory."
                }
                $entryName = $file.FullName.Substring($sourcePrefix.Length).Replace("\", "/")
                if (-not $entryName -or $entryName.StartsWith("./") -or $entryName.StartsWith("/") -or $entryName.Contains("../")) {
                    throw "A portable source file produced an unsafe ZIP entry name."
                }
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $zip,
                    $file.FullName,
                    $entryName,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
        }
        finally {
            $zip.Dispose()
        }
        [pscustomobject]@{ CreatedEntries = $files.Count } | ConvertTo-Json -Compress
    }
    "inspect" {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::OpenRead($archive)
        try {
            $entries = @($zip.Entries | ForEach-Object { $_.FullName })
        }
        finally {
            $zip.Dispose()
        }

        $shell = New-Object -ComObject Shell.Application
        $shellFolder = $shell.NameSpace($archive)
        $shellItemCount = if ($null -eq $shellFolder) { -1 } else { $shellFolder.Items().Count }
        [pscustomobject]@{
            Entries = $entries
            ExplorerShellItemCount = $shellItemCount
        } | ConvertTo-Json -Compress -Depth 4
    }
    "expand" {
        $destination = [System.IO.Path]::GetFullPath([string] $payload.destination)
        if (Test-Path -LiteralPath $destination) {
            throw "The Expand-Archive destination already exists."
        }
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            throw "The Expand-Archive destination parent does not exist."
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $destination
        [pscustomobject]@{ Expanded = $true } | ConvertTo-Json -Compress
    }
    default {
        throw "Unknown portable ZIP validation operation."
    }
}
