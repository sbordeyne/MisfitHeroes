State = {}

local FACTION = {
    NONE = "none",
    HUMAN = "human",
    MONSTER = "monster",
    MUTANT = "mutant",
}

local EFFECT_CATEGORY = {
    NONE = "none",
    ON_PLAY = "on_play",
    VICTORY_CALC = "victory_calc",
    EXTRA_COST = "extra_cost",
    CONDITION = "condition",
}

-- Point this at wherever assets/ ends up hosted (Steam Cloud, GitHub raw,
-- etc). Local file paths only work for the machine that's actually running
-- the TTS client you're testing in.
local ASSET_BASE = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/assets/"

local UI_ASSETS = {
    cost = ASSET_BASE .. "ui/ui_cost.png",
    victory = ASSET_BASE .. "ui/ui_victory.png",
    factionHuman = ASSET_BASE .. "ui/ui_faction_human.png",
    factionMonster = ASSET_BASE .. "ui/ui_faction_monster.png",
    factionMutant = ASSET_BASE .. "ui/ui_faction_mutant.png",
    effectOnPlay = ASSET_BASE .. "ui/ui_effect_on_play.png",
    effectVictory = ASSET_BASE .. "ui/ui_effect_victory.png",
    effectExtraCost = ASSET_BASE .. "ui/ui_effect_extra_cost.png",
    effectCondition = ASSET_BASE .. "ui/ui_effect_condition.png",
    effectActivation = ASSET_BASE .. "ui/ui_effect_activation.png",
    font = ASSET_BASE .. "ComickBook_CAPS.ttf",
}

-- :marker: token -> icon image, and the UI custom-asset name it's registered under.
local ICON_MARKERS = {
    g = { name = "icon_g", url = ASSET_BASE .. "font/g.png" },
    human = { name = "icon_human", url = ASSET_BASE .. "font/human.png" },
    monster = { name = "icon_monster", url = ASSET_BASE .. "font/monster.png" },
    mutant = { name = "icon_mutant", url = ASSET_BASE .. "font/mutant.png" },
    leaf = { name = "icon_leaf", url = ASSET_BASE .. "font/leaf.png" },
    rock = { name = "icon_rock", url = ASSET_BASE .. "font/rock.png" },
    water = { name = "icon_water", url = ASSET_BASE .. "font/water.png" },
    resource = { name = "icon_resource", url = ASSET_BASE .. "font/resource.png" },
    condition = { name = "icon_condition", url = ASSET_BASE .. "font/condition.png" },
    extra_cost = { name = "icon_extra_cost", url = ASSET_BASE .. "font/extra_cost.png" },
    victory_calc = { name = "icon_victory_calc", url = ASSET_BASE .. "font/victory_calc.png" },
    on_play = { name = "icon_on_play", url = ASSET_BASE .. "font/on_play.png" },
}

local FONT_ASSET_NAME = "ComickBookCAPS"

-- Fractional (left, top, right, bottom) layout boxes for a single flat card
-- face (no hero/background split, unlike the old combined-card version).
-- Loosely carried over from src/old/Card.lua's proportions as a starting
-- placeholder -- not yet checked against this card's actual artwork/asset
-- layout, will need eyeballing once real art is in.
local LAYOUT = {
    cost = { 0.0, 0.0, 0.22, 0.18 },
    victory = { 0.78, 0.0, 1.0, 0.18 },
    faction = { 0.0, 0.05, 0.22, 0.65 },
    artwork = { 0.0, 0.0, 1.0, 0.62 },

    effectBox = { 0.03, 0.64, 1.0, 0.80 },
    effectText = { 0.08, 0.65, 0.97, 0.79 },

    activationEffectBox = { 0.03, 0.81, 1.0, 0.97 },
    activationEffectText = { 0.08, 0.82, 0.97, 0.96 },
}

local FONT_SIZE = {
    badge = 42,  -- cost / VP numbers
    effect = 26, -- effect box text
}

local TEXT_COLOR = "#2B1B12"

-- Object-attached UI: pixel-to-world conversion. TTS UI elements are laid
-- out in pixels and then scaled down onto the object by `scale`; these two
-- constants are a starting point and will need tuning against the live card
-- mesh.
local UI_PIXELS_PER_UNIT = 100
local UI_SCALE = { 0.01, 0.01, 0.01 }

-- Decals stack along Y so nothing z-fights; each queued decal grabs the
-- next step automatically.
local BASE_DECAL_Y = 0.11
local DECAL_Y_STEP = 0.001
-- UI panels sit just above the topmost decal.
local UI_Y = 0.2

-- render() can be called many times in a row (every setter triggers one), so
-- decals/UI are rebuilt from scratch each call via setDecals/setXmlTable
-- rather than appended to with addDecal -- otherwise every edit would stack
-- another copy of every decal on top of the last.
local decalYCounter = 0
local queuedDecals = {}
local queuedUIElements = {}
local uiAssetsRegistered = false

function onSave()
    return JSON.encode(State)
end


function onLoad(saved_data)
    local loaded_data = nil
    if saved_data ~= nil and saved_data ~= '' then
        loaded_data = JSON.decode(saved_data)
    end

    if loaded_data ~= nil and #loaded_data > 0 then
        State = loaded_data
    else
        State = {
            faction = FACTION.NONE,
            cost = 0,
            background_url = "",
            foreground_url = "",
            points = 0,
            effect_category = EFFECT_CATEGORY.NONE,
            effect = "",
            activation_effect = "",
        }
    end

    render()
end

-- Bound as a single table, not two positional args: card.call() (see
-- startGame() in Global.lua) only ever passes one `parameters` table to the
-- target function, so { background = ..., foreground = ... } is the only
-- shape a remote call can actually deliver.
function setStateFromBgFg(params)
    local background = params.background
    local foreground = params.foreground
    local bgCost = background.cost or 0
    local fgCost = foreground.cost or 0
    local cost = bgCost + fgCost
    local points = background.points or 0
    local bgFaction = background.faction or FACTION.NONE
    local fgFaction = foreground.faction or FACTION.NONE
    local faction = FACTION.NONE
    if bgFaction == FACTION.NONE then
        faction = fgFaction
    elseif fgFaction == FACTION.NONE then
        faction = bgFaction
    elseif bgFaction == fgFaction then
        faction = bgFaction
    else
        faction = FACTION.MUTANT
    end
    setState({
        cost = cost,
        points = points,
        faction = faction,
        background_url = background.artwork_url or "",
        foreground_url = foreground.artwork_url or "",
        effect_category = background.effect.category or EFFECT_CATEGORY.NONE,
        effect = background.effect.text or "",
        activation_effect = foreground.effect.text or "",
    })
end

function setState(newState)
    for key, _ in pairs(State) do
        if newState[key] ~= nil then
            State[key] = newState[key]
        end
    end
    render()
end

--------------------------------------------------------------------------
-- Layout helpers
--------------------------------------------------------------------------

-- Converts a fractional (left, top, right, bottom) card-space box into a
-- world-space {position, rotation, scale}, using the card object's own live
-- bounds rather than a hardcoded card size.
local function fracToWorld(box, yOffset)
    local size = self.getBounds().size
    local width, length = size.x, size.z
    local left, top, right, bottom = box[1], box[2], box[3], box[4]

    local centerXFrac = (left + right) / 2
    local centerZFrac = (top + bottom) / 2
    local boxWidthFrac = right - left
    local boxHeightFrac = bottom - top

    return {
        position = { (centerXFrac - 0.5) * width, yOffset, (centerZFrac - 0.5) * length },
        rotation = { 90, 0, 0 },
        scale = { boxWidthFrac * width, 1, boxHeightFrac * length },
    }
end

local function nextDecalY()
    decalYCounter = decalYCounter + 1
    return BASE_DECAL_Y + decalYCounter * DECAL_Y_STEP
end

local function queueImageDecal(name, url, box)
    local xf = fracToWorld(box, nextDecalY())
    table.insert(queuedDecals, {
        name = name,
        url = url,
        position = xf.position,
        rotation = xf.rotation,
        scale = xf.scale,
    })
end

--------------------------------------------------------------------------
-- Text tokenizing / marker substitution
--------------------------------------------------------------------------

-- Splits `text` on ":marker:" tokens. Literal text segments are uppercased
-- (ComickBook_CAPS only has capital glyphs) -- this must happen per-segment,
-- BEFORE any markers are matched against the whole string, since
-- string.upper(":g:") would produce ":G:" and silently break the match.
local function tokenize(text)
    local tokens = {}
    local pos = 1
    local length = #text

    while pos <= length do
        local s, e, marker = string.find(text, "(:[%a][%w]*:)", pos)
        if not s then
            table.insert(tokens, { type = "text", value = string.upper(string.sub(text, pos)) })
            break
        end
        if s > pos then
            table.insert(tokens, { type = "text", value = string.upper(string.sub(text, pos, s - 1)) })
        end
        local key = string.sub(marker, 2, -2)
        local icon = ICON_MARKERS[key]
        if icon then
            table.insert(tokens, { type = "icon", icon = icon })
        else
            -- Unrecognized marker: keep it as literal (uppercased) text
            -- rather than silently dropping it.
            table.insert(tokens, { type = "text", value = string.upper(marker) })
        end
        pos = e + 1
    end

    return tokens
end

-- Splits multi-line text (authors hard-break long effect text with "\n")
-- into one token list per line.
local function tokenizeLines(text)
    local lines = {}
    for line in string.gmatch((text or "") .. "\n", "(.-)\n") do
        table.insert(lines, tokenize(line))
    end
    if #lines == 0 then
        lines = { {} }
    end
    return lines
end

--------------------------------------------------------------------------
-- UI building
--------------------------------------------------------------------------

local function ensureUIAssetsRegistered()
    if uiAssetsRegistered then return end
    local assets = { { name = FONT_ASSET_NAME, url = UI_ASSETS.font } }
    for _, icon in pairs(ICON_MARKERS) do
        table.insert(assets, { name = icon.name, url = icon.url })
    end
    self.UI.setCustomAssets(assets)
    uiAssetsRegistered = true
end

-- One row (HorizontalLayout) of alternating Text/Image children for a
-- single line's tokens.
local function buildRow(tokens, fontSize)
    local children = {}
    for _, token in ipairs(tokens) do
        if token.type == "icon" then
            table.insert(children, {
                tag = "Image",
                attributes = {
                    image = token.icon.name,
                    width = tostring(fontSize),
                    height = tostring(fontSize),
                },
            })
        else
            table.insert(children, {
                tag = "Text",
                attributes = {
                    text = token.value,
                    font = FONT_ASSET_NAME,
                    fontSize = tostring(fontSize),
                    color = TEXT_COLOR,
                },
            })
        end
    end

    return {
        tag = "HorizontalLayout",
        attributes = { childAlignment = "MiddleCenter", spacing = "2" },
        children = children,
    }
end

-- Queues a positioned Panel containing one row per line, stacked
-- vertically, over `box`. `lines` is a list of token lists (see
-- tokenizeLines); pass {tokens} directly for single-line content.
local function queueTextBox(id, box, lines, fontSize)
    local xf = fracToWorld(box, UI_Y)

    local rows = {}
    for _, tokens in ipairs(lines) do
        table.insert(rows, buildRow(tokens, fontSize))
    end

    table.insert(queuedUIElements, {
        tag = "Panel",
        attributes = {
            id = id,
            position = table.concat(xf.position, " "),
            rotation = "90 0 0",
            scale = table.concat(UI_SCALE, " "),
            width = tostring(math.floor(xf.scale[1] * UI_PIXELS_PER_UNIT)),
            height = tostring(math.floor(xf.scale[3] * UI_PIXELS_PER_UNIT)),
            color = "#00000000",
        },
        children = {
            {
                tag = "VerticalLayout",
                attributes = { childAlignment = "MiddleCenter", spacing = "2" },
                children = rows,
            },
        },
    })
end

--------------------------------------------------------------------------
-- Component renderers
--------------------------------------------------------------------------

local function renderArtwork()
    if State.background_url ~= "" then
        queueImageDecal("Background Art", State.background_url, LAYOUT.artwork)
    end
    if State.foreground_url ~= "" then
        queueImageDecal("Foreground Art", State.foreground_url, LAYOUT.artwork)
    end
end

local function renderCost()
    queueImageDecal("Cost Coin", UI_ASSETS.cost, LAYOUT.cost)
    queueTextBox("cost_text", LAYOUT.cost, { tokenize(tostring(State.cost)) }, FONT_SIZE.badge)
end

local function renderVictoryPoints()
    queueImageDecal("Victory Trophy", UI_ASSETS.victory, LAYOUT.victory)
    queueTextBox("victory_text", LAYOUT.victory, { tokenize(tostring(State.points)) }, FONT_SIZE.badge)
end

local function renderFaction()
    if State.faction == FACTION.NONE then return end

    local urlByFaction = {
        [FACTION.HUMAN] = UI_ASSETS.factionHuman,
        [FACTION.MONSTER] = UI_ASSETS.factionMonster,
        [FACTION.MUTANT] = UI_ASSETS.factionMutant,
    }
    queueImageDecal("Faction Ribbon", urlByFaction[State.faction], LAYOUT.faction)
end

local function renderEffectBox()
    if State.effect_category == EFFECT_CATEGORY.NONE or State.effect == "" then return end

    local urlByCategory = {
        [EFFECT_CATEGORY.ON_PLAY] = UI_ASSETS.effectOnPlay,
        [EFFECT_CATEGORY.VICTORY_CALC] = UI_ASSETS.effectVictory,
        [EFFECT_CATEGORY.EXTRA_COST] = UI_ASSETS.effectExtraCost,
        [EFFECT_CATEGORY.CONDITION] = UI_ASSETS.effectCondition,
    }
    local url = urlByCategory[State.effect_category] or UI_ASSETS.effectOnPlay

    queueImageDecal("Effect Box", url, LAYOUT.effectBox)
    queueTextBox("effect_text", LAYOUT.effectText, tokenizeLines(State.effect), FONT_SIZE.effect)
end

local function renderActivationEffectBox()
    if State.activation_effect == "" then return end

    queueImageDecal("Activation Effect Box", UI_ASSETS.effectActivation, LAYOUT.activationEffectBox)
    queueTextBox(
        "activation_effect_text",
        LAYOUT.activationEffectText,
        tokenizeLines(State.activation_effect),
        FONT_SIZE.effect
    )
end

--------------------------------------------------------------------------
-- Entry point
--------------------------------------------------------------------------

function render()
    ensureUIAssetsRegistered()

    decalYCounter = 0
    queuedDecals = {}
    queuedUIElements = {}

    renderArtwork()
    renderCost()
    renderVictoryPoints()
    renderFaction()
    renderEffectBox()
    renderActivationEffectBox()

    self.setDecals(queuedDecals)
    self.UI.setXmlTable(queuedUIElements)
end
