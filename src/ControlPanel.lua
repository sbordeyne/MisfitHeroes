-- ==============================================
-- MISFIT HEROES - World-space control panel
-- ==============================================
-- Owns the physical panel object players use before the game starts: the
-- Start button, plus one enable/disable toggle per extension listed in
-- data/index.json. "base" is always enabled and has no toggle -- it's the
-- core game, not an optional extension.

ControlPanel = {}

local INDEX_URL = "https://raw.githubusercontent.com/sbordeyne/MisfitHeroes/refs/heads/master/data/index.json"
-- Placeholder -- needs tuning against the actual table asset (same caveat
-- as RING_RADIUS in Global.lua).
local PANEL_POS = { x = 0, y = 1, z = -14 }
local BASE_KEY = "base"

-- extension key -> enabled.
ControlPanel.extensions = { [BASE_KEY] = true }
-- extension key -> data JSON url, populated from index.json. Excludes
-- "base" -- it's not an optional extension, so it never gets a toggle.
ControlPanel.sources = {}

local panelObject

local function sortedExtensionKeys()
    local keys = {}
    for key in pairs(ControlPanel.sources) do
        table.insert(keys, key)
    end
    table.sort(keys)
    return keys
end

function ControlPanel.isEnabled(key)
    return ControlPanel.extensions[key] == true
end

function ControlPanel.setEnabled(key, enabled)
    if key == BASE_KEY then return end -- base can't be disabled
    ControlPanel.extensions[key] = enabled
end

function ControlPanel.build()
    panelObject = spawnObject({
        type = "BlockSquare",
        position = PANEL_POS,
        rotation = { 0, 0, 0 },
        -- Must stay uniform {1,1,1}: a UI Panel's own `scale` attribute is
        -- applied ON TOP OF the object's scale (see refreshUI's UI_SCALE),
        -- so a non-uniform object scale (e.g. the old {4, 0.1, 2}) silently
        -- crushes/distorts the attached UI -- that's why the panel used to
        -- render nothing.
        scale = { 1, 1, 1 },
    })
    panelObject.setName("Misfit Heroes Control Panel")
    panelObject.setColorTint({ 0.1, 0.1, 0.12 })
    panelObject.setLock(false)
    -- Deliberately NOT setting interactable = false here: that disables
    -- click-through for ALL of the object's attached UI, not just physical
    -- grabbing, which would make the Start button unclickable. setLock(true)
    -- already stops players from picking the panel up.

    -- A freshly spawned object isn't always ready to accept a UI call on the
    -- same frame; give it a beat before the first setXmlTable.
    Wait.frames(function()
        ControlPanel.refreshUI() -- show Start immediately; extension rows fill in once the index loads
        ControlPanel.loadIndex()
    end, 2)
end

function ControlPanel.loadIndex()
    WebRequest.get(INDEX_URL, function(request)
        if request.is_error then
            printToAll("Failed to load extension index from " .. INDEX_URL .. ": " .. request.error, { 1, 0, 0 })
            return
        end

        local decoded = JSON.decode(request.text) or {}
        ControlPanel.sources = {}
        for key, url in pairs(decoded) do
            if key ~= BASE_KEY then
                ControlPanel.sources[key] = url
                if ControlPanel.extensions[key] == nil then
                    ControlPanel.extensions[key] = false
                end
            end
        end

        ControlPanel.refreshUI()
    end)
end

function ControlPanel.refreshUI()
    local extensionKeys = sortedExtensionKeys()

    local children = {
        { tag = "Text", attributes = { text = "MISFIT HEROES", fontSize = "26", color = "#FFFFFF" } },
        {
            tag = "Button",
            attributes = {
                id = "start_button",
                onClick = "Global/onStartClick",
                width = "160",
                height = "50",
                color = "#2E8B57",
                textColor = "#FFFFFF",
                fontSize = "28",
            },
            value = "Start",
        },
        { tag = "Text", attributes = { text = "Extensions", fontSize = "22", color = "#FFFFFF" } },
        {
            tag = "HorizontalLayout",
            attributes = { childAlignment = "MiddleLeft", spacing = "8" },
            children = {
                -- base is always on and can't be toggled off.
                { tag = "Toggle", attributes = { isOn = "True", interactable = "False" } },
                { tag = "Text", attributes = { text = BASE_KEY, fontSize = "24", color = "#AAAAAA" } },
            },
        },
    }

    for _, key in ipairs(extensionKeys) do
        table.insert(children, {
            tag = "HorizontalLayout",
            attributes = { childAlignment = "MiddleLeft", spacing = "8" },
            children = {
                {
                    tag = "Toggle",
                    attributes = {
                        id = "ext_" .. key,
                        isOn = tostring(ControlPanel.extensions[key]),
                        onValueChanged = "Global/onControlPanelToggle",
                    },
                },
                { tag = "Text", attributes = { text = key, fontSize = "24", color = "#FFFFFF" } },
            },
        })
    end

    panelObject.UI.setXmlTable({
        {
            tag = "Panel",
            attributes = {
                position = "0 0.2 0",
                rotation = "90 0 0",
                scale = "0.03 0.03 0.03",
                width = "300",
                height = tostring(160 + 40 * (#extensionKeys + 1)),
                color = "#1A1A1ACC",
            },
            children = {
                {
                    tag = "VerticalLayout",
                    attributes = { childAlignment = "UpperCenter", spacing = "10" },
                    children = children,
                },
            },
        },
    })
end
