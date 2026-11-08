-- Test 1 (docs/era-data.md): can the Forever client run a class it doesn't ship?
-- Records, into the saved variables EverlakeTest1DB (read by "everlake-client.sh test1"):
--   * every Lua error and blocked action, with a short stack
--   * at login, at each level-up, after a talent change and on /el1: class, power types and runes, the Death Knight
--     test spells (known, cost, usable), the spellbook's skill lines, specialization, the talent tree and its points,
--     the action bar, and which of Blizzard's class frames exist
--   * casts and cast failures of the test spells
-- Commands: /el1 (snapshot), /el1 talents (load and open the talent frame, then snapshot), /el1 spellbook,
--           /el1 runes. The saved variables are written at /reload or logout.
local SPELLS = { 47541, 49998, 48707, 49020, 49184, 55095, 47632 } -- Death Coil, Death Strike, AMS, Obliterate, Howling Blast, Frost Fever, Death Coil damage
local POWERS = { [0] = "MANA", [1] = "RAGE", [2] = "FOCUS", [3] = "ENERGY", [4] = "COMBO_POINTS", [5] = "RUNES",
                 [6] = "RUNIC_POWER", [12] = "CHI" }
local MAX_SNAPSHOTS, MAX_EVENTS, MAX_ERRORS = 15, 300, 150

local db
local pending = { errors = {}, events = {} }
local watched = {}
for _, id in ipairs(SPELLS) do watched[id] = true end

local function stamp() return date("%H:%M:%S") end

local function push(list, item, max)
    list[#list + 1] = item
    while #list > max do table.remove(list, 1) end
end

local function store() return db or pending end

local function record(kind, text)
    push(store().events, stamp() .. " " .. kind .. ": " .. tostring(text), MAX_EVENTS)
end

local function recordError(msg)
    local stack = debugstack and debugstack(3, 8, 0) or ""
    push(store().errors, stamp() .. " " .. tostring(msg) .. "\n" .. stack, MAX_ERRORS)
end

local previousHandler = geterrorhandler()
seterrorhandler(function(msg, ...)
    pcall(recordError, msg)
    if previousHandler then return previousHandler(msg, ...) end
end)

-- one section of a snapshot: its lines, or the error it hit
local function section(lines, title, fn)
    lines[#lines + 1] = "[" .. title .. "]"
    local ok, err = pcall(fn, function(fmt, ...) lines[#lines + 1] = "  " .. string.format(fmt, ...) end)
    if not ok then lines[#lines + 1] = "  ERROR " .. tostring(err) end
end

local function v(x)
    if x == nil then return "nil" end
    return tostring(x)
end

local function snapshot(label)
    local lines = {}
    section(lines, "player", function(add)
        local className, classFile, classID = UnitClass("player")
        local raceName, raceFile, raceID = UnitRace("player")
        local version, build = GetBuildInfo()
        add("%s level %s, class %s/%s/%s, race %s/%s/%s, realm %s, client %s.%s", v(UnitName("player")),
            v(UnitLevel("player")), v(className), v(classFile), v(classID), v(raceName), v(raceFile), v(raceID),
            v(GetRealmName()), v(version), v(build))
    end)
    section(lines, "classes the client knows", function(add)
        add("GetNumClasses() = %s", v(GetNumClasses and GetNumClasses()))
        for id = 1, 13 do
            local info = C_CreatureInfo and C_CreatureInfo.GetClassInfo(id)
            if info then add("%d %s %s", id, v(info.className), v(info.classFile)) end
        end
    end)
    section(lines, "power", function(add)
        local ptype, token = UnitPowerType("player")
        add("display power %s %s", v(ptype), v(token))
        for p = 0, 22 do
            local max = UnitPowerMax("player", p)
            if max and max > 0 then add("power %d %s: %s / %s", p, POWERS[p] or "?", v(UnitPower("player", p)), v(max)) end
        end
    end)
    section(lines, "runes", function(add)
        if not GetRuneCooldown then add("no GetRuneCooldown in this client") return end
        for i = 1, 6 do
            local start, duration, ready = GetRuneCooldown(i)
            add("rune %d: start %s duration %s ready %s", i, v(start), v(duration), v(ready))
        end
    end)
    section(lines, "test spells", function(add)
        for _, id in ipairs(SPELLS) do
            local info = C_Spell and C_Spell.GetSpellInfo and C_Spell.GetSpellInfo(id)
            local costs = {}
            local powerCost = C_Spell and C_Spell.GetSpellPowerCost and C_Spell.GetSpellPowerCost(id)
            for _, c in ipairs(powerCost or {}) do costs[#costs + 1] = v(c.name) .. " " .. v(c.cost) end
            local usable, noPower = nil, nil
            if C_Spell and C_Spell.IsSpellUsable then usable, noPower = C_Spell.IsSpellUsable(id) end
            local desc = C_Spell and C_Spell.GetSpellDescription and C_Spell.GetSpellDescription(id) or ""
            add("%d %s icon %s: player spell %s, known %s, usable %s (no power %s), cost [%s], range %s-%s, text '%s'",
                id, v(info and info.name), v(info and info.iconID), v(IsPlayerSpell and IsPlayerSpell(id)),
                v(IsSpellKnown and IsSpellKnown(id)), v(usable), v(noPower), table.concat(costs, ", "),
                v(info and info.minRange), v(info and info.maxRange), string.sub(desc, 1, 80))
        end
    end)
    section(lines, "spellbook", function(add)
        local n = C_SpellBook.GetNumSpellBookSkillLines()
        add("%s skill lines", v(n))
        for i = 1, n or 0 do
            local line = C_SpellBook.GetSpellBookSkillLineInfo(i)
            local names = {}
            for slot = line.itemIndexOffset + 1, line.itemIndexOffset + math.min(line.numSpellBookItems, 40) do
                local item = C_SpellBook.GetSpellBookItemInfo(slot, Enum.SpellBookSpellBank.Player)
                if item then names[#names + 1] = v(item.name) .. "(" .. v(item.spellID or item.actionID) .. ")" end
            end
            add("%d '%s' skill line %s, %s items: %s", i, v(line.name), v(line.skillLineID), v(line.numSpellBookItems),
                table.concat(names, " "))
        end
    end)
    section(lines, "specialization", function(add)
        local getSpec = (C_SpecializationInfo and C_SpecializationInfo.GetSpecialization) or GetSpecialization
        local getInfo = (C_SpecializationInfo and C_SpecializationInfo.GetSpecializationInfo) or GetSpecializationInfo
        local index = getSpec and getSpec()
        add("index %s", v(index))
        if index and getInfo then
            local id, name = getInfo(index)
            add("spec %s %s", v(id), v(name))
        end
    end)
    section(lines, "talents", function(add)
        local configID = C_ClassTalents and C_ClassTalents.GetActiveConfigID()
        add("active config %s", v(configID))
        if not configID then return end
        local config = C_Traits.GetConfigInfo(configID)
        add("config '%s' type %s trees %s", v(config and config.name), v(config and config.type),
            config and table.concat(config.treeIDs or {}, ",") or "nil")
        for _, treeID in ipairs(config and config.treeIDs or {}) do
            local nodes = C_Traits.GetTreeNodes(treeID) or {}
            local purchased, visible = 0, 0
            for _, nodeID in ipairs(nodes) do
                local node = C_Traits.GetNodeInfo(configID, nodeID)
                if node then
                    purchased = purchased + (node.ranksPurchased or 0)
                    if node.isVisible then visible = visible + 1 end
                end
            end
            add("tree %s: %d nodes, %d visible, %d ranks bought", v(treeID), #nodes, visible, purchased)
            for _, c in ipairs(C_Traits.GetTreeCurrencyInfo(configID, treeID, false) or {}) do
                add("  currency %s: %s left, %s spent, max %s", v(c.traitCurrencyID), v(c.quantity), v(c.spent),
                    v(c.maxQuantity))
            end
        end
    end)
    section(lines, "action bar 1-12", function(add)
        local slots = {}
        for slot = 1, 12 do
            local kind, id = GetActionInfo(slot)
            if kind then slots[#slots + 1] = slot .. "=" .. v(kind) .. ":" .. v(id) end
        end
        add("%s", table.concat(slots, " "))
    end)
    section(lines, "class frames", function(add)
        local _, _, classID = UnitClass("player")
        add("RuneFrame %s, ComboFrame %s, ClassVisuals[%s] %s, PlayerSpellsFrame %s",
            v(_G.RuneFrame ~= nil), v(_G.ComboFrame ~= nil), v(classID),
            v(_G.ClassVisuals and _G.ClassVisuals[classID] ~= nil), v(_G.PlayerSpellsFrame ~= nil))
    end)
    if db then
        push(db.snapshots, { time = date("%Y-%m-%d %H:%M:%S"), label = label, lines = lines }, MAX_SNAPSHOTS)
    end
    return lines
end

local function say(text) print("|cff33ccff[Everlake Test 1]|r " .. text) end

local function openTalents()
    local loaded, reason
    if C_AddOns and C_AddOns.LoadAddOn then loaded, reason = C_AddOns.LoadAddOn("Blizzard_PlayerSpells") end
    record("talents", "LoadAddOn(Blizzard_PlayerSpells) = " .. v(loaded) .. " " .. v(reason))
    local ok, err = pcall(function()
        if PlayerSpellsUtil and PlayerSpellsUtil.OpenToClassTalentsTab then
            PlayerSpellsUtil.OpenToClassTalentsTab()
        elseif TogglePlayerSpellsFrame then
            TogglePlayerSpellsFrame()
        else
            error("no PlayerSpellsUtil.OpenToClassTalentsTab or TogglePlayerSpellsFrame")
        end
    end)
    record("talents", "open: " .. (ok and "ok" or ("ERROR " .. v(err))))
    say("talent frame: " .. (ok and "opened" or ("error " .. v(err))) .. ". Snapshot in 2 s.")
    C_Timer.After(2, function()
        local shown = PlayerSpellsFrame and PlayerSpellsFrame:IsShown()
        record("talents", "PlayerSpellsFrame shown " .. v(shown))
        snapshot("talent frame")
    end)
end

local function openSpellbook()
    local ok, err = pcall(function()
        if C_AddOns and C_AddOns.LoadAddOn then C_AddOns.LoadAddOn("Blizzard_PlayerSpells") end
        PlayerSpellsUtil.OpenToSpellBookTab()
    end)
    record("spellbook", "open: " .. (ok and "ok" or ("ERROR " .. v(err))))
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("PLAYER_LEVEL_UP")
frame:RegisterEvent("UNIT_SPELLCAST_SUCCEEDED")
frame:RegisterEvent("UNIT_SPELLCAST_FAILED")
frame:RegisterEvent("UI_ERROR_MESSAGE")
for _, event in ipairs({ "ADDON_ACTION_BLOCKED", "ADDON_ACTION_FORBIDDEN", "LUA_WARNING", "TRAIT_CONFIG_UPDATED",
                         "LEARNED_SPELL_IN_SKILL_LINE", "LEARNED_SPELL_IN_TAB", "PLAYER_TALENT_UPDATE" }) do
    pcall(frame.RegisterEvent, frame, event) -- not every event exists in every client
end
frame:SetScript("OnEvent", function(self, event, ...)
    if event == "ADDON_LOADED" then
        if ... ~= "EverlakeTest1" then return end
        EverlakeTest1DB = EverlakeTest1DB or {}
        db = EverlakeTest1DB
        db.snapshots = db.snapshots or {}
        db.events = db.events or {}
        db.errors = db.errors or {}
        for _, e in ipairs(pending.errors) do push(db.errors, e, MAX_ERRORS) end
        for _, e in ipairs(pending.events) do push(db.events, e, MAX_EVENTS) end
        pending = { errors = {}, events = {} }
        record("session", "loaded")
    elseif event == "PLAYER_LOGIN" then
        C_Timer.After(3, function()
            snapshot("login")
            local _, classFile = UnitClass("player")
            say(("%s logged in as %s. %d errors so far. Type /el1 for a snapshot, /el1 talents for the talent frame.")
                :format(v(UnitName("player")), v(classFile), #db.errors))
        end)
    elseif event == "PLAYER_LEVEL_UP" then
        local level = ...
        C_Timer.After(2, function() snapshot("level " .. v(level)) end)
    elseif event == "UNIT_SPELLCAST_SUCCEEDED" or event == "UNIT_SPELLCAST_FAILED" then
        local unit, _, spellID = ...
        if unit == "player" and watched[spellID] then record(event == "UNIT_SPELLCAST_SUCCEEDED" and "cast" or "cast failed", spellID) end
    elseif event == "UI_ERROR_MESSAGE" then
        local _, message = ...
        record("ui error", message)
    elseif event == "TRAIT_CONFIG_UPDATED" or event == "PLAYER_TALENT_UPDATE" then
        record("talents", event)
        C_Timer.After(1, function() snapshot(event) end)
    else
        record(event, table.concat({ tostringall(...) }, " "))
    end
end)

SLASH_EVERLAKETEST11 = "/el1"
SlashCmdList.EVERLAKETEST1 = function(msg)
    msg = strlower(strtrim(msg or ""))
    if msg == "talents" then
        openTalents()
    elseif msg == "spellbook" then
        openSpellbook()
    elseif msg == "runes" then
        for _, line in ipairs(snapshot("runes")) do
            if line:find("rune") or line:find("power") then print(line) end
        end
    else
        local lines = snapshot("manual")
        for _, line in ipairs(lines) do print(line) end
        say(("snapshot saved (%d errors recorded). /reload or log out to write it to disk."):format(#db.errors))
    end
end
