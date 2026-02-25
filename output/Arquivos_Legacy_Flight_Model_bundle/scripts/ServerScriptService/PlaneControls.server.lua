-- Extracted from RBXMX
-- Class: Script
-- Name: PlaneControls
-- Path: ServerScriptService/PlaneControls

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local remote = ReplicatedStorage:WaitForChild("PlaneControls")

remote.OnServerEvent:Connect(function(player, seat, payload)
	-- valida seat
	if typeof(seat) ~= "Instance" or not seat:IsA("VehicleSeat") then return end

	-- garante que o player está sentado nesse seat
	local char = player.Character
	if not char then return end
	local humanoid = char:FindFirstChildOfClass("Humanoid")
	if not humanoid then return end
	if humanoid.SeatPart ~= seat then return end

	local rudder = 0
	local flaps = nil

	-- backward-compat: payload antigo (number = rudder)
	if type(payload) == "number" then
		rudder = payload
	elseif type(payload) == "table" then
		if type(payload.Rudder) == "number" then rudder = payload.Rudder end
		if type(payload.Flaps) == "number" then flaps = payload.Flaps end
	else
		return
	end

	rudder = math.clamp(rudder, -1, 1)
	seat:SetAttribute("Rudder", rudder) -- Attributes API :contentReference[oaicite:3]{index=3}

	if flaps ~= nil then
		flaps = math.clamp(flaps, 0, 1)
		seat:SetAttribute("Flaps", flaps)
	end
end)