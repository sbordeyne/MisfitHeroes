-- ==============================================
-- MISFIT HEROES - Deck Setup Script (paste into Global.lua)
-- ==============================================
-- Builds a 96-card deck by randomly pairing transparent hero art
-- with background art on blank base cards, "sleeving" them together.

-- #include Card
-- #include PlayerGrid
-- #include ControlPanel

-- Faction constants. A hero and background of different factions combine into "purple".
local FACTION = {
    NONE = "none",
    BLUE = "blue",
    RED = "red",
    PURPLE = "purple", -- only ever appears as a COMPUTED combined faction, not set on individual cards
}

-- Card data (96 heroes as "foregrounds", 96 backgrounds) is fetched at
-- runtime from data/base.json rather than hardcoded here -- see
-- loadMisfitHeroesData() below. heroData/backgroundData stay nil until the
-- first load completes.
local DATA_URL = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/data/base.json"
local ASSET_BASE = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/assets/"

local heroData = nil
local backgroundData = nil

-- A plain blank card face/back used as the base for every card.
local blankFaceURL = ASSET_BASE .. "cards/bg_card_front.png"
local blankBackURL = ASSET_BASE .. "cards/bg_card_back.png"

-- data/base.json's faction strings ("human" / "monster" / "none") mapped
-- onto the BLUE/RED/NONE constants that Card.lua's ribbon assets
-- (ui_faction_blue/red/purple.png) are keyed on. Mismatched factions still
-- combine into PURPLE regardless of what the labels say.
local JSON_FACTION_MAP = {
    human = FACTION.BLUE,
    monster = FACTION.RED,
    none = FACTION.NONE,
}

-- Converts one data/base.json entry (a background or foreground) into the
-- {id, name, url, cost, faction, victoryPoints, effect} shape the deck
-- builder and Card.lua expect.
--
-- isHero forces victoryPoints to 0: every foreground entry's "points" field
-- is a meaningless -1 placeholder (heroes never carry their own VP -- see
-- Card:computeVictoryPoints, which only reads the background side). For
-- backgrounds, points is the real VP value, with -1 meaning "X" (computed
-- by a VICTORY_CALC effect).
local function convertEntry(entry, index, prefix, isHero)
    local victoryPoints = 0
    if not isHero then
        victoryPoints = (entry.points == -1) and "X" or entry.points
    end

    return {
        id = string.format("%s_%02d", prefix, index),
        name = entry.name,
        url = entry.artwork_url,
        cost = entry.cost,
        faction = JSON_FACTION_MAP[entry.faction] or FACTION.NONE,
        victoryPoints = victoryPoints,
        effect = {
            category = entry.effect and entry.effect.category,
            text = entry.effect and entry.effect.text,
        },
    }
end

-- Fetches data/base.json and (re)builds heroData/backgroundData from it,
-- then calls onReady(). Safe to call again later (e.g. to pick up edits to
-- the hosted JSON) since it always overwrites both tables from scratch.
function loadMisfitHeroesData(onReady)
    WebRequest.get(DATA_URL, function(request)
        if request.is_error then
            printToAll("Failed to load card data from " .. DATA_URL .. ": " .. request.error, {1, 0, 0})
            return
        end

        local decoded = JSON.decode(request.text)
        if not decoded or not decoded.backgrounds or not decoded.foregrounds then
            printToAll("Card data at " .. DATA_URL .. " is missing 'backgrounds'/'foregrounds'.", {1, 0, 0})
            return
        end

        backgroundData = {}
        for i, entry in ipairs(decoded.backgrounds) do
            table.insert(backgroundData, convertEntry(entry, i, "bg", false))
        end

        heroData = {}
        for i, entry in ipairs(decoded.foregrounds) do
            table.insert(heroData, convertEntry(entry, i, "hero", true))
        end

        onReady()
    end)
end

local spawnedCards = {}

-- Call this to (re)build the deck, e.g. bound to a button or chat command.
-- Loads data/base.json first if it hasn't been fetched yet.
function setupMisfitHeroesDeck()
    if not heroData or not backgroundData then
        loadMisfitHeroesData(setupMisfitHeroesDeck)
        return
    end

    if #heroData ~= #backgroundData then
        printToAll("Hero and background lists must be the same length!", {1, 0, 0})
        return
    end

    spawnedCards = {}
    local heroes = shuffleList(heroData)
    local backgrounds = shuffleList(backgroundData)

    spawnNextCard(1, #heroes, heroes, backgrounds)
end

-- Spawns cards one at a time, spread across frames, so TTS has time to
-- actually create each object before we try to decal it.
function spawnNextCard(i, total, heroes, backgrounds)
    if i > total then
        Wait.time(function() recombineIntoDeck(spawnedCards) end, 1)
        return
    end

    local row = math.floor((i - 1) / 12)
    local col = (i - 1) % 12
    local pos = Vector(-7 + col * 1.1, 3, -4 + row * 1.6)

    local card = spawnObject({
        type = "Card",
        position = pos,
        rotation = {0, 180, 0},
        scale = {1, 1, 1},
    })

    card.setCustomObject({
        type = 0, -- rectangular
        face = blankFaceURL,
        back = blankBackURL,
        unique_back = false,
    })
    local cardGUID = card.getGUID()
    card.reload()

    local hero = heroes[i]
    local background = backgrounds[i]

    Wait.frames(function()
        -- reload() destroys and respawns the object, so the original `card`
        -- reference is stale by now; re-fetch the live object by GUID.
        card = getObjectFromGUID(cardGUID)

        -- Renders artwork, cost, victory points, faction ribbon, name banner,
        -- and both effect boxes (see src/Card.lua).
        Card.new(card, hero, background):render()

        -- Hidden metadata: not visible to players, readable/writable from script.
        -- Use this to look up abilities, trigger effects, score, etc.
        card.memo = JSON.encode({
            hero = hero,
            background = background,
            -- Combined stats for the assembled card:
            faction = computeCombinedFaction(hero.faction, background.faction),
            cost = hero.cost + background.cost, -- ASSUMPTION: total cost = hero cost + background cost
            victoryPoints = computeCombinedVictoryPoints(hero.victoryPoints, background.victoryPoints),
        })

        table.insert(spawnedCards, card)
        spawnNextCard(i + 1, total, heroes, backgrounds)
    end, 6)
end

-- Same faction on both halves stays that faction; different factions become purple.
function computeCombinedFaction(heroFaction, backgroundFaction)
    if heroFaction == backgroundFaction then
        return heroFaction
    end
    if backgroundFaction == FACTION.NONE then
        return heroFaction
    end
    return FACTION.PURPLE
end

-- If either half has a variable ("X") VP value, the combined card is also "X"
-- (its true value gets resolved later by your VICTORY_CALC effect logic).
-- Otherwise it's the sum of both halves' VP.
function computeCombinedVictoryPoints(heroVP, backgroundVP)
    if heroVP == "X" or backgroundVP == "X" then
        return "X"
    end
    return heroVP + backgroundVP
end

function shuffleList(list)
    local copy = {}
    for i, v in ipairs(list) do copy[i] = v end
    for i = #copy, 2, -1 do
        local j = math.random(i)
        copy[i], copy[j] = copy[j], copy[i]
    end
    return copy
end

function recombineIntoDeck(cards)
    if #cards < 2 then return end
    local results = group(cards)
    local deck = results[1]
    deck.setPosition({0, 2, 0})
    deck.shuffle()
    printToAll("Misfit Heroes deck ready - " .. #cards .. " cards.", {0, 1, 0})
end

-- Reads the hero/background metadata back off a card, e.g. when it's drawn or played.
-- Usage: local data = getCardData(clicked_object)
function getCardData(card)
    if card.memo == nil or card.memo == "" then return nil end
    return JSON.decode(card.memo)
end

function onStartClick()
    setupMisfitHeroesDeck()
end

-- Optional: type !setup in chat to trigger the build
function onChat(message, player)
    if message == "!setup" then
        setupMisfitHeroesDeck()
        return false
    end
end

-- ==============================================
-- Per-player grids
-- ==============================================
-- Seated players are spaced evenly around a ring centered on the table.
-- This does NOT try to match true TTS seat facing (that's table-asset
-- specific and not reliably queryable) -- angles are just divided evenly,
-- so RING_RADIUS and the resulting grid placement will need visual tuning
-- against the actual table.
local RING_RADIUS = 10
local RING_Y = 1

-- Seats that never own a grid.
local NON_PLAYER_COLORS = { Black = true, Grey = true }

function buildPlayerGrids()
    local seated = {}
    for _, player in ipairs(Player.getPlayers()) do
        if player.seated and not NON_PLAYER_COLORS[player.color] then
            table.insert(seated, player.color)
        end
    end
    if #seated == 0 then return end
    table.sort(seated)

    destroyPlayerGrids()

    for i, color in ipairs(seated) do
        local angleDeg = (i - 1) * (360 / #seated)
        local rad = math.rad(angleDeg)
        local centerPos = {
            x = RING_RADIUS * math.sin(rad),
            y = RING_Y,
            z = -RING_RADIUS * math.cos(rad),
        }
        local facing = angleDeg + 180 -- face back toward the table center

        local grid = PlayerGrid.new(color, centerPos, facing)
        grid:build()
        PlayerGrid.instances[color] = grid
    end
end

function destroyPlayerGrids()
    for _, grid in pairs(PlayerGrid.instances) do
        grid:destroy()
    end
    PlayerGrid.instances = {}
end

-- Grids get rebuilt as players join/leave/switch seats, but never while any
-- grid already has cards on it -- once play has started, seating changes no
-- longer reshuffle the board out from under placed cards.
function anyGridOccupied()
    for _, grid in pairs(PlayerGrid.instances) do
        if not grid:isEmpty() then return true end
    end
    return false
end

function refreshPlayerGridsIfSafe()
    if not anyGridOccupied() then
        buildPlayerGrids()
    end
end

function onObjectEnterZone(zone, enter_object)
    PlayerGrid.handleZoneEvent(zone)
end

function onObjectLeaveZone(zone, leave_object)
    PlayerGrid.handleZoneEvent(zone)
end

function onPlayerConnect(player)
    refreshPlayerGridsIfSafe()
end

function onPlayerDisconnect(player)
    refreshPlayerGridsIfSafe()
end

function onPlayerChangeColor(color)
    refreshPlayerGridsIfSafe()
end

-- ==============================================
-- World-space control panel (see src/ControlPanel.lua)
-- ==============================================
function onControlPanelToggle(player, value, id)
    local key = string.gsub(id, "^ext_", "")
    ControlPanel.setEnabled(key, value == "True")
end

function onLoad()
    ControlPanel.build()
    buildPlayerGrids()
end
