-- ==============================================
-- MISFIT HEROES - Card renderer
-- ==============================================
-- Renders one combined card (a hero + a background) onto a blank TTS "Card"
-- object: artwork, cost coin, victory-point trophy, faction ribbon, name
-- banner, and both effect boxes. Static art/shapes are drawn with decals
-- (rotate/flip correctly with the object); all dynamic text -- including
-- :marker: -> icon substitution -- is drawn with the object's attached UI,
-- since decals cannot render text.
--
-- No dependency on Global.lua: FACTION/BG_EFFECT are duplicated here so this
-- file can be included and used standalone.
--
-- Usage:
--   local rendered = Card.new(cardObject, heroData, backgroundData)
--   rendered:render()

Card = {}
Card.__index = Card

Card.FACTION = {
    NONE = "none",
    BLUE = "blue",
    RED = "red",
    PURPLE = "purple",
}

Card.BG_EFFECT = {
    CONDITION = "condition",
    ADDITIONAL_COST = "extra_cost",
    ON_PLAY = "on_play",
    VICTORY_CALC = "victory_calc",
}

local FACTION = Card.FACTION
local BG_EFFECT = Card.BG_EFFECT

-- Point this at wherever assets/ ends up hosted (Steam Cloud, GitHub raw,
-- etc). Local file paths only work for the machine that's actually running
-- the TTS client you're testing in -- see the same warning in Global.lua.
local ASSET_BASE = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/assets/"

local UI_ASSETS = {
    cost = ASSET_BASE .. "ui/ui_cost.png",
    victory = ASSET_BASE .. "ui/ui_victory.png",
    banner = ASSET_BASE .. "ui/ui_banner.png",
    factionBlue = ASSET_BASE .. "ui/ui_faction_blue.png",
    factionRed = ASSET_BASE .. "ui/ui_faction_red.png",
    factionPurple = ASSET_BASE .. "ui/ui_faction_purple.png",
    effectHero = ASSET_BASE .. "ui/ui_effect_hero.png",
    effectCondition = ASSET_BASE .. "ui/ui_effect_condition.png",
    effectAdditionalCost = ASSET_BASE .. "ui/ui_effect_additional_cost.png",
    effectOnPlay = ASSET_BASE .. "ui/ui_effect_on_play.png",
    effectVictory = ASSET_BASE .. "ui/ui_effect_victory.png",
    font = ASSET_BASE .. "ComickBook_CAPS.ttf",
}

-- :marker: token -> icon image, and the UI custom-asset name it's registered under.
local ICON_MARKERS = {
    g = { name = "icon_g", url = ASSET_BASE .. "font/g.png" },
    human = { name = "icon_human", url = ASSET_BASE .. "font/human.png" },
    monster = { name = "icon_monster", url = ASSET_BASE .. "font/monster.png" },
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

-- Fractional (left, top, right, bottom) layout boxes -- ported from
-- src/extract_artwork.py's SEARCH/FALLBACK constants (the best available
-- ground truth, tuned against photographed reference cards). Exact fit
-- against the live TTS card mesh still needs eyeballing -- see the plan's
-- verification section.
local LAYOUT = {
    cost = { 0.0, 0.0, 0.22, 0.18 },
    victory = { 0.78, 0.0, 1.0, 0.18 },
    faction = { 0.0, 0.05, 0.22, 0.65 },
    artwork = { 0.0, 0.0, 1.0, 5 / 7 },

    banner = { 0.08, 0.53, 0.92, 0.78 },
    bannerHeroText = { 0.12, 0.55, 0.88, 0.63 },
    bannerBackgroundText = { 0.14, 0.65, 0.86, 0.76 },

    effectBackground = { 0.03, 0.76, 1.0, 0.94 },
    effectBackgroundText = { 0.17, 0.775, 0.97, 0.935 },

    effectHero = { 0.03, 0.65, 1.0, 0.86 },
    effectHeroText = { 0.06, 0.665, 0.97, 0.855 },
}

local FONT_SIZE = {
    badge = 42,   -- cost / VP numbers
    banner = 34,  -- hero / background name
    effect = 26,  -- effect box text
}

local TEXT_COLOR = "#2B1B12"

-- Object-attached UI: pixel-to-world conversion. TTS UI elements are laid
-- out in pixels and then scaled down onto the object by `scale`; these two
-- constants are a starting point and will need tuning against the live card
-- mesh (same as DECAL_SCALE in Global.lua).
local UI_PIXELS_PER_UNIT = 100
local UI_SCALE = { 0.01, 0.01, 0.01 }

-- Decals stack along Y so nothing z-fights; each call to addImageDecal grabs
-- the next step automatically.
local BASE_DECAL_Y = 0.11
local DECAL_Y_STEP = 0.001
-- UI panels sit just above the topmost decal.
local UI_Y = 0.2

--------------------------------------------------------------------------
-- Construction
--------------------------------------------------------------------------

function Card.new(cardObject, heroData, backgroundData)
    local self = setmetatable({}, Card)
    self.cardObject = cardObject
    self.hero = heroData
    self.background = backgroundData

    self.faction = self:computeFaction()
    self.cost = (heroData.cost or 0) + (backgroundData.cost or 0)
    self.victoryPoints = self:computeVictoryPoints()

    self.decalYCounter = 0
    self.uiElements = {}

    return self
end

-- Same faction on both halves stays that faction; NONE defers to the other
-- side; two different factions become PURPLE. Mirrors
-- Global.lua's computeCombinedFaction.
function Card:computeFaction()
    local heroFaction = self.hero.faction or FACTION.NONE
    local backgroundFaction = self.background.faction or FACTION.NONE

    if heroFaction == backgroundFaction then
        return heroFaction
    end
    if backgroundFaction == FACTION.NONE then
        return heroFaction
    end
    if heroFaction == FACTION.NONE then
        return backgroundFaction
    end
    return FACTION.PURPLE
end

-- If either half has a variable ("X") VP value the combined card is also
-- "X"; otherwise it's the sum of both halves. Mirrors
-- Global.lua's computeCombinedVictoryPoints.
function Card:computeVictoryPoints()
    local backgroundVP = self.background.victoryPoints
    return backgroundVP
end

--------------------------------------------------------------------------
-- Layout helpers
--------------------------------------------------------------------------

-- Converts a fractional (left, top, right, bottom) card-space box into a
-- world-space {position, rotation, scale} for addDecal, using the card
-- object's own live bounds rather than a hardcoded card size.
function Card:fracToWorld(box, yOffset)
    local size = self.cardObject.getBounds().size
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

function Card:nextDecalY()
    self.decalYCounter = self.decalYCounter + 1
    return BASE_DECAL_Y + self.decalYCounter * DECAL_Y_STEP
end

function Card:addImageDecal(name, url, box)
    local xf = self:fracToWorld(box, self:nextDecalY())
    self.cardObject.addDecal({
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
function Card:tokenize(text)
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
function Card:tokenizeLines(text)
    local lines = {}
    for line in string.gmatch((text or "") .. "\n", "(.-)\n") do
        table.insert(lines, self:tokenize(line))
    end
    if #lines == 0 then
        lines = { {} }
    end
    return lines
end

--------------------------------------------------------------------------
-- UI building
--------------------------------------------------------------------------

function Card:ensureUIAssetsRegistered()
    if self.uiAssetsRegistered then return end
    local assets = { { name = FONT_ASSET_NAME, url = UI_ASSETS.font } }
    for _, icon in pairs(ICON_MARKERS) do
        table.insert(assets, { name = icon.name, url = icon.url })
    end
    self.cardObject.UI.setCustomAssets(assets)
    self.uiAssetsRegistered = true
end

-- One row (HorizontalLayout) of alternating Text/Image children for a
-- single line's tokens.
function Card:buildRow(tokens, fontSize)
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
function Card:queueTextBox(id, box, lines, fontSize)
    local xf = self:fracToWorld(box, UI_Y)

    local rows = {}
    for _, tokens in ipairs(lines) do
        table.insert(rows, self:buildRow(tokens, fontSize))
    end

    table.insert(self.uiElements, {
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

function Card:flushUI()
    self.cardObject.UI.setXmlTable(self.uiElements)
end

--------------------------------------------------------------------------
-- Component renderers
--------------------------------------------------------------------------

function Card:renderArtwork()
    self:addImageDecal("Background Art", self.background.url, LAYOUT.artwork)
    self:addImageDecal("Hero Art", self.hero.url, LAYOUT.artwork)
end

function Card:renderCost()
    self:addImageDecal("Cost Coin", UI_ASSETS.cost, LAYOUT.cost)
    self:queueTextBox("cost_text", LAYOUT.cost, { self:tokenize(tostring(self.cost)) }, FONT_SIZE.badge)
end

function Card:renderVictoryPoints()
    self:addImageDecal("Victory Trophy", UI_ASSETS.victory, LAYOUT.victory)
    self:queueTextBox("victory_text", LAYOUT.victory, { self:tokenize(tostring(self.victoryPoints)) }, FONT_SIZE.badge)
end

function Card:renderFaction()
    if self.faction == FACTION.NONE then return end

    local urlByFaction = {
        [FACTION.BLUE] = UI_ASSETS.factionBlue,
        [FACTION.RED] = UI_ASSETS.factionRed,
        [FACTION.PURPLE] = UI_ASSETS.factionPurple,
    }
    self:addImageDecal("Faction Ribbon", urlByFaction[self.faction], LAYOUT.faction)
end

function Card:renderBanner()
    self:addImageDecal("Name Banner", UI_ASSETS.banner, LAYOUT.banner)
    self:queueTextBox("banner_hero_text", LAYOUT.bannerHeroText, { self:tokenize(self.hero.name or "") }, FONT_SIZE.banner)
    self:queueTextBox("banner_background_text", LAYOUT.bannerBackgroundText, { self:tokenize(self.background.name or "") }, FONT_SIZE.banner)
end

function Card:renderBackgroundEffectBox()
    local effect = self.background.effect or {}
    local urlByCategory = {
        [BG_EFFECT.CONDITION] = UI_ASSETS.effectCondition,
        [BG_EFFECT.ADDITIONAL_COST] = UI_ASSETS.effectAdditionalCost,
        [BG_EFFECT.ON_PLAY] = UI_ASSETS.effectOnPlay,
        [BG_EFFECT.VICTORY_CALC] = UI_ASSETS.effectVictory,
    }
    local url = urlByCategory[effect.category] or UI_ASSETS.effectOnPlay

    self:addImageDecal("Background Effect Box", url, LAYOUT.effectBackground)
    self:queueTextBox(
        "background_effect_text",
        LAYOUT.effectBackgroundText,
        self:tokenizeLines(effect.text),
        FONT_SIZE.effect
    )
end

function Card:renderHeroEffectBox()
    local effect = self.hero.effect or {}
    self:addImageDecal("Hero Effect Box", UI_ASSETS.effectHero, LAYOUT.effectHero)
    self:queueTextBox(
        "hero_effect_text",
        LAYOUT.effectHeroText,
        self:tokenizeLines(effect.text),
        FONT_SIZE.effect
    )
end

--------------------------------------------------------------------------
-- Entry point
--------------------------------------------------------------------------

function Card:render()
    self:ensureUIAssetsRegistered()

    self:renderArtwork()
    self:renderCost()
    self:renderVictoryPoints()
    self:renderFaction()
    self:renderBanner()
    self:renderBackgroundEffectBox()
    self:renderHeroEffectBox()

    self:flushUI()
    return self
end
