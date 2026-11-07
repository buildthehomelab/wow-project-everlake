-- Gate 5 realm switch test (docs/era-data.md, tests 4-6): one Forever client, two realms that send different data.
--   Everlake (realm 1):                   no Death Knight or Monk; "Attack (realm 1)", "Hearthstone (realm 1)"
--   Everlake Two (realm 2):               Death Knight and Monk with their spells and talent tree;
--                                          "Attack (realm 2)", "Hearthstone (realm 2)"
-- At every login it reads what the client holds for each probe, compares it with what this realm sends, prints the
-- verdict in chat and keeps it in the saved variables EverlakeSwitchDB (account-wide, so one list across both realms;
-- written at logout or /reload). "everlake-client.sh switch" reads it. /els takes a snapshot by hand.
local EXPECT = {
    realm1 = {
        attack = "Attack (realm 1)", hearth = "Hearthstone (realm 1)",
        class6 = nil, class10 = nil, deathCoil = nil, treeNodes = 0,
    },
    realm2 = {
        attack = "Attack (realm 2)", hearth = "Hearthstone (realm 2)",
        class6 = "DEATHKNIGHT", class10 = "MONK", deathCoil = "Death Coil", treeNodes = 53,
    },
}
local MAX_LOGINS, MAX_ERRORS = 60, 60

local db
local pendingErrors = {}

local function v(x)
    if x == nil then return "nil" end
    return tostring(x)
end

local function say(text) print("|cff33ccff[Everlake Switch]|r " .. text) end

local previousHandler = geterrorhandler()
seterrorhandler(function(msg, ...)
    pcall(function()
        local list = db and db.errors or pendingErrors
        list[#list + 1] = date("%H:%M:%S") .. " " .. tostring(msg)
        while #list > MAX_ERRORS do table.remove(list, 1) end
    end)
    if previousHandler then return previousHandler(msg, ...) end
end)

local function spellName(id)
    if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) end
    return (GetSpellInfo(id))
end

local function probe()
    local p = {}
    p.attack = spellName(6603)
    p.hearth = spellName(8690)
    local c6 = C_CreatureInfo and C_CreatureInfo.GetClassInfo(6)
    local c10 = C_CreatureInfo and C_CreatureInfo.GetClassInfo(10)
    p.class6 = c6 and c6.classFile or nil
    p.class10 = c10 and c10.classFile or nil
    p.numClasses = GetNumClasses and GetNumClasses()
    p.deathCoil = spellName(47541)
    local ok, text = pcall(function() return C_Spell.GetSpellDescription(47541) end)
    p.deathCoilText = ok and text and string.sub(text, 1, 60) or ""
    local okTree, nodes = pcall(function() return C_Traits.GetTreeNodes(954100) end)
    p.treeNodes = okTree and nodes and #nodes or 0
    p.deathCoilKnown = IsPlayerSpell and IsPlayerSpell(47541) or false
    return p
end

local function check(label)
    local realm = GetRealmName() or "?"
    local kind = realm == "Everlake Two" and "realm2" or "realm1"
    local expect = EXPECT[kind]
    local p = probe()
    local wrong = {}
    for _, key in ipairs({ "attack", "hearth", "class6", "class10", "deathCoil", "treeNodes" }) do
        if p[key] ~= expect[key] then
            wrong[#wrong + 1] = ("%s is '%s', this realm sends '%s'"):format(key, v(p[key]), v(expect[key]))
        end
    end
    local _, classFile = UnitClass("player")
    local entry = {
        time = date("%Y-%m-%d %H:%M:%S"), label = label, realm = realm, expected = kind,
        character = (UnitName("player") or "?") .. " (" .. v(classFile) .. ", level " .. v(UnitLevel("player")) .. ")",
        verdict = #wrong == 0 and "OK" or "MIXED",
        wrong = table.concat(wrong, "; "),
        seen = ("attack '%s', hearthstone '%s', class 6 %s, class 10 %s, %s classes, Death Coil '%s' known %s text '%s', tree 954100 %d nodes")
            :format(v(p.attack), v(p.hearth), v(p.class6), v(p.class10), v(p.numClasses), v(p.deathCoil),
                    v(p.deathCoilKnown), v(p.deathCoilText), p.treeNodes),
    }
    if db then
        db.logins[#db.logins + 1] = entry
        while #db.logins > MAX_LOGINS do table.remove(db.logins, 1) end
    end
    if entry.verdict == "OK" then
        say(("|cff33ff33OK|r on %s: only this realm's data (%s)."):format(realm, entry.seen))
    else
        say(("|cffff3333MIXED|r on %s: %s"):format(realm, entry.wrong))
    end
    return entry
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" then
        if name ~= "EverlakeSwitch" then return end
        EverlakeSwitchDB = EverlakeSwitchDB or {}
        db = EverlakeSwitchDB
        db.logins = db.logins or {}
        db.errors = db.errors or {}
        for _, e in ipairs(pendingErrors) do db.errors[#db.errors + 1] = e end
        pendingErrors = {}
    elseif event == "PLAYER_LOGIN" then
        -- hotfixes requested at login may still be arriving: check after 5 s, and again after 30 s
        C_Timer.After(5, function() check("login") end)
        C_Timer.After(30, function() check("login+30s") end)
    end
end)

SLASH_EVERLAKESWITCH1 = "/els"
SlashCmdList.EVERLAKESWITCH = function()
    check("manual")
    say("saved; /reload or log out writes it to disk.")
end
