-- ==============================================
-- MISFIT HEROES - Deck Setup Script (paste into Global.lua)
-- ==============================================
-- Builds a 96-card deck by randomly pairing transparent hero art
-- with background art on blank base cards, "sleeving" them together.

-- #include Card

-- Faction constants. A hero and background of different factions combine into "purple".
local FACTION = {
    NONE = "none",
    BLUE = "blue",
    RED = "red",
    PURPLE = "purple", -- only ever appears as a COMPUTED combined faction, not set on individual cards
}

-- Effect categories that apply to background effects.
local BG_EFFECT = {
    CONDITION = "condition",           -- a condition of play
    ADDITIONAL_COST = "additional_cost",
    ON_PLAY = "on_play",
    VICTORY_CALC = "victory_calc",     -- means victoryPoints should be "X" on this background
}

-- Fill these in with your 96 heroes and 96 backgrounds.
-- URLs must be publicly reachable (Steam Cloud, GitHub raw links, imgbb, etc.)
-- Local file paths will NOT work in Tabletop Simulator.
-- "id" is a stable identifier you can reference in other scripts (e.g. ability lookups).
--
-- victoryPoints: 1 or "X" (use "X" whenever the value is computed by an effect, e.g. VICTORY_CALC).
-- effect.text: plain-language rules text, shown to the player or used by your ability-resolution code.
local heroData = {
    {
        id = "hero_01", name = "Vicomte", url = "https://steamusercontent-a.akamaihd.net/ugc/12703178047108682101/C5EAA096971785661FE6F6B126B5ED1CD7D6CFB6/",
        cost = 1, faction = FACTION.BLUE, victoryPoints = 0,
        effect = { text = "Piochez une carte pour chaque carte HEROS dans votre tableau." },
    },
    {
        id = "hero_02", name = "Scientifique", url = "https://steamusercontent-a.akamaihd.net/ugc/12409751618063215871/23979E112F2433438EBB8C53DC9F7C478EC96889/",
        cost = 2, faction = FACTION.BLUE, victoryPoints = 0,
        effect = { text = "Recrutez une carte MUTANTE pour 8g de moins (mais pas moins de 0)" },
    },
    -- ... continue for all 96
}

local backgroundData = {
    {
        id = "bg_01", name = "Angélique", url = "https://steamusercontent-a.akamaihd.net/ugc/9817866855122808077/2FF9ECCB762A436DD2B261E04B7975AAC0BDABF1/",
        cost = 0, faction = FACTION.NONE, victoryPoints = 1,
        effect = { category = BG_EFFECT.ON_PLAY, text = "Gain 1 gold when this card is played." },
    },
    {
        id = "bg_02", name = "Antique", url = "https://steamusercontent-a.akamaihd.net/ugc/14282936292201905579/D9C227EC3E167F2CDCCC07E2073F4CFE10F0B59D/",
        cost = 14, faction = FACTION.BLUE, victoryPoints = "X",
        effect = { category = BG_EFFECT.VICTORY_CALC, text = "Worth 1 VP per Blue hero you control." },
    },
    -- ... continue for all 96
}

-- A plain blank card face/back used as the base for every card.
local blankFaceURL = "https://steamusercontent-a.akamaihd.net/ugc/16250680365902369776/2C162E297E869BDD1746BCAF54B0F71F9D94D21D/"
local blankBackURL = "https://steamusercontent-a.akamaihd.net/ugc/17283040185869791068/93E26E679A1ACBDC42E514E073291D429BAEFA47/"

local spawnedCards = {}

-- Call this to (re)build the deck, e.g. bound to a button or chat command.
function setupMisfitHeroesDeck()
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