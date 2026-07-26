function onSave()
    return JSON.encode(state)
end

state = {}

function onLoad(saved_data)
    --Checks if there is a saved data. If there is, it gets the saved value for 'count'
    if saved_data ~= '' then
        local loaded_data = JSON.decode(saved_data)
        state = loaded_data
    else
        local player_order = tonumber(self.getDescription())
        state = {
            order = player_order,
            money = 35 + 5 * (player_order - 1),
            water = 0,
            rock = 0,
            leaf = 0,
            points = 0,
            cards = {},
        }
    end
    b_display_leaf = generateButtons("leaf", 0, {1})
    b_display_rock = generateButtons("rock", 1, {1})
    b_display_water = generateButtons("water", 2, {1})
    b_display_points = generateButtons("points", 3, {1})
    b_display_money = generateButtons("money", 4, {1, 5, 10})
end

function increase_leaf()
    state.leaf = state.leaf + 1
    b_display_leaf.label = tostring(state.leaf)
    self.editButton(b_display_leaf)
end

function increase_rock()
    state.rock = state.rock + 1
    b_display_rock.label = tostring(state.rock)
    self.editButton(b_display_rock)
end

function increase_water()
    state.water = state.water + 1
    b_display_water.label = tostring(state.water)
    self.editButton(b_display_water)
end

function increase_money()
    state.money = state.money + 1
    b_display_money.label = tostring(state.money)
    self.editButton(b_display_money)
end

function decrease_leaf()
    if state.leaf > 0 then
        state.leaf = state.leaf - 1
        b_display_leaf.label = tostring(state.leaf)
        self.editButton(b_display_leaf)
    end
end

function decrease_rock()
    if state.rock > 0 then
        state.rock = state.rock - 1
        b_display_rock.label = tostring(state.rock)
        self.editButton(b_display_rock)
    end
end

function decrease_water()
    if state.water > 0 then
        state.water = state.water - 1
        b_display_water.label = tostring(state.water)
        self.editButton(b_display_water)
    end
end

function decrease_money()
    if state.money > 0 then
        state.money = state.money - 1
        b_display_money.label = tostring(state.money)
        self.editButton(b_display_money)
    end
end

function increase5_money()
    state.money = state.money + 5
    b_display_money.label = tostring(state.money)
    self.editButton(b_display_money)
end

function decrease5_money()
    if state.money >= 5 then
        state.money = state.money - 5
        b_display_money.label = tostring(state.money)
        self.editButton(b_display_money)
    end
end

function increase10_money()
    state.money = state.money + 10
    b_display_money.label = tostring(state.money)
    self.editButton(b_display_money)
end

function decrease10_money()
    if state.money >= 10 then
        state.money = state.money - 10
        b_display_money.label = tostring(state.money)
        self.editButton(b_display_money)
    end
end

function generateButtons(resource, index, increments)
    local resource_count = 0
    if increments == nil then
        increments = {1}
    end

    local b_display = {
        index = index, click_function = '', function_owner = self, label = tostring(resource_count),
        position = {0,0.1,-10 * index}, width = 600, height = 600, font_size = 500
    }
    for i, increment in ipairs(increments) do
        local b_plus = {
            click_function = 'increase'..increment..'_'..resource, function_owner = self, label =  '+'..increment,
            position = {0.75,0.1,0.26 - (i-1)*0.55}, width = 15, height = 30, font_size = 10
        }
        local b_minus = {
            click_function = 'decrease'..increment..'_'..resource, function_owner = self, label =  '-'..increment,
            position = {-0.75,0.1,0.26 - (i-1)*0.55}, width = 15, height = 30, font_size = 10
        }
        self.createButton(b_plus)
        self.createButton(b_minus)
    end

    self.createButton(b_display)
    return b_display
end