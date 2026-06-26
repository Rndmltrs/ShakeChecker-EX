Add-Type -AssemblyName System.Drawing

Write-Host "Enter input PNG filename (with extension):"
$InputPath = Read-Host

Write-Host "Enter output PNG filename (with extension):"
$OutputPath = Read-Host

if (-Not (Test-Path $InputPath)) {
    Write-Host "ERROR: Input file not found: $InputPath"
    Write-Host "Press Enter to exit..."
    [void][System.Console]::ReadLine()
    exit
}

try {
    $img = [System.Drawing.Bitmap]::FromFile($InputPath)
    $width = $img.Width
    $height = $img.Height

    $grayBmp = New-Object System.Drawing.Bitmap $width, $height

    for ($y = 0; $y -lt $height; $y++) {
        for ($x = 0; $x -lt $width; $x++) {
            $pixel = $img.GetPixel($x, $y)
            $r = $pixel.R
            $g = $pixel.G
            $b = $pixel.B

            # Standard luminance formula
            $gray = [int](0.3 * $r + 0.59 * $g + 0.11 * $b)

            $grayColor = [System.Drawing.Color]::FromArgb($gray, $gray, $gray)
            $grayBmp.SetPixel($x, $y, $grayColor)
        }
    }

    $grayBmp.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $grayBmp.Dispose()
    $img.Dispose()

    Write-Host "SUCCESS: Grayscale image saved to $OutputPath"
}
catch {
    Write-Host "ERROR converting image: $_"
}

Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
