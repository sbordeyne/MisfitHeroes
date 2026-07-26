function onSave()
    return JSON.encode(state)
end

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
    b_display_leaf = generateButtons("leaf", state)
    b_display_rock = generateButtons("rock", state)
    b_display_water = generateButtons("water", state)
    b_display_points = generateButtons("points", state)
    b_display_money = generateButtons("money", state)
end

function increase_leaf()
    state.leaf = state.leaf + 1
    b_display_leaf.label = tostring(state.leaf)
end

function increase_rock()
    state.rock = state.rock + 1
    b_display_rock.label = tostring(state.rock)
end

function increase_water()
    state.water = state.water + 1
    b_display_water.label = tostring(state.water)
end

function increase_points()
    state.points = state.points + 1
    b_display_points.label = tostring(state.points)
end

function increase_money()
    state.money = state.money + 1
    b_display_money.label = tostring(state.money)
end

function decrease_leaf()
    if state.leaf > 0 then
        state.leaf = state.leaf - 1
        b_display_leaf.label = tostring(state.leaf)
    end
end

function decrease_rock()
    if state.rock > 0 then
        state.rock = state.rock - 1
        b_display_rock.label = tostring(state.rock)
    end
end

function decrease_water()
    if state.water > 0 then
        state.water = state.water - 1
        b_display_water.label = tostring(state.water)
    end
end

function decrease_points()
    if state.points > 0 then
        state.points = state.points - 1
        b_display_points.label = tostring(state.points)
    end
end

function decrease_money()
    if state.money > 0 then
        state.money = state.money - 1
        b_display_money.label = tostring(state.money)
    end
end


function increase5_leaf()
    state.leaf = state.leaf + 5
    b_display_leaf.label = tostring(state.leaf)
end

function increase5_rock()
    state.rock = state.rock + 5
    b_display_rock.label = tostring(state.rock)
end

function increase5_water()
    state.water = state.water + 5
    b_display_water.label = tostring(state.water)
end

function increase5_points()
    state.points = state.points + 5
    b_display_points.label = tostring(state.points)
end

function increase5_money()
    state.money = state.money + 5
    b_display_money.label = tostring(state.money)
end

function decrease5_leaf()
    if state.leaf >= 5 then
        state.leaf = state.leaf - 5
        b_display_leaf.label = tostring(state.leaf)
    end
end

function decrease5_rock()
    if state.rock >= 5 then
        state.rock = state.rock - 5
        b_display_rock.label = tostring(state.rock)
    end
end

function decrease5_water()
    if state.water >= 5 then
        state.water = state.water - 5
        b_display_water.label = tostring(state.water)
    end
end

function decrease5_points()
    if state.points >= 5 then
        state.points = state.points - 5
        b_display_points.label = tostring(state.points)
    end
end

function decrease5_money()
    if state.money >= 5 then
        state.money = state.money - 5
        b_display_money.label = tostring(state.money)
    end
end

function generateButtons(resource, state)
    local resource_count = state[resource]

    local b_display = {
        index = 0, click_function = '', function_owner = self, label = tostring(resource_count),
        position = {0,0.1,0}, width = 600, height = 600, font_size = 500
    }
    local b_plus = {
        click_function = 'increase_'..resource, function_owner = self, label =  '+1',
        position = {0.75,0.1,0.26}, width = 150, height = 300, font_size = 100
    }
    local b_minus = {
        click_function = 'decrease_'..resource, function_owner = self, label =  '-1',
        position = {-0.75,0.1,0.26}, width = 150, height = 300, font_size = 100
    }
    local b_plus5 = {
        click_function = 'increase5_'..resource, function_owner = self, label =  '+5',
        position = {0.75,0.1,-0.29}, width = 150, height = 230, font_size = 100
    }
    local b_minus5 = {
        click_function = 'decrease5_'..resource, function_owner = self, label =  '-5',
        position = {-0.75,0.1,-0.29}, width = 150, height = 230, font_size = 100
    }


    self.createButton(b_display)
    self.createButton(b_plus)
    self.createButton(b_minus)
    self.createButton(b_plus5)
    self.createButton(b_minus5)
    return b_display
end