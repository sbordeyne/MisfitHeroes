function onSave()
    return JSON.encode(State)
end

State = {}

local function copyTableWithKeyChanged(t, key, newValue)
    local t2 = {}
    for k,v in pairs(t) do
        if type(v) == "table" then
            t2[k] = copyTableWithKeyChanged(v, key, newValue)
        else
            if k == key then
                t2[k] = newValue
            else
                t2[k] = v
            end
        end
    end
    return t2
end

-- Fractional (x, y) center of each resource's token icon on the board's
-- face texture (assets/board.png, 1072x1400px), as (pixelX / width,
-- pixelY / height). Same left-to-right / top-to-bottom convention as
-- Card.lua's LAYOUT boxes. "points" uses the trophy icon further down the
-- sheet, not the blank 5th slot in the top icon row.
local TOKEN_FRAC = {
    water = { x = 65 / 1072, y = 97 / 1400 },
    rock = { x = 300 / 1072, y = 92 / 1400 },
    leaf = { x = 546 / 1072, y = 93 / 1400 },
    money = { x = 755 / 1072, y = 97 / 1400 },
    points = { x = 960 / 1072, y = 350 / 1400 },
}

-- How far "above" (toward the board's far edge) the count display sits
-- relative to its token, as a fraction of the board's own length. This
-- is a first guess -- flip the sign if it lands on the wrong side once you
-- see it in-editor.
local DISPLAY_OFFSET_FRAC = -0.03

-- Converts a fractional (x, y) position on the board's face texture into a
-- position local to this object, using its live bounds rather than a
-- hardcoded board size -- getBounds() reports world-space (scaled) size, so
-- dividing by getScale() first recovers the unscaled/local size that
-- createButton's `position` actually needs (button positions are local to
-- the object, i.e. also scaled by its Transform, same as attached UI).
local function fracToLocal(fracX, fracZ, y)
    local size = self.getBounds().size
    local scale = self.getScale()
    local width = size.x / scale.x
    local length = size.z / scale.z
    return { (fracX - 0.5) * width, y, (fracZ - 0.5) * length }
end

function onLoad(saved_data)
    --Checks if there is a saved data. If there is, it gets the saved value for 'count'
    -- (an object that's never been saved gets nil here, not ''; and a save
    -- taken while State was itself nil round-trips as the string "null",
    -- which decodes back to nil -- so the decoded result needs checking too,
    -- not just the raw saved_data string, or a corrupted save stays corrupted)
    local loaded_data = nil
    if saved_data ~= nil and saved_data ~= '' then
        loaded_data = JSON.decode(saved_data)
    end

    if loaded_data ~= nil and #loaded_data > 0 then
        printToAll("State : "..JSON.encode(loaded_data))
        State = loaded_data
    else
        local player_order = 1
        State = {
            order = player_order,
            money = 35 + 5 * (player_order - 1),
            water = 0,
            rock = 0,
            leaf = 0,
            points = 0,
            cards = {},
        }
    end

    b_display_leaf = generateButton("leaf")
    b_display_rock = generateButton("rock")
    b_display_water = generateButton("water")
    b_display_money = generateButton("money")
    b_display_points = generateButton("points")
end

function on_btn_money(obj, color, alt_click)
    if alt_click then
        if State.money > 0 then
            State = copyTableWithKeyChanged(State, "money", State.money - 1)
        end
    else
        State = copyTableWithKeyChanged(State, "money", State.money + 1)
    end
    b_display_money.label = tostring(State.money)
    obj.editButton(b_display_money)
end

function on_btn_leaf(obj, color, alt_click)
    if alt_click then
        if State.leaf > 0 then
            State = copyTableWithKeyChanged(State, "leaf", State.leaf - 1)
        end
    else
        State = copyTableWithKeyChanged(State, "leaf", State.leaf + 1)
    end
    b_display_leaf.label = tostring(State.leaf)
    obj.editButton(b_display_leaf)
end

function on_btn_rock(obj, color, alt_click)
    if alt_click then
        if State.rock > 0 then
            State = copyTableWithKeyChanged(State, "rock", State.rock - 1)
        end
    else
        State = copyTableWithKeyChanged(State, "rock", State.rock + 1)
    end
    b_display_rock.label = tostring(State.rock)
    obj.editButton(b_display_rock)
end

function on_btn_water(obj, color, alt_click)
    if alt_click then
        if State.water > 0 then
            State = copyTableWithKeyChanged(State, "water", State.water - 1)
        end
    else
        State = copyTableWithKeyChanged(State, "water", State.water + 1)
    end
    b_display_water.label = tostring(State.water)
    obj.editButton(b_display_water)
end

function on_btn_points(obj, color, alt_click)
end


-- editButton() requires `index` to know which existing button to update --
-- "the only parameter that is required is the index" -- but createButton()
-- doesn't accept an index; it's auto-assigned by creation order (0, 1, 2...)
-- and can't be read back. Since onLoad always creates buttons in the same
-- fixed order, this tracks what that auto-assigned index will be so it can
-- be stored on b_display for later editButton() calls. Without it,
-- editButton had no way to identify the right button, which is what showed
-- up as the button "moving to the cursor".
local nextButtonIndex = 0

-- tokenFrac: {x, y} fractional position of the resource's token icon on
-- the board texture (see TOKEN_FRAC). The count display is anchored just
-- "above" it (DISPLAY_OFFSET_FRAC); the +/- buttons flank the display the
-- same way they always have, just relative to that anchor instead of a
-- fixed slot.
function generateButton(resource)
    local tokenFrac = TOKEN_FRAC[resource]
    local resource_count = State[resource]
    local anchor = fracToLocal(tokenFrac.x, tokenFrac.y + DISPLAY_OFFSET_FRAC, 0.1)
    local tooltip = "LMB +1\nRMB -1"
    if resource == "points" then
        tooltip = ""
    end
    local b_display = {
        click_function = 'on_btn_'..resource, function_owner = self, label = tostring(resource_count),
        position = anchor, width = 100, height = 100, font_size = 70,
        tooltip = tooltip,
    }
    b_display.index = nextButtonIndex
    self.createButton(b_display)
    nextButtonIndex = nextButtonIndex + 1
    return b_display
end
