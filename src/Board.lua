function onSave()
    return JSON.encode(State)
end

State = {}

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
    if saved_data ~= '' then
        local loaded_data = JSON.decode(saved_data)
        State = loaded_data
    else
        local player_order = tonumber(self.getDescription())
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
    b_display_leaf = generateButtons("leaf", TOKEN_FRAC.leaf, {1})
    b_display_rock = generateButtons("rock", TOKEN_FRAC.rock, {1})
    b_display_water = generateButtons("water", TOKEN_FRAC.water, {1})
    b_display_money = generateButtons("money", TOKEN_FRAC.money, {1, 5, 10})
    b_display_points = generateButtons("points", TOKEN_FRAC.points, {})
end

function increase_leaf()
    State.leaf = State.leaf + 1
    b_display_leaf.label = tostring(State.leaf)
    self.editButton(b_display_leaf)
end

function increase_rock()
    State.rock = State.rock + 1
    b_display_rock.label = tostring(State.rock)
    self.editButton(b_display_rock)
end

function increase_water()
    State.water = State.water + 1
    b_display_water.label = tostring(State.water)
    self.editButton(b_display_water)
end

function increase_money()
    State.money = State.money + 1
    b_display_money.label = tostring(State.money)
    self.editButton(b_display_money)
end

function decrease_leaf()
    if State.leaf > 0 then
        State.leaf = State.leaf - 1
        b_display_leaf.label = tostring(State.leaf)
        self.editButton(b_display_leaf)
    end
end

function decrease_rock()
    if State.rock > 0 then
        State.rock = State.rock - 1
        b_display_rock.label = tostring(State.rock)
        self.editButton(b_display_rock)
    end
end

function decrease_water()
    if State.water > 0 then
        State.water = State.water - 1
        b_display_water.label = tostring(State.water)
        self.editButton(b_display_water)
    end
end

function decrease_money()
    if State.money > 0 then
        State.money = State.money - 1
        b_display_money.label = tostring(State.money)
        self.editButton(b_display_money)
    end
end

function increase5_money()
    State.money = State.money + 5
    b_display_money.label = tostring(State.money)
    self.editButton(b_display_money)
end

function decrease5_money()
    if State.money >= 5 then
        State.money = State.money - 5
        b_display_money.label = tostring(State.money)
        self.editButton(b_display_money)
    end
end

function increase10_money()
    State.money = State.money + 10
    b_display_money.label = tostring(State.money)
    self.editButton(b_display_money)
end

function decrease10_money()
    if State.money >= 10 then
        State.money = State.money - 10
        b_display_money.label = tostring(State.money)
        self.editButton(b_display_money)
    end
end


function doNothing()
end

-- Measured live via the diagnostic print: this board's local (unscaled)
-- footprint is about 4.49 x 4.98 units (getBounds().size {21.1, 0.15, 23.4}
-- / getScale() {4.7, 1, 4.7}), and adjacent tokens sit only ~0.9-1.0 units
-- apart in that space. The old +/- offset (0.75) was sized for a much
-- bigger assumed board and reached almost all the way into the next
-- resource's buttons -- that's what "all over the place" was. These are
-- sized to fit inside that ~0.9 unit gap instead.
local PLUS_MINUS_X_OFFSET = 0.16
local PLUS_MINUS_Z_BASE = 0.06
local PLUS_MINUS_Z_STEP = 0.12

-- tokenFrac: {x, y} fractional position of the resource's token icon on
-- the board texture (see TOKEN_FRAC). The count display is anchored just
-- "above" it (DISPLAY_OFFSET_FRAC); the +/- buttons flank the display the
-- same way they always have, just relative to that anchor instead of a
-- fixed slot.
function generateButtons(resource, tokenFrac, increments)
    printToAll("State : "..JSON.encode(State))
    local resource_count = 0
    if increments == nil then
        increments = {1}
    end

    local anchor = fracToLocal(tokenFrac.x, tokenFrac.y + DISPLAY_OFFSET_FRAC, 0.1)

    local b_display = {
        click_function = 'doNothing', function_owner = self, label = tostring(resource_count),
        position = anchor, width = 100, height = 100, font_size = 70
    }
    for i, increment in ipairs(increments) do
        local b_plus = {
            click_function = 'increase'..increment..'_'..resource, function_owner = self, label =  '+'..increment,
            position = {anchor[1] + PLUS_MINUS_X_OFFSET, anchor[2], anchor[3] + PLUS_MINUS_Z_BASE - (i-1)*PLUS_MINUS_Z_STEP},
            width = 50, height = 70, font_size = 40
        }
        local b_minus = {
            click_function = 'decrease'..increment..'_'..resource, function_owner = self, label =  '-'..increment,
            position = {anchor[1] - PLUS_MINUS_X_OFFSET, anchor[2], anchor[3] + PLUS_MINUS_Z_BASE - (i-1)*PLUS_MINUS_Z_STEP},
            width = 50, height = 70, font_size = 40
        }
        self.createButton(b_plus)
        self.createButton(b_minus)
    end

    self.createButton(b_display)
    return b_display
end
