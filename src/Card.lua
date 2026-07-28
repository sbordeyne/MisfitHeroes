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
        local player_order = 1
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

function render()
end