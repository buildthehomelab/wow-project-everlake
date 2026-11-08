-- Classic hotfix test (docs/classic-on-forever.md): realm 2 "Everlake Two" sends about 89,000 hotfix rows that turn
-- Forever's spells, items and skills into Classic Era's; realm 1 "Everlake" sends Forever's own. At every login this
-- reads probes whose value differs between the two, compares them with what this realm should show, prints the verdict
-- in chat and keeps it in EverlakeClassic1DB (account-wide, written at logout or /reload). /elc checks by hand.
local CLASSIC_REALM = "Everlake Two"
-- Each probe: what Forever shows and what Classic Era shows (from the two builds' tables, 2026-11-08).
local PROBES = {
    -- spell text Classic changed (Spell, a hotfix_blob row)
    { key = "removeCurse", kind = "text", id = 475, forever = "Curse or Bane", classic = "Removes %d+ Curse from" },
    { key = "prayerHealing", kind = "text", id = 596, forever = "heals the target and their party",
      classic = "prayer heals party members within" },
    -- spells Forever removed and Classic has (SpellName + Spell + SpellMisc ... rows added)
    { key = "salvation", kind = "spell", id = 1038, forever = nil, classic = "Blessing of Salvation" },
    { key = "elements", kind = "spell", id = 1490, forever = nil, classic = "Curse of the Elements" },
    { key = "detectMagic", kind = "spell", id = 2855, forever = nil, classic = "Detect Magic" },
    -- item levels Classic changed (ItemSparse)
    { key = "signet", kind = "ilvl", id = 18403, forever = 65, classic = 74 },
    { key = "alchStone", kind = "ilvl", id = 13503, forever = 50, classic = 60 },
}
local MAX_LOGINS, MAX_ERRORS = 60, 60

local db
local pendingErrors = {}
local loadedAt = GetTime()

local function v(x)
    if x == nil then return "nil" end
    return tostring(x)
end

local function say(text) print("|cff33ccff[Everlake Classic 1]|r " .. text) end

local previousHandler = geterrorhandler()
seterrorhandler(function(msg, ...)
    pcall(function()
        local list = db and db.errors or pendingErrors
        list[#list + 1] = date("%H:%M:%S") .. " " .. tostring(msg)
        while #list > MAX_ERRORS do table.remove(list, 1) end
    end)
    if previousHandler then return previousHandler(msg, ...) end
end)

local function read(p)
    if p.kind == "spell" then
        if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(p.id) end
        return (GetSpellInfo(p.id))
    elseif p.kind == "text" then
        local ok, text = pcall(function() return C_Spell.GetSpellDescription(p.id) end)
        return ok and text or nil
    elseif p.kind == "ilvl" then
        if C_Item and C_Item.RequestLoadItemDataByID then C_Item.RequestLoadItemDataByID(p.id) end
        local info = { (C_Item and C_Item.GetItemInfo or GetItemInfo)(p.id) }
        return info[4]
    end
end

-- which side a value belongs to: "forever", "classic", "both" (can't tell) or "neither"
local function side(p, value)
    local function is(expect)
        if p.kind == "text" then return value ~= nil and expect ~= nil and string.find(value, expect) ~= nil end
        return value == expect
    end
    local f, c = is(p.forever), is(p.classic)
    if p.kind == "text" and value ~= nil and not f and not c then return "neither" end
    if f and c then return "both" end
    return f and "forever" or c and "classic" or "neither"
end

local function check(label)
    local realm = GetRealmName() or "?"
    local want = realm == CLASSIC_REALM and "classic" or "forever"
    local got, wrong, pending = {}, {}, 0
    for _, p in ipairs(PROBES) do
        local value = read(p)
        local s = side(p, value)
        if p.kind == "ilvl" and value == nil then
            pending = pending + 1
            s = "pending"
        end
        got[#got + 1] = ("%s=%s"):format(p.key, s)
        if s ~= want and s ~= "both" and s ~= "pending" then
            wrong[#wrong + 1] = ("%s %d shows %s ('%s')"):format(p.key, p.id, s, string.sub(v(value), 1, 60))
        end
    end
    local entry = {
        time = date("%Y-%m-%d %H:%M:%S"), label = label, realm = realm, expected = want,
        character = (UnitName("player") or "?") .. " level " .. v(UnitLevel("player")),
        secondsSinceAddonLoad = math.floor(GetTime() - loadedAt),
        verdict = #wrong > 0 and "MIXED" or pending > 0 and "PENDING" or "OK",
        wrong = table.concat(wrong, "; "),
        seen = table.concat(got, ", "),
        luaMemoryKB = math.floor(collectgarbage("count")),
    }
    if db then
        db.logins[#db.logins + 1] = entry
        while #db.logins > MAX_LOGINS do table.remove(db.logins, 1) end
    end
    if entry.verdict == "OK" then
        say(("|cff33ff33OK|r on %s: all %s (%s)."):format(realm, want, entry.seen))
    elseif entry.verdict == "PENDING" then
        say(("|cffffff33PENDING|r on %s: item data still loading (%s)."):format(realm, entry.seen))
    else
        say(("|cffff3333MIXED|r on %s, expected %s: %s"):format(realm, want, entry.wrong))
    end
    return entry
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" then
        if name ~= "EverlakeClassic1" then return end
        EverlakeClassic1DB = EverlakeClassic1DB or {}
        db = EverlakeClassic1DB
        db.logins = db.logins or {}
        db.errors = db.errors or {}
        for _, e in ipairs(pendingErrors) do db.errors[#db.errors + 1] = e end
        pendingErrors = {}
    elseif event == "PLAYER_LOGIN" then
        -- item data may load a little later: check after 5 s and again after 30 s
        C_Timer.After(5, function() check("login") end)
        C_Timer.After(30, function() check("login+30s") end)
    end
end)

SLASH_EVERLAKECLASSIC11 = "/elc"
SlashCmdList.EVERLAKECLASSIC1 = function()
    check("manual")
    say("saved; /reload or log out writes it to disk.")
end
