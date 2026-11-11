Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Everlake Launcher'
$form.ClientSize = New-Object System.Drawing.Size(510, 165)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false

$eraContent = New-Object System.Windows.Forms.CheckBox
$eraContent.Text = 'Era content'
$eraContent.SetBounds(16, 14, 200, 24)

$location = New-Object System.Windows.Forms.TextBox
$location.SetBounds(16, 52, 383, 24)
$location.AccessibleName = 'Era checkout folder'
if ($env:EVERLAKE_ERA_DIR) {
    $location.Text = $env:EVERLAKE_ERA_DIR
} elseif (Test-Path 'profiles/targets.json' -PathType Leaf) {
    $location.Text = (Get-Location).Path
} else {
    $location.Text = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..\everlake-era'))
}

$browse = New-Object System.Windows.Forms.Button
$browse.Text = 'Browse...'
$browse.SetBounds(411, 50, 83, 26)
$browse.Add_Click({
    $picker = New-Object System.Windows.Forms.FolderBrowserDialog
    try {
        $picker.Description = 'Select the everlake-era checkout'
        if ($picker.ShowDialog($form) -eq 'OK') { $location.Text = $picker.SelectedPath }
    } finally {
        $picker.Dispose()
    }
})

$download = New-Object System.Windows.Forms.Button
$download.Text = 'Download maps'
$download.SetBounds(16, 108, 125, 30)

$status = New-Object System.Windows.Forms.Button
$status.Text = 'Check progress'
$status.SetBounds(152, 108, 125, 30)

function Update-EraControls {
    $location.Enabled = $eraContent.Checked
    $browse.Enabled = $eraContent.Checked
    $download.Enabled = $eraContent.Checked
    $status.Enabled = $eraContent.Checked
}

function Start-EraCommand([string]$command) {
    $checkout = $location.Text.Trim()
    if (!$checkout -or !(Test-Path -LiteralPath (Join-Path $checkout 'profiles/targets.json') -PathType Leaf)) {
        [void][System.Windows.Forms.MessageBox]::Show($form, 'Select the everlake-era checkout folder.', 'Era content')
        return
    }
    $launcher = Join-Path $PSScriptRoot 'everlake-client.cmd'
    $env:EVERLAKE_ERA_DIR = $checkout
    $env:EVERLAKE_WINDOWS_LAUNCHER = $launcher
    Start-Process -FilePath $env:ComSpec -ArgumentList '/d', '/v:off', '/k', ('call "%EVERLAKE_WINDOWS_LAUNCHER%" ' + $command)
}

$eraContent.Add_CheckedChanged({ Update-EraControls })
$download.Add_Click({ Start-EraCommand 'era-maps' })
$status.Add_Click({ Start-EraCommand 'era-maps-status' })
$form.Controls.AddRange(@($eraContent, $location, $browse, $download, $status))
Update-EraControls
[void]$form.ShowDialog()
