-- ==============================================
-- MISFIT HEROES - Game Setup Script
-- ==============================================
-- startGame() spawns 96 blank cards, attaches src/Card.lua to each one, and
-- deals out a random background/foreground pairing across them by calling
-- each card's own setStateFromBgFg (see src/Card.lua).

-- data/index.json lists one or more data file URLs (currently just "base",
-- pointing at data/base.json); every file it points to is fetched and its
-- "backgrounds"/"foregrounds" lists merged, so adding a new data file later
-- only means adding a line to index.json.
local INDEX_URL = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/data/index.json"
local ASSET_BASE = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/assets/"
local CARD_SCRIPT_URL = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/src/Card.lua"

-- Every spawned card starts as this same blank face/back...
local blankFaceURL = ASSET_BASE .. "cards/bg_card_front.png"
local blankBackURL = ASSET_BASE .. "cards/bg_card_back.png"

local backgroundData = nil
local foregroundData = nil
-- ...and gets src/Card.lua's source attached via setLuaScript -- fetched
-- once from GitHub and cached here rather than embedded, so this file
-- doesn't have to be kept in sync with Card.lua by hand.
local cardScriptText = nil

-- Fetches data/index.json and every data file it references, then calls
-- onReady(). Safe to call again later (e.g. to pick up edits to the hosted
-- JSON) since it always rebuilds both tables from scratch. Entries are kept
-- exactly as decoded -- setStateFromBgFg takes them as-is, no remapping.
function loadMisfitHeroesData(onReady)
    WebRequest.get(INDEX_URL, function(indexRequest)
        if indexRequest.is_error then
            printToAll("Failed to load " .. INDEX_URL .. ": " .. indexRequest.error, { 1, 0, 0 })
            return
        end

        local index = JSON.decode(indexRequest.text)
        if not index then
            printToAll("Card data index at " .. INDEX_URL .. " failed to decode.", { 1, 0, 0 })
            return
        end

        local urls = {}
        for _, url in pairs(index) do
            table.insert(urls, url)
        end

        backgroundData = {}
        foregroundData = {}
        loadDataFile(1, urls, onReady)
    end)
end

-- Fetches urls[i], appends its backgrounds/foregrounds, then recurses to the
-- next one -- sequential rather than parallel so a failure on file N doesn't
-- race with file N+1 quietly finishing and calling onReady() early.
function loadDataFile(i, urls, onReady)
    if i > #urls then
        onReady()
        return
    end

    WebRequest.get(urls[i], function(request)
        if request.is_error then
            printToAll("Failed to load card data from " .. urls[i] .. ": " .. request.error, { 1, 0, 0 })
            return
        end

        local decoded = JSON.decode(request.text)
        if not decoded or not decoded.backgrounds or not decoded.foregrounds then
            printToAll("Card data at " .. urls[i] .. " is missing 'backgrounds'/'foregrounds'.", { 1, 0, 0 })
            return
        end

        for _, entry in ipairs(decoded.backgrounds) do
            table.insert(backgroundData, entry)
        end
        for _, entry in ipairs(decoded.foregrounds) do
            table.insert(foregroundData, entry)
        end

        loadDataFile(i + 1, urls, onReady)
    end)
end

function loadCardScript(onReady)
    WebRequest.get(CARD_SCRIPT_URL, function(request)
        if request.is_error then
            printToAll("Failed to load " .. CARD_SCRIPT_URL .. ": " .. request.error, { 1, 0, 0 })
            return
        end
        cardScriptText = request.text
        onReady()
    end)
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

local spawnedCards = {}

-- Call this (e.g. bound to a button or chat command) to spawn 96 fresh cards
-- and deal a random hero/background pairing onto them. Loads data/index.json
-- and src/Card.lua's source first if either hasn't been fetched yet.
function startGame()
    if not backgroundData or not foregroundData then
        loadMisfitHeroesData(startGame)
        return
    end
    if not cardScriptText then
        loadCardScript(startGame)
        return
    end

    if #backgroundData ~= #foregroundData then
        printToAll("Background and foreground lists must be the same length!", { 1, 0, 0 })
        return
    end

    spawnedCards = {}
    local backgrounds = shuffleList(backgroundData)
    local foregrounds = shuffleList(foregroundData)

    spawnNextCard(1, #backgrounds, backgrounds, foregrounds)
end

-- Spawns cards one at a time, spread across frames, so TTS has time to
-- actually create/reload each object before we try to call into its script.
function spawnNextCard(i, total, backgrounds, foregrounds)
    if i > total then
        Wait.time(function() assembleDeck(spawnedCards) end, 1)
        return
    end

    local row = math.floor((i - 1) / 12)
    local col = (i - 1) % 12
    local pos = Vector(-7 + col * 1.1, 3, -4 + row * 1.6)

    local card = spawnObject({
        type = "Card",
        position = pos,
        rotation = { 0, 180, 0 },
        scale = { 1, 1, 1 },
    })

    local background = backgrounds[i]
    local foreground = foregrounds[i]

    -- setCustomObject/setLuaScript "will not work correctly if used in the
    -- same frame the object is spawned" (TTS API docs) -- waiting a frame
    -- before touching the freshly spawned card is what was silently leaving
    -- every card without Card.lua actually attached (so setStateFromBgFg
    -- never existed on it, and it stayed on the plain blank face).
    Wait.frames(function()
        card.setCustomObject({
            type = 0, -- rectangular
            face = blankFaceURL,
            back = blankBackURL,
            unique_back = false,
        })
        card.setLuaScript(cardScriptText)
        -- reload() returns the respawned object directly -- no need to
        -- track/re-fetch by GUID.
        card = card.reload()

        Wait.frames(function()
            card.call("setStateFromBgFg", { background = background, foreground = foreground })

            table.insert(spawnedCards, card)
            spawnNextCard(i + 1, total, backgrounds, foregrounds)
        end, 6)
    end, 1)
end

-- Merges all spawned cards into a single shuffled deck, once every card has
-- had a chance to apply its state/decals -- mirrors old Global.lua's
-- recombineIntoDeck.
function assembleDeck(cards)
    if #cards < 2 then return end
    local results = group(cards)
    local deck = results[1]
    deck.setPosition({ 0, 2, 0 })
    deck.shuffle()
    printToAll("Misfit Heroes deck ready - " .. #cards .. " cards.", { 0, 1, 0 })
end

-- Optional: type !start in chat to trigger dealing.
function onChat(message, player)
    if message == "!start" then
        startGame()
        return false
    end
end
