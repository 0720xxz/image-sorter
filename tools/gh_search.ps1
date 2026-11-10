# 用服务器出口检索 GitHub，规避本机 IP 的 API 限速。
$ProgressPreference = 'SilentlyContinue'
$queries = @('photo organizer exif', 'sort photos by date', 'photo sorter', 'photo library organize')
foreach ($q in $queries) {
    $encoded = [uri]::EscapeDataString($q)
    Write-Output "## $q"
    try {
        $url = "https://api.github.com/search/repositories?q=$encoded&sort=stars&per_page=6"
        $r = Invoke-RestMethod -Uri $url -Headers @{ 'User-Agent' = 'image-sorter' } -TimeoutSec 30
        foreach ($item in $r.items) {
            $lang = if ($item.language) { $item.language } else { '-' }
            Write-Output ("{0} | {1} | {2}" -f $item.stargazers_count, $item.full_name, $lang)
        }
    } catch {
        Write-Output ("ERR " + $_.Exception.Message)
    }
    Start-Sleep -Seconds 2
}
