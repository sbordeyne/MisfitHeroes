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

-- Fractional center of each of the 16 card-slot cells (4 cols x 4 rows,
-- measured from the card-back tiles printed on the board texture -- 210px
-- column pitch, 290px row pitch out of the 1072x1400 image), plus the
-- quest-token marker: the blank square at the top-right of the icon row
-- (same row as TOKEN_FRAC's icons, rightmost slot, never assigned to a
-- resource).
local CARD_SLOT_COL_FRAC = { 331.5 / 1072, 541.5 / 1072, 751.5 / 1072, 961.5 / 1072 }
local CARD_SLOT_ROW_FRAC = { 376.5 / 1400, 666.5 / 1400, 956.5 / 1400, 1246.5 / 1400 }
local QUEST_SLOT_FRAC = { x = 973 / 1072, y = 101.5 / 1400 }

-- Small hand-tuned correction applied only to where a card actually SNAPS
-- (not to the zones, which were re-verified pixel-accurate against the
-- printed grid's own border lines). A small consistent left-right residual
-- remained even with correct column centers -- likely something in how TTS
-- resolves this object's local-to-world placement for snap points
-- specifically that isn't inspectable from script. Nudge in small steps
-- (0.002-0.005 =~ 2-5px) and reload; positive shifts right, negative left.
local CARD_SLOT_SNAP_X_NUDGE_FRAC = -0.007

-- Zone/snap-point footprint sizes, as a fraction of the texture -- 90% of
-- each slot's measured pitch (card slots) or measured size (quest square),
-- same margin convention as PlayerGrid.lua's CELL_SPACING * 0.9.
local CARD_SLOT_SIZE_FRAC = { x = 189 / 1072, z = 261 / 1400 }
local QUEST_SLOT_SIZE_FRAC = { x = 123 / 1072, z = 126 / 1400 }
local ZONE_HEIGHT = 3

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

-- Converts a fractional (x, y) position into a WORLD position instead --
-- unlike buttons/snap points (local to this object), zones are separate
-- objects spawned via spawnObject, so they need real world coordinates.
-- Uses getBounds() directly (already world-space) rather than fracToLocal,
-- so no scale division/multiplication round-trip is needed -- just rotate
-- the offset by the board's own yaw so this still works if the board isn't
-- axis-aligned.
local function fracToWorld(fracX, fracZ, y)
    local bounds = self.getBounds()
    local rad = math.rad(self.getRotation().y)
    local offsetX = (fracX - 0.5) * bounds.size.x
    local offsetZ = (fracZ - 0.5) * bounds.size.z
    local worldX = offsetX * math.cos(rad) - offsetZ * math.sin(rad)
    local worldZ = offsetX * math.sin(rad) + offsetZ * math.cos(rad)
    return { bounds.center.x + worldX, bounds.center.y + y, bounds.center.z + worldZ }
end

-- Destroys any zones a previous onLoad already spawned for this specific
-- board (matched by name + proximity, so reloading during testing doesn't
-- pile up duplicates, and so this doesn't touch other players' boards
-- running the same script).
local function destroyStaleZones()
    local origin = self.getPosition()
    for _, obj in ipairs(getAllObjects()) do
        if obj.getName():find("^BoardZone_") then
            local p = obj.getPosition()
            local dx, dz = p.x - origin.x, p.z - origin.z
            if math.sqrt(dx * dx + dz * dz) < 30 then
                obj.destruct()
            end
        end
    end
end

-- Builds one Zone + one snap point per card slot (16, in a 4x4 grid), plus
-- one extra pair on the quest-token marker at the top-right of the board.
local function buildSlotZonesAndSnapPoints()
    destroyStaleZones()

    local slots = {}
    for row = 1, #CARD_SLOT_ROW_FRAC do
        for col = 1, #CARD_SLOT_COL_FRAC do
            table.insert(slots, {
                fracX = CARD_SLOT_COL_FRAC[col],
                fracZ = CARD_SLOT_ROW_FRAC[row],
                tag = "CardSlot_" .. row .. "_" .. col,
                sizeFrac = CARD_SLOT_SIZE_FRAC,
            })
        end
    end
    table.insert(slots, {
        fracX = QUEST_SLOT_FRAC.x,
        fracZ = QUEST_SLOT_FRAC.y,
        tag = "QuestSlot",
        sizeFrac = QUEST_SLOT_SIZE_FRAC,
    })

    local snapPoints = {}
    local bounds = self.getBounds()
    for _, slot in ipairs(slots) do
        local snapFracX = slot.fracX
        if slot.tag:find("^CardSlot_") then
            snapFracX = snapFracX + CARD_SLOT_SNAP_X_NUDGE_FRAC
        end
        local localPos = fracToLocal(snapFracX, slot.fracZ, 0.1)
        table.insert(snapPoints, {
            position = localPos,
            rotation = { 0, 0, 0 },
            rotation_snap = true,
            -- No `tags` here: tags restrict a snap point to only objects
            -- carrying that same tag (via object.addTag()) -- cards never
            -- get one, so a tagged snap point silently accepts nothing.
            -- slot.tag is still used for the zone's name below, where it's
            -- just an identifying label, not a filter.
        })

        local worldPos = fracToWorld(slot.fracX, slot.fracZ, ZONE_HEIGHT / 2)
        local zone = spawnObject({
            type = "ScriptingTrigger",
            position = worldPos,
            rotation = { 0, self.getRotation().y, 0 },
            scale = { slot.sizeFrac.x * bounds.size.x, ZONE_HEIGHT, slot.sizeFrac.z * bounds.size.z },
        })
        zone.setName("BoardZone_" .. slot.tag)
    end

    self.setSnapPoints(snapPoints)
end

-- TEMP DIAGNOSTIC -- onObjectEnterZone/onObjectLeaveZone fire for every
-- zone in the whole game, in every object's script, not just this board's
-- own -- filter to zones named "BoardZone_*" that are actually close to
-- this board so multiple Board instances don't spam each other. Remove
-- once zone behavior is confirmed working.
local function isOwnZone(zone)
    if not zone.getName():find("^BoardZone_") then return false end
    local origin = self.getPosition()
    local p = zone.getPosition()
    local dx, dz = p.x - origin.x, p.z - origin.z
    return math.sqrt(dx * dx + dz * dz) < 30
end

function onObjectEnterZone(zone, enter_object)
    if isOwnZone(zone) then
        -- use_snap_points lives on the DRAGGED object, not the board -- an
        -- object with it disabled will never lock onto any of this board's
        -- snap points no matter how correct their positions are. Force it
        -- on as soon as something wanders into one of our zones, so it's
        -- already enabled by the time the player actually drops it.
        if not enter_object.use_snap_points then
            enter_object.use_snap_points = true
        end
        -- printToAll(zone.getName() .. " ENTER: " .. enter_object.getName() .. " (" .. enter_object.tag .. ")", { 0, 1, 1 })
    end
end

function onObjectLeaveZone(zone, leave_object)
    if isOwnZone(zone) then
        -- printToAll(zone.getName() .. " LEAVE: " .. leave_object.getName() .. " (" .. leave_object.tag .. ")", { 1, 0.5, 0 })
    end
end

-- onObjectDrop fires for every object dropped anywhere, in every object's
-- own script -- only react when this specific board is the one that moved.
-- Snap points are genuinely local to the object so they track it for free;
-- zones are independent objects at a fixed world position, so they need to
-- be torn down and respawned at the board's new spot.
--
-- The rebuild is delayed rather than run immediately on drop: onObjectDrop
-- fires the instant the object is released, which can be before its smooth
-- move/rotate animation has actually finished settling. Reading
-- getBounds()/getRotation() at that instant risks baking in a transient,
-- not-yet-final transform, which would throw off every zone by however far
-- the board still had left to travel/rotate.
function onObjectDrop(player_color, dropped_object)
    if dropped_object == self then
        Wait.time(buildSlotZonesAndSnapPoints, 0.5)
    end
    if dropped_object.tag == "Card" then
        -- printToAll("Card dropped: " .. dropped_object.getName() .. " (" .. dropped_object.guid .. ")", { 1, 1, 0 })
    end
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

    buildSlotZonesAndSnapPoints()
end

function on_btn_money(obj, color, alt_click)
    if alt_click then
        if State.money > 0 then
            State.money = State.money - 1
        end
    else
        State.money = State.money + 1
    end
    b_display_money.label = tostring(State.money)
    obj.editButton(b_display_money)
end

function on_btn_leaf(obj, color, alt_click)
    if alt_click then
        if State.leaf > 0 then
            State.leaf = State.leaf - 1
        end
    else
        State.leaf = State.leaf + 1
    end
    b_display_leaf.label = tostring(State.leaf)
    obj.editButton(b_display_leaf)
end

function on_btn_rock(obj, color, alt_click)
    if alt_click then
        if State.rock > 0 then
            State.rock = State.rock - 1
        end
    else
        State.rock = State.rock + 1
    end
    b_display_rock.label = tostring(State.rock)
    obj.editButton(b_display_rock)
end

function on_btn_water(obj, color, alt_click)
    if alt_click then
        if State.water > 0 then
            State.water = State.water - 1
        end
    else
        State.water = State.water + 1
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