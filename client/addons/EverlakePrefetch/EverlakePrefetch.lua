-- Gate 2 test (docs/custom-files.md). A map's world file is read the moment the map loads and must already be
-- stored locally, while files asked for in the background are streamed from the CDN and then kept. This asks for
-- every added file as a texture: the files aren't textures, so nothing shows, but the client streams and keeps
-- each one. EverlakePrefetchList is written by "everlake-client.sh gate2" from the server's build.json.
local holder = CreateFrame("Frame", nil, UIParent)
holder:SetSize(1, 1)
holder:SetPoint("BOTTOMLEFT")
holder:SetAlpha(0.01)

local function prefetch()
    local list = EverlakePrefetchList or {}
    for _, fileID in ipairs(list) do
        local t = holder:CreateTexture()
        t:SetSize(1, 1)
        t:SetPoint("BOTTOMLEFT")
        t:SetTexture(fileID)
    end
    print(("|cff33ccff[Everlake]|r asked the client for %d added files. Give it 20 seconds, then teleport."):format(#list))
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent", prefetch)

SLASH_EVERLAKEPREFETCH1 = "/prefetch"
SlashCmdList.EVERLAKEPREFETCH = prefetch
