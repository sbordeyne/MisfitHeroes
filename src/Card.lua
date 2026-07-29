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

-- Sentinel for a "variable" victory point value (data/base.json uses -1 for
-- this on backgrounds whose points are computed by a VICTORY_CALC effect
-- instead of being fixed) -- picks the ui_victory_x.png badge, which already
-- has an "X" printed on it, instead of the plain numbered one.
local VARIABLE_POINTS = "X"

-- Point this at wherever assets/ ends up hosted (Steam Cloud, GitHub raw,
-- etc). Local file paths only work for the machine that's actually running
-- the TTS client you're testing in.
local ASSET_BASE = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/assets/"

-- Rendered as decals (see queueImageDecal) -- decals take a URL directly, no
-- pre-registration needed, unlike attached-UI Image elements.
local UI_ASSETS = {
    cost = ASSET_BASE .. "ui/ui_cost.png",
    victory = ASSET_BASE .. "ui/ui_victory.png",
    victoryX = ASSET_BASE .. "ui/ui_victory_x.png",
    banner = ASSET_BASE .. "ui/ui_banner.png",
    factionHuman = ASSET_BASE .. "ui/ui_faction_human.png",
    factionMonster = ASSET_BASE .. "ui/ui_faction_monster.png",
    factionMutant = ASSET_BASE .. "ui/ui_faction_mutant.png",
    effectOnPlay = ASSET_BASE .. "ui/ui_effect_on_play.png",
    effectVictory = ASSET_BASE .. "ui/ui_effect_victory.png",
    effectExtraCost = ASSET_BASE .. "ui/ui_effect_extra_cost.png",
    effectCondition = ASSET_BASE .. "ui/ui_effect_condition.png",
    effectActivation = ASSET_BASE .. "ui/ui_effect_activation.png",
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

--------------------------------------------------------------------------
-- Layout
--------------------------------------------------------------------------
-- Every ui/ asset is authored 1:1 against this reference canvas (matches
-- bg_card_front.png's own pixel size) -- no rescaling needed, only correct
-- positioning. ui_cost anchors by its own top-left corner to the card's
-- top-left; ui_victory mirrors that to the top-right; ui_banner and every
-- ui_effect_* variant anchor by their bottom-left corner to the card's
-- bottom-left. That last group each carries a lot of transparent padding
-- above its actual ink (e.g. ui_banner.png is a 537px-tall canvas but the
-- ribbon itself only occupies the top ~178px of it) -- sized specifically so
-- several of them can share that one bottom-left anchor and still land
-- stacked in the right place with no manual offset math here.
local CARD_PX = { width = 1000, height = 1400 }

local ASSET_PX = {
    cost = { 140, 143 },
    victory = { 115, 126 },
    victoryX = { 114, 123 },
    artwork = { 1000, 1000 },
    factionHuman = { 100, 554 },
    factionMonster = { 100, 576 },
    factionMutant = { 100, 580 },
    banner = { 1000, 537 },
    effectOnPlay = { 1000, 359 },
    effectVictory = { 1000, 358 },
    effectExtraCost = { 1000, 365 },
    effectCondition = { 1000, 362 },
    effectActivation = { 1000, 227 },
}

local function topLeftBox(px)
    return { 0, 0, px[1] / CARD_PX.width, px[2] / CARD_PX.height }
end

local function topRightBox(px)
    local w = px[1] / CARD_PX.width
    return { 1 - w, 0, 1, px[2] / CARD_PX.height }
end

local function bottomLeftBox(px)
    local h = px[2] / CARD_PX.height
    return { 0, 1 - h, 1, 1 }
end

-- Faction ribbons have no anchor rule of their own (unlike the assets
-- above, their canvas has no built-in padding to lean on) -- best guess is
-- flush against the left edge, starting right where the cost badge ends.
local function belowCostBox(px)
    local costBottom = ASSET_PX.cost[2] / CARD_PX.height
    return { 0, costBottom, px[1] / CARD_PX.width, costBottom + px[2] / CARD_PX.height }
end

local LAYOUT = {
    cost = topLeftBox(ASSET_PX.cost),
    victory = topRightBox(ASSET_PX.victory),
    victoryX = topRightBox(ASSET_PX.victoryX),
    artwork = topLeftBox(ASSET_PX.artwork),

    factionHuman = belowCostBox(ASSET_PX.factionHuman),
    factionMonster = belowCostBox(ASSET_PX.factionMonster),
    factionMutant = belowCostBox(ASSET_PX.factionMutant),

    banner = bottomLeftBox(ASSET_PX.banner),
    effectOnPlay = bottomLeftBox(ASSET_PX.effectOnPlay),
    effectVictory = bottomLeftBox(ASSET_PX.effectVictory),
    effectExtraCost = bottomLeftBox(ASSET_PX.effectExtraCost),
    effectCondition = bottomLeftBox(ASSET_PX.effectCondition),
    effectActivation = bottomLeftBox(ASSET_PX.effectActivation),

    -- Text-safe sub-boxes, hand-measured against each asset's own painted
    -- ink (not its full padded canvas) so text doesn't sit on top of the
    -- ribbon fold / icon square / decorative border art.
    costText = { 0.04, 0.03, 0.135, 0.10 },
    victoryText = { 0.895, 0.01, 0.995, 0.075 },
    bannerText = { 0.28, 0.645, 0.74, 0.75 },
    effectText = { 0.23, 0.75, 0.90, 0.855 },
    activationEffectText = { 0.10, 0.855, 0.90, 0.965 },
}

local FONT_SIZE = {
    badge = 42,  -- cost / VP numbers
    banner = 30, -- hero / background name
    effect = 26, -- effect box text
}

local TEXT_COLOR = "#2B1B12"

-- Object-attached UI (used for text -- decals can't render text): pixel-to-
-- world conversion. UI elements are laid out in pixels and then scaled down
-- onto the object by `scale`; these two constants are a starting point and
-- will need tuning against the live card mesh.
local UI_PIXELS_PER_UNIT = 100
local UI_SCALE = { 0.01, 0.01, 0.01 }
local UI_Y = 0.2

-- Decals (used for art/badges/ribbons/boxes): TTS's decal `scale` is a
-- multiplier against the image's own undocumented "normal" size -- NOT an
-- absolute world-space size, and NOT the same value as a UI panel's pixel
-- width/height. DECAL_PIXELS_PER_UNIT is our best working estimate of that
-- "normal size" reference, reverse-engineered from a known-working example
-- (a 640x800px card overlay needed roughly scale=(2.11,3.03) to cover a
-- similarly-proportioned card -- see chat, 2026-07-29). Since every asset
-- here is authored 1:1 against the same 1000x1400 CARD_PX reference canvas,
-- one calibrated constant sizes ALL of them correctly at once -- if
-- everything renders too small/large, adjust this single number; relative
-- proportions between elements should stay correct regardless.
local DECAL_PIXELS_PER_UNIT = 650

-- Decals stack along Y so nothing z-fights; each queued decal grabs the
-- next step automatically.
local BASE_DECAL_Y = 0.11
local DECAL_Y_STEP = 0.001

local decalYCounter = 0
local queuedDecals = {}
local queuedUIElements = {}
local decalScale = { x = 1, y = 1 }

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
            background_name = "",
            foreground_name = "",
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
    -- data/base.json uses -1 on a background to mean "variable, computed by
    -- its own VICTORY_CALC effect" -- foregrounds' points are always a
    -- meaningless -1 placeholder and never contribute here.
    local points = background.points or 0
    if points == -1 then
        points = VARIABLE_POINTS
    end
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
        background_name = background.name or "",
        foreground_name = foreground.name or "",
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

function setCost(cost)
    State.cost = cost
    self.render()
end

function setFaction(faction)
    State.faction = faction
    self.render()
end

function setBackgroundUrl(background_url)
    State.background_url = background_url
    self.render()
end

function setForegroundUrl(foreground_url)
    State.foreground_url = foreground_url
    self.render()
end

function setBackgroundName(background_name)
    State.background_name = background_name
    self.render()
end

function setForegroundName(foreground_name)
    State.foreground_name = foreground_name
    self.render()
end

function setPoints(points)
    State.points = points
    self.render()
end

function setEffectCategory(effect_category)
    State.effect_category = effect_category
    self.render()
end

function setEffect(effect)
    State.effect = effect
    self.render()
end

function setActivationEffect(activation_effect)
    State.activation_effect = activation_effect
    self.render()
end

--------------------------------------------------------------------------
-- Layout helpers
--------------------------------------------------------------------------

-- Converts a fractional (left, top, right, bottom) card-space box into this
-- UI panel's {position, width, height} -- using the card object's own live
-- bounds rather than a hardcoded card size.
local function panelGeometry(box)
    local size = self.getBounds().size
    local width, length = size.x, size.z
    local left, top, right, bottom = box[1], box[2], box[3], box[4]

    local centerXFrac = (left + right) / 2
    local centerZFrac = (top + bottom) / 2
    local boxWidthFrac = right - left
    local boxHeightFrac = bottom - top

    local worldWidth = boxWidthFrac * width
    local worldHeight = boxHeightFrac * length

    return {
        position = table.concat({ (centerXFrac - 0.5) * width, UI_Y, (centerZFrac - 0.5) * length }, " "),
        width = tostring(math.floor(worldWidth * UI_PIXELS_PER_UNIT)),
        height = tostring(math.floor(worldHeight * UI_PIXELS_PER_UNIT)),
    }
end

-- decalScale is the same for every decal on this card (see
-- DECAL_PIXELS_PER_UNIT) -- only needs recomputing once per render, from the
-- object's current (possibly still-settling) live bounds.
local function computeDecalScale()
    local size = self.getBounds().size
    return {
        x = size.x * DECAL_PIXELS_PER_UNIT / CARD_PX.width,
        y = size.z * DECAL_PIXELS_PER_UNIT / CARD_PX.height,
    }
end

local function nextDecalY()
    decalYCounter = decalYCounter + 1
    return BASE_DECAL_Y + decalYCounter * DECAL_Y_STEP
end

-- Queues a decal covering `box`'s fractional card-space area. Every decal
-- shares the one precomputed decalScale (see computeDecalScale) -- since
-- box was itself derived from the asset's own pixel size against CARD_PX,
-- the asset's pixel size cancels out of the scale math entirely, leaving
-- the same {x, y} for every decal regardless of which asset it is.
local function queueImageDecal(name, url, box)
    local size = self.getBounds().size
    local width, length = size.x, size.z
    local left, top, right, bottom = box[1], box[2], box[3], box[4]
    local centerXFrac = (left + right) / 2
    local centerZFrac = (top + bottom) / 2

    table.insert(queuedDecals, {
        name = name,
        url = url,
        position = { (centerXFrac - 0.5) * width, nextDecalY(), (centerZFrac - 0.5) * length },
        rotation = { 90, 0, 0 },
        -- After the 90-degree tilt, local Y (the image's own height/up-down
        -- axis) becomes the card's length axis, and local Z (the image's
        -- thickness) becomes "up off the table" -- height goes in the
        -- middle slot, not the last one.
        scale = { decalScale.x, decalScale.y, 1 },
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
-- into one token list per line. Uses a plain (non-pattern) search rather
-- than gmatch("(.-)\n") -- MoonSharp's lazy-match backtracking hits a
-- "pattern too complex" recursion limit on lines with no "\n" (i.e. most
-- single-line effect text) well before real Lua would.
local function tokenizeLines(text)
    text = text or ""
    local lines = {}
    local pos = 1
    while true do
        local s = string.find(text, "\n", pos, true)
        if not s then
            table.insert(lines, tokenize(string.sub(text, pos)))
            break
        end
        table.insert(lines, tokenize(string.sub(text, pos, s - 1)))
        pos = s + 1
    end
    if #lines == 0 then
        lines = { {} }
    end
    return lines
end

--------------------------------------------------------------------------
-- UI building
--------------------------------------------------------------------------

-- Icon markers are the only thing left needing pre-registration as custom
-- UI assets (used inline within text rows) -- everything else (art, badges,
-- ribbons, banner, effect boxes) is a decal now, which takes a URL directly.
local function buildAssetList()
    local assets = {}
    for _, icon in pairs(ICON_MARKERS) do
        table.insert(assets, { name = icon.name, url = icon.url })
    end
    return assets
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
    local geo = panelGeometry(box)

    local rows = {}
    for _, tokens in ipairs(lines) do
        table.insert(rows, buildRow(tokens, fontSize))
    end

    table.insert(queuedUIElements, {
        tag = "Panel",
        attributes = {
            id = id,
            position = geo.position,
            rotation = "90 0 0",
            scale = table.concat(UI_SCALE, " "),
            width = geo.width,
            height = geo.height,
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
    queueTextBox("cost_text", LAYOUT.costText, { tokenize(tostring(State.cost)) }, FONT_SIZE.badge)
end

local function renderVictoryPoints()
    if State.points == VARIABLE_POINTS then
        -- ui_victory_x.png already has the "X" printed on it -- no text overlay.
        queueImageDecal("Victory Trophy", UI_ASSETS.victoryX, LAYOUT.victoryX)
        return
    end
    queueImageDecal("Victory Trophy", UI_ASSETS.victory, LAYOUT.victory)
    queueTextBox("victory_text", LAYOUT.victoryText, { tokenize(tostring(State.points)) }, FONT_SIZE.badge)
end

local function renderFaction()
    if State.faction == FACTION.NONE then return end

    local assetByFaction = {
        [FACTION.HUMAN] = { url = UI_ASSETS.factionHuman, box = LAYOUT.factionHuman },
        [FACTION.MONSTER] = { url = UI_ASSETS.factionMonster, box = LAYOUT.factionMonster },
        [FACTION.MUTANT] = { url = UI_ASSETS.factionMutant, box = LAYOUT.factionMutant },
    }
    local asset = assetByFaction[State.faction]
    queueImageDecal("Faction Ribbon", asset.url, asset.box)
end

local function renderBanner()
    if State.foreground_name == "" and State.background_name == "" then return end

    queueImageDecal("Name Banner", UI_ASSETS.banner, LAYOUT.banner)
    queueTextBox(
        "banner_text",
        LAYOUT.bannerText,
        { tokenize(State.foreground_name), tokenize(State.background_name) },
        FONT_SIZE.banner
    )
end

local function renderEffectBox()
    if State.effect_category == EFFECT_CATEGORY.NONE or State.effect == "" then return end

    local assetByCategory = {
        [EFFECT_CATEGORY.ON_PLAY] = { url = UI_ASSETS.effectOnPlay, box = LAYOUT.effectOnPlay },
        [EFFECT_CATEGORY.VICTORY_CALC] = { url = UI_ASSETS.effectVictory, box = LAYOUT.effectVictory },
        [EFFECT_CATEGORY.EXTRA_COST] = { url = UI_ASSETS.effectExtraCost, box = LAYOUT.effectExtraCost },
        [EFFECT_CATEGORY.CONDITION] = { url = UI_ASSETS.effectCondition, box = LAYOUT.effectCondition },
    }
    local asset = assetByCategory[State.effect_category]
        or { url = UI_ASSETS.effectOnPlay, box = LAYOUT.effectOnPlay }

    queueImageDecal("Effect Box", asset.url, asset.box)
    queueTextBox("effect_text", LAYOUT.effectText, tokenizeLines(State.effect), FONT_SIZE.effect)
end

local function renderActivationEffectBox()
    if State.activation_effect == "" then return end

    queueImageDecal("Activation Effect Box", UI_ASSETS.effectActivation, LAYOUT.effectActivation)
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
    decalYCounter = 0
    queuedDecals = {}
    queuedUIElements = {}
    decalScale = computeDecalScale()

    renderArtwork()
    renderCost()
    renderVictoryPoints()
    renderFaction()
    renderBanner()
    renderEffectBox()
    renderActivationEffectBox()

    self.setDecals(queuedDecals)
    self.UI.setXmlTable(queuedUIElements, buildAssetList())
end
