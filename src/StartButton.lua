function onLoad(state)
    button = self.createButton({
        click_function = "startGame",
        function_owner = self,
        label = "Start Game",
        position = { 0, 0.3, 0 },
        rotation = { 0, 180, 0 },
        width = 2000,
        height = 500,
        font_size = 250
    })
end

function startGame()
    Global.call("startGame")
end
