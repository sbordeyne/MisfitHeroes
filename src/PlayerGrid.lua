-- ==============================================
-- MISFIT HEROES - Per-player 4x4 placement grid
-- ==============================================
-- One PlayerGrid owns a physical base object (carries the snap points and
-- the world-space UI overlay used to color cells) plus 16 ScriptingTrigger
-- zones -- one per cell -- used to detect which card, if any, occupies each
-- cell. Global.lua owns the seated-player layout (positions/facing) and the
-- onObjectEnterZone/onObjectLeaveZone hooks that dispatch into this module.
--
-- Placement rule: a cell is legal if it is empty AND either it's the
-- bottom-left corner (row 1, col 1) while the grid is still entirely empty,
-- or it has at least one orthogonally (not diagonally) adjacent occupied
-- neighbor. Row 1 = nearest the owning player, col 1 = that player's left --
-- both defined in the grid's own local space, so this holds regardless of
-- where the grid is placed/rotated on the table.

PlayerGrid = {}
PlayerGrid.__index = PlayerGrid

local GRID_SIZE = 4
-- World-unit spacing between adjacent cell centers. Starting point only --
-- needs eyeballing against the live table/card assets (same caveat as
-- DECAL_SCALE/LAYOUT in Card.lua).
local CELL_SPACING = 2.5
local ZONE_HEIGHT = 3

local COLOR_LEGAL = "#3DDC5AAA"
local COLOR_ILLEGAL = "#00000000" -- fully transparent: no highlight

-- zone GUID -> {grid = PlayerGrid, row = n, col = n}, so the global
-- onObjectEnterZone/onObjectLeaveZone hooks in Global.lua can dispatch here.
PlayerGrid.zoneIndex = {}
-- player color -> PlayerGrid instance
PlayerGrid.instances = {}

--------------------------------------------------------------------------
-- Construction
--------------------------------------------------------------------------

-- centerPos: {x, y, z} world position of the grid's center.
-- facingAngle: degrees around Y; row 1 (bottom) points toward -local Z
-- before rotation, i.e. "toward the player" once facingAngle points the
-- grid at whoever owns it.
function PlayerGrid.new(color, centerPos, facingAngle)
    local self = setmetatable({}, PlayerGrid)
    self.color = color
    self.centerPos = centerPos
    self.facingAngle = facingAngle

    self.occupied = {}
    for r = 1, GRID_SIZE do
        self.occupied[r] = {}
        for c = 1, GRID_SIZE do
            self.occupied[r][c] = false
        end
    end
    self.zones = {}

    return self
end

function PlayerGrid:isEmpty()
    for r = 1, GRID_SIZE do
        for c = 1, GRID_SIZE do
            if self.occupied[r][c] then return false end
        end
    end
    return true
end

--------------------------------------------------------------------------
-- Geometry helpers
--------------------------------------------------------------------------

-- Rotates a local (x, z) offset by the grid's facing angle and adds it to
-- the grid's world center.
function PlayerGrid:localToWorld(localX, localZ)
    local rad = math.rad(self.facingAngle)
    local worldX = localX * math.cos(rad) - localZ * math.sin(rad)
    local worldZ = localX * math.sin(rad) + localZ * math.cos(rad)
    return {
        x = self.centerPos.x + worldX,
        y = self.centerPos.y,
        z = self.centerPos.z + worldZ,
    }
end

-- Local-space (x, z) offset of cell (row, col) from the grid center.
function PlayerGrid:cellLocalOffset(row, col)
    local x = (col - (GRID_SIZE + 1) / 2) * CELL_SPACING
    local z = (row - (GRID_SIZE + 1) / 2) * CELL_SPACING
    return x, z
end

local function cellKey(row, col)
    return row .. "_" .. col
end

--------------------------------------------------------------------------
-- Build: base object, snap points, zones
--------------------------------------------------------------------------

function PlayerGrid:build()
    self.base = spawnObject({
        type = "BlockSquare",
        position = self.centerPos,
        rotation = { 0, self.facingAngle, 0 },
        -- Must stay uniform {1,1,1}: both setSnapPoints' local `position`
        -- and an attached UI Panel's `scale` attribute (see refreshHighlights)
        -- are applied on top of the object's own scale, so sizing the base's
        -- footprint via a non-uniform object scale would silently blow up
        -- the snap point positions and crush/distort the cell highlights
        -- (same bug that made ControlPanel render nothing).
        scale = { 1, 1, 1 },
    })
    self.base.setName("MisfitGrid_" .. self.color)
    self.base.setColorTint({ 0.15, 0.15, 0.15 })
    self.base.setLock(true)
    self.base.interactable = false -- a snap/zone/UI carrier, not something players grab

    self:buildSnapPoints()
    self:buildZones()
    self:refreshHighlights()
end

function PlayerGrid:buildSnapPoints()
    local points = {}
    for row = 1, GRID_SIZE do
        for col = 1, GRID_SIZE do
            local x, z = self:cellLocalOffset(row, col)
            table.insert(points, {
                position = { x, 1, z }, -- local to the base object
                rotation = { 0, 0, 0 },
                rotation_snap = true,
                tags = { "MisfitCard", self.color },
            })
        end
    end
    self.base.setSnapPoints(points)
end

function PlayerGrid:buildZones()
    for row = 1, GRID_SIZE do
        for col = 1, GRID_SIZE do
            local worldPos = self:localToWorld(self:cellLocalOffset(row, col))
            worldPos.y = self.centerPos.y + ZONE_HEIGHT / 2

            local zone = spawnObject({
                type = "ScriptingTrigger",
                position = worldPos,
                rotation = { 0, self.facingAngle, 0 },
                scale = { CELL_SPACING * 0.9, ZONE_HEIGHT, CELL_SPACING * 0.9 },
            })
            zone.setName("MisfitZone_" .. self.color .. "_" .. row .. "_" .. col)

            self.zones[cellKey(row, col)] = zone
            PlayerGrid.zoneIndex[zone.getGUID()] = { grid = self, row = row, col = col }
        end
    end
end

function PlayerGrid:destroy()
    for _, zone in pairs(self.zones) do
        PlayerGrid.zoneIndex[zone.getGUID()] = nil
        zone.destruct()
    end
    self.zones = {}
    if self.base then
        self.base.destruct()
        self.base = nil
    end
end

--------------------------------------------------------------------------
-- Occupancy / legal-cell rule
--------------------------------------------------------------------------

-- Re-scans the zone's contents (rather than trusting a single enter/leave
-- object) so stacked/overlapping objects don't desync the occupancy table.
function PlayerGrid:refreshOccupancy(row, col)
    local zone = self.zones[cellKey(row, col)]
    local hasCard = false
    for _, obj in ipairs(zone.getObjects()) do
        if obj.tag == "Card" then
            hasCard = true
            break
        end
    end
    self.occupied[row][col] = hasCard
end

function PlayerGrid:hasOccupiedNeighbor(row, col)
    local deltas = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }
    for _, d in ipairs(deltas) do
        local r, c = row + d[1], col + d[2]
        if r >= 1 and r <= GRID_SIZE and c >= 1 and c <= GRID_SIZE and self.occupied[r][c] then
            return true
        end
    end
    return false
end

function PlayerGrid:isLegal(row, col)
    if self.occupied[row][col] then return false end
    if self:isEmpty() then
        return row == 1 and col == 1
    end
    return self:hasOccupiedNeighbor(row, col)
end

--------------------------------------------------------------------------
-- Highlighting (world-space UI overlay, attached to the base object)
--------------------------------------------------------------------------

function PlayerGrid:refreshHighlights()
    local elements = {}
    for row = 1, GRID_SIZE do
        for col = 1, GRID_SIZE do
            local x, z = self:cellLocalOffset(row, col)
            local color = self:isLegal(row, col) and COLOR_LEGAL or COLOR_ILLEGAL

            table.insert(elements, {
                tag = "Panel",
                attributes = {
                    id = "cell_" .. cellKey(row, col),
                    position = string.format("%f 0.1 %f", x, z),
                    rotation = "90 0 0",
                    scale = "0.01 0.01 0.01",
                    width = tostring(math.floor(CELL_SPACING * 0.85 * 100)),
                    height = tostring(math.floor(CELL_SPACING * 0.85 * 100)),
                    color = color,
                },
            })
        end
    end
    self.base.UI.setXmlTable(elements)
end

--------------------------------------------------------------------------
-- Zone event dispatch (called from Global.lua's onObjectEnterZone/LeaveZone)
--------------------------------------------------------------------------

function PlayerGrid.handleZoneEvent(zone)
    local entry = PlayerGrid.zoneIndex[zone.getGUID()]
    if not entry then return end
    entry.grid:refreshOccupancy(entry.row, entry.col)
    entry.grid:refreshHighlights()
end
